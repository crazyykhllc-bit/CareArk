import asyncio
import copy
import logging
import tempfile
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, or_, select, update

from app.batch_schemas import validate_sources
from app.models import UploadBatch, BatchFile, Attachment, SourceUnit
from app.services.extraction import ExtractionError
from app.services.medication_grouping import associate_unidentified_medication_faces
from app.services.preprocess import DocumentPreprocessor


logger = logging.getLogger(__name__)


class BatchProcessor:
    def __init__(self, session_factory, storage, extractor, settings):
        self.session_factory, self.storage, self.extractor, self.settings = session_factory, storage, extractor, settings
        self.preprocessor = DocumentPreprocessor(settings.model_max_pages)

    async def claim_next(self):
        now = datetime.now(timezone.utc)
        async with self.session_factory() as db:
            batch = await db.scalar(select(UploadBatch).where(or_(
                and_(UploadBatch.status == 'queued', or_(UploadBatch.next_attempt_at.is_(None), UploadBatch.next_attempt_at <= now)),
                and_(UploadBatch.status.in_(['preprocessing', 'extracting']), UploadBatch.lease_expires_at < now)
            )).order_by(UploadBatch.created_at).with_for_update(skip_locked=True).limit(1))
            if not batch:
                return None
            batch.status = 'preprocessing'
            batch.attempt_token = str(uuid.uuid4())
            batch.lease_expires_at = now + timedelta(minutes=3)
            await db.commit()
            return batch.id, batch.attempt_token

    async def heartbeat(self, batch_id, token):
        while True:
            await asyncio.sleep(30)
            async with self.session_factory() as db:
                await db.execute(update(UploadBatch).where(UploadBatch.id == batch_id, UploadBatch.attempt_token == token,
                    UploadBatch.status.in_(['preprocessing', 'extracting'])).values(lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=3)))
                await db.commit()

    async def process(self, batch_id, token=None):
        batch_id = uuid.UUID(str(batch_id))
        async with self.session_factory() as db:
            batch = await db.get(UploadBatch, batch_id)
            if not batch or batch.status not in {'queued', 'preprocessing', 'extracting'}:
                return
            if token and batch.attempt_token != token:
                return
            token = token or str(uuid.uuid4())
            batch.attempt_token, batch.status = token, 'preprocessing'
            batch.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)
            await db.commit()
            beat = asyncio.create_task(self.heartbeat(batch_id, token))
            try:
                rows = (await db.execute(select(BatchFile, Attachment).join(Attachment, Attachment.id == BatchFile.attachment_id)
                    .where(BatchFile.batch_id == batch.id, Attachment.owner_id == batch.owner_id).order_by(BatchFile.ordinal))).all()
                sources, file_sources = [], {}
                for entry, attachment in rows:
                    stream = await self.storage.get(attachment.object_key)
                    try:
                        data = await asyncio.to_thread(stream.read)
                    finally:
                        if hasattr(stream, 'close'):
                            stream.close()
                    with tempfile.TemporaryDirectory() as temp:
                        path = Path(temp) / ('source' + Path(attachment.filename).suffix)
                        path.write_bytes(data)
                        prepared = await asyncio.to_thread(self.preprocessor.prepare, path, attachment.mime_type)
                    parts = [('image', p) for p in prepared.image_parts] + [('text', p) for p in prepared.text_parts]
                    if len(sources) + len(parts) > self.settings.model_max_pages:
                        raise ValueError(f'本批超过 {self.settings.model_max_pages} 页/片段，请拆批处理')
                    file_sources[str(entry.id)] = []
                    for ordinal, (kind, part) in enumerate(parts):
                        source_id = uuid.uuid5(batch.id, f'{attachment.id}:{ordinal}')
                        page = getattr(part, 'page', None)
                        label = f'{attachment.filename} · ' + (f'第 {page} 页' if page else getattr(part, 'label', f'图片 {ordinal + 1}'))
                        if not await db.get(SourceUnit, source_id):
                            db.add(SourceUnit(id=source_id, owner_id=batch.owner_id, batch_id=batch.id,
                                attachment_id=attachment.id, ordinal=ordinal, page_index=page, label=label[:600], kind=kind))
                        item = {'id': str(source_id), 'kind': kind, 'label': label}
                        item['data' if kind == 'image' else 'text'] = part.data if kind == 'image' else part.content
                        if kind == 'image':
                            item['mime_type'] = part.mime_type
                        sources.append(item)
                        file_sources[str(entry.id)].append(str(source_id))
                if not sources:
                    raise ValueError('文件中没有可识别内容')
                grouping = copy.deepcopy(batch.grouping)
                for hints in [grouping.get('groups', []), grouping.get('encounters', [])]:
                    for hint in hints:
                        hint['source_ids'] = [sid for fid in hint['file_ids'] for sid in file_sources.get(fid, [])]
                await db.commit()
                changed = await db.execute(update(UploadBatch).where(UploadBatch.id == batch.id, UploadBatch.attempt_token == token)
                                           .values(status='extracting'))
                await db.commit()
                if not changed.rowcount:
                    return
                result = await self.extractor.extract_batch(sources, grouping)
                validate_sources(result, {x['id'] for x in sources})
                original_payload = result.model_dump(mode='json')
                result = associate_unidentified_medication_faces(result, grouping)
                validate_sources(result, {x['id'] for x in sources})
                # User hints are constraints, not suggestions that may be silently discarded.
                for hint in grouping.get('groups', []):
                    if not any(g.kind == hint['kind'] and set(g.source_ids) == set(hint['source_ids']) for g in result.groups):
                        raise ValueError('模型未保持手动资料分组，请重试或调整分组')
                for hint in grouping.get('encounters', []):
                    selected = set(hint['source_ids'])
                    members = [g for g in result.groups if set(g.source_ids) & selected]
                    visit_ids = {g.encounter_id for g in members}
                    if len(visit_ids) != 1 or None in visit_ids:
                        raise ValueError('模型未保持手动就诊关联，请重试或调整分组')
                result.reviewed = False
                payload = result.model_dump(mode='json')
                await db.execute(update(UploadBatch).where(UploadBatch.id == batch.id, UploadBatch.attempt_token == token,
                    UploadBatch.status == 'extracting').values(status='pending_confirmation', payload=payload,
                    original_payload=original_payload, error_message=None, version=UploadBatch.version + 1, lease_expires_at=None))
                await db.commit()
            except Exception as error:
                frames = traceback.extract_tb(error.__traceback__)
                location = ' > '.join(
                    f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in frames[-5:]
                )
                # Do not log exception text: validation failures can contain
                # extracted medical content. Type and code locations are enough
                # to diagnose unexpected processor defects safely.
                logger.error('Batch %s failed with %s at %s', batch_id, type(error).__name__, location)
                await db.rollback()
                current = await db.get(UploadBatch, batch_id, populate_existing=True)
                if current and current.attempt_token == token and current.status in {'preprocessing', 'extracting'}:
                    current.retry_count += 1
                    retry = isinstance(error, ExtractionError) and error.retryable and current.retry_count <= self.settings.model_max_retries
                    current.status = 'queued' if retry else 'failed'
                    current.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=2 ** current.retry_count) if retry else None
                    current.error_message = str(error)[:500] if isinstance(error, (ExtractionError, ValueError)) else '文件处理失败，请重试或检查文件格式'
                    current.lease_expires_at = None
                    await db.commit()
            finally:
                beat.cancel()
                try:
                    await beat
                except asyncio.CancelledError:
                    pass
