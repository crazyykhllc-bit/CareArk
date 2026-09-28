import hashlib
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.uploads import ALLOWED_MIME_TYPES
from app.batch_schemas import BatchSubmit, SaveBatchDraft, BatchConfirm, CreateBatch, validate_sources
from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models import UploadBatch, BatchFile, SourceUnit, Attachment, User
from app.services.storage import get_storage, ObjectStorage
from app.services.upload_care import create_context, context_json, validate_target
from app.models import UploadCareContext
from app.services.image_previews import preview_urls

router = APIRouter(prefix='/api/batches')


async def owned_batch(db, user, batch_id, *, lock=False):
    query = select(UploadBatch).where(UploadBatch.id == batch_id, UploadBatch.owner_id == user.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    batch = await db.scalar(query)
    if not batch:
        raise HTTPException(404, '上传批次不存在')
    return batch


def check_version(batch, version):
    if batch.version != version:
        raise HTTPException(409, '资料已更新，请刷新后重试')


async def batch_json(db, batch):
    context = await db.get(UploadCareContext, batch.care_context_id) if batch.care_context_id else None
    rows = (await db.execute(select(BatchFile, Attachment).join(Attachment, Attachment.id == BatchFile.attachment_id)
                            .where(BatchFile.batch_id == batch.id, BatchFile.owner_id == batch.owner_id)
                            .order_by(BatchFile.ordinal))).all()
    sources = (await db.scalars(select(SourceUnit).where(SourceUnit.batch_id == batch.id, SourceUnit.owner_id == batch.owner_id)
                               .order_by(SourceUnit.created_at, SourceUnit.ordinal))).all()
    files = [{'id': str(f.id), 'client_file_id': f.client_file_id, 'attachment_id': str(a.id), 'filename': a.filename,
              'mime_type': a.mime_type, 'size_bytes': a.size_bytes, 'sha256': a.sha256,
              'content_url': f'/api/attachments/{a.id}/content', **preview_urls(a)} for f, a in rows]
    return {'id': str(batch.id), 'status': batch.status, 'version': batch.version, 'grouping': batch.grouping,
            'created_at': batch.created_at.isoformat(), 'files': files, 'error_message': batch.error_message,
            'sources': [{'id': str(s.id), 'attachment_id': str(s.attachment_id), 'page_index': s.page_index,
                         'label': s.label, 'kind': s.kind, 'content_url': f'/api/attachments/{s.attachment_id}/content'} for s in sources],
            'payload': batch.payload, 'result': batch.result, 'care_context': context_json(context)}


@router.post('', status_code=201)
async def create_batch(data: CreateBatch | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await create_context(db, user.id, data.care_context if data else None)
    batch = UploadBatch(owner_id=user.id, care_context_id=context.id if context else None)
    db.add(batch)
    await db.commit()
    return await batch_json(db, batch)


@router.get('')
async def list_batches(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(UploadBatch).where(UploadBatch.owner_id == user.id, UploadBatch.status.not_in(['archived', 'cancelled']))
                            .order_by(UploadBatch.created_at.desc()).limit(100))).all()
    return {'items': [await batch_json(db, row) for row in rows]}


@router.get('/limits')
async def batch_limits(user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)):
    return {'max_selection': 100, 'max_files_per_batch': min(settings.batch_max_files, 20),
            'max_bytes_per_batch': settings.batch_max_bytes, 'max_bytes_per_file': settings.upload_max_bytes}


@router.get('/{batch_id}')
async def get_batch(batch_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await batch_json(db, await owned_batch(db, user, batch_id))


@router.post('/{batch_id}/files', status_code=201)
async def upload_file(batch_id: uuid.UUID, client_file_id: str = Form(..., min_length=1, max_length=100),
                      file: UploadFile = File(...), user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db), storage: ObjectStorage = Depends(get_storage),
                      settings: Settings = Depends(get_settings)):
    batch = await owned_batch(db, user, batch_id, lock=True)
    if batch.status != 'receiving':
        raise HTTPException(409, '批次已提交，不能再添加文件')
    existing = await db.scalar(select(BatchFile).where(BatchFile.batch_id == batch.id, BatchFile.client_file_id == client_file_id))
    if existing:
        return await batch_json(db, batch)
    rows = (await db.execute(select(BatchFile, Attachment).join(Attachment, Attachment.id == BatchFile.attachment_id)
                            .where(BatchFile.batch_id == batch.id))).all()
    if len(rows) >= settings.batch_max_files:
        raise HTTPException(413, f'每批最多 {settings.batch_max_files} 个文件，请拆批上传')
    mime = (file.content_type or '').lower()
    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(415, '不支持这种文件格式')
    size, digest = 0, hashlib.sha256()
    total = sum(a.size_bytes for _, a in rows)
    key = f'users/{user.id}/batches/{batch.id}/{uuid.uuid4()}'
    stored = False
    with tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024) as spool:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.upload_max_bytes or size + total > settings.batch_max_bytes:
                raise HTTPException(413, '文件或批次超过大小限制，请移除文件并拆批上传')
            digest.update(chunk)
            spool.write(chunk)
        if not size:
            raise HTTPException(422, '文件为空')
        spool.seek(0)
        try:
            await storage.put(key, spool, size, mime)
            stored = True
            attachment = Attachment(owner_id=user.id, filename=(file.filename or '未命名文件')[:500], mime_type=mime,
                                    size_bytes=size, sha256=digest.hexdigest(), object_key=key)
            db.add(attachment)
            await db.flush()
            db.add(BatchFile(owner_id=user.id, batch_id=batch.id, attachment_id=attachment.id,
                             client_file_id=client_file_id, ordinal=max([f.ordinal for f, _ in rows], default=-1) + 1))
            batch.version += 1
            await db.commit()
        except Exception:
            await db.rollback()
            if stored:
                await storage.delete(key)
            raise
    return await batch_json(db, batch)


@router.delete('/{batch_id}/files/{file_id}')
async def remove_file(batch_id: uuid.UUID, file_id: uuid.UUID, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    batch = await owned_batch(db, user, batch_id, lock=True)
    if batch.status != 'receiving':
        raise HTTPException(409, '仅上传中的批次可移除文件')
    item = await db.scalar(select(BatchFile).where(BatchFile.id == file_id, BatchFile.batch_id == batch.id))
    if not item:
        raise HTTPException(404, '文件不存在')
    await db.delete(item)
    batch.version += 1
    await db.commit()
    return await batch_json(db, batch)


@router.post('/{batch_id}/submit')
async def submit_batch(batch_id: uuid.UUID, data: BatchSubmit, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    batch = await owned_batch(db, user, batch_id, lock=True)
    check_version(batch, data.expected_version)
    if batch.status != 'receiving':
        raise HTTPException(409, '该批次已经提交')
    ids = {str(x) for x in (await db.scalars(select(BatchFile.id).where(BatchFile.batch_id == batch.id))).all()}
    if not ids:
        raise HTTPException(422, '请先上传文件')
    for entries in [data.groups, data.encounters]:
        used, keys = set(), set()
        for entry in entries:
            selected = set(entry.file_ids)
            if not selected <= ids or selected & used or entry.id in keys or len(selected) != len(entry.file_ids):
                raise HTTPException(422, '手动分组包含无效、重复或交叉的文件，请调整')
            used |= selected
            keys.add(entry.id)
    batch.grouping = data.model_dump(exclude={'expected_version'})
    batch.status = 'queued'
    batch.version += 1
    await db.commit()
    return await batch_json(db, batch)


@router.put('/{batch_id}/grouping')
async def save_grouping(batch_id: uuid.UUID, data: BatchSubmit, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    batch = await owned_batch(db, user, batch_id, lock=True)
    check_version(batch, data.expected_version)
    if batch.status != 'receiving':
        raise HTTPException(409, '只有上传中的批次可以调整文件分组')
    ids = {str(x) for x in (await db.scalars(select(BatchFile.id).where(BatchFile.batch_id == batch.id))).all()}
    for entries in [data.groups, data.encounters]:
        used, keys = set(), set()
        for entry in entries:
            selected = set(entry.file_ids)
            if not selected <= ids or selected & used or entry.id in keys:
                raise HTTPException(422, '手动分组引用无效或交叉的文件')
            used |= selected
            keys.add(entry.id)
    batch.grouping = data.model_dump(exclude={'expected_version'})
    batch.version += 1
    await db.commit()
    return await batch_json(db, batch)


@router.post('/{batch_id}/reopen')
async def reopen_batch(batch_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    batch = await owned_batch(db, user, batch_id, lock=True)
    if batch.status != 'failed':
        raise HTTPException(409, '仅失败批次可返回上传分组阶段')
    await db.execute(delete(SourceUnit).where(SourceUnit.batch_id == batch.id, SourceUnit.owner_id == user.id))
    batch.status, batch.error_message, batch.attempt_token = 'receiving', None, None
    batch.payload, batch.original_payload = None, None
    batch.version += 1
    await db.commit()
    return await batch_json(db, batch)


@router.post('/{batch_id}/retry')
async def retry_batch(batch_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    batch = await owned_batch(db, user, batch_id, lock=True)
    if batch.status != 'failed':
        raise HTTPException(409, '只有失败批次可重试')
    batch.status, batch.error_message, batch.next_attempt_at = 'queued', None, None
    batch.retry_count = 0
    batch.version += 1
    await db.commit()
    return await batch_json(db, batch)


@router.post('/{batch_id}/cancel')
async def cancel_batch(batch_id: uuid.UUID, data: BatchConfirm, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    batch = await owned_batch(db, user, batch_id, lock=True)
    if batch.status == 'cancelled':
        return await batch_json(db, batch)
    check_version(batch, data.expected_version)
    if batch.status not in ('receiving', 'failed', 'pending_confirmation'):
        raise HTTPException(409, '请等待正在识别的任务完成后再取消')
    batch.status = 'cancelled'
    batch.version += 1
    await db.commit()
    return await batch_json(db, batch)


@router.get('/{batch_id}/draft')
async def get_draft(batch_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    batch = await owned_batch(db, user, batch_id)
    if not batch.payload:
        raise HTTPException(409, '识别结果尚未生成')
    return await batch_json(db, batch)


@router.put('/{batch_id}/draft')
async def save_draft(batch_id: uuid.UUID, data: SaveBatchDraft, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    batch = await owned_batch(db, user, batch_id, lock=True)
    check_version(batch, data.expected_version)
    if batch.status != 'pending_confirmation':
        raise HTTPException(409, '当前批次不能修改草稿')
    ids = {str(x) for x in (await db.scalars(select(SourceUnit.id).where(SourceUnit.batch_id == batch.id))).all()}
    try:
        validate_sources(data.payload, ids)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if data.care_context is not None:
        if data.care_targets:
            raise HTTPException(422, '整批归属不能同时指定单份资料归属')
        # A review changes this batch only; other automatic batches retain their
        # original shared upload intent. New events are still deferred to confirm.
        context = await create_context(db, user.id, data.care_context)
        batch.care_context_id = context.id
        batch.grouping = {**(batch.grouping or {}), 'care_targets':{}}
    if data.care_targets is not None:
        group_ids = {group.id for group in data.payload.groups}
        if not set(data.care_targets) <= group_ids:
            raise HTTPException(422, '归属引用了不存在的资料组')
        for target in data.care_targets.values():
            if target.mode == 'new_topic':
                raise HTTPException(422, '资料组可使用本次归属，或选择已有大事件')
            await validate_target(db, user.id, target)
        batch.grouping = {**(batch.grouping or {}), 'care_targets':{
            key:target.model_dump(mode='json') for key,target in data.care_targets.items()}}
    batch.payload = data.payload.model_dump(mode='json')
    batch.version += 1
    await db.commit()
    return await batch_json(db, batch)


@router.post('/{batch_id}/confirm')
async def confirm_batch(batch_id: uuid.UUID, data: BatchConfirm, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    from app.services.batch_confirmation import confirm
    batch = await owned_batch(db, user, batch_id, lock=True)
    if batch.status == 'archived':
        return batch.result
    check_version(batch, data.expected_version)
    if batch.status != 'pending_confirmation':
        raise HTTPException(409, '当前批次尚不能确认')
    return await confirm(db, user, batch)
