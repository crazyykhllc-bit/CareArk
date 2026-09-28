"""PostgreSQL concurrency smoke test in a disposable, isolated database.

Run inside the web container. No model or object-storage API calls are made.
"""
import asyncio
import os
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.batches import confirm_batch
from app.api.care_hierarchy import Upgrade, upgrade
from app.batch_schemas import BatchConfirm, UploadCareIntent
from app.models import Attachment, Base, CareTopic, Document, Encounter, SourceUnit, UploadBatch, User
from app.services.upload_care import create_context


async def main():
    admin = create_async_engine(os.environ['DATABASE_URL'], isolation_level='AUTOCOMMIT')
    name = 'care_verify_' + uuid4().hex
    engine = create_async_engine(admin.url.set(database=name))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    try:
        async with admin.connect() as db:
            await db.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            user = User(email='synthetic@example.test',password_hash='synthetic',role='user')
            db.add(user)
            await db.commit()
            owner_id = user.id
        intent = UploadCareIntent(intent_key=uuid4().hex,mode='new_topic',name='Synthetic continuing care')

        async def prepare(hospital, target=None, existing_event=None):
            async with sessions() as db:
                context = await create_context(db,owner_id,target or intent)
                batch = UploadBatch(owner_id=owner_id,care_context_id=context.id,status='pending_confirmation')
                attachment = Attachment(owner_id=owner_id,filename='synthetic.png',mime_type='image/png',
                    size_bytes=1,sha256='0'*64,object_key=uuid4().hex)
                db.add_all([batch,attachment])
                await db.flush()
                source = SourceUnit(owner_id=owner_id,batch_id=batch.id,attachment_id=attachment.id,
                    ordinal=0,label='synthetic',kind='image')
                db.add(source)
                await db.flush()
                batch.payload={'groups':[{'id':'g','kind':'document','source_ids':[str(source.id)],
                    'encounter_id':'v','document':{'type':'其他医疗资料','title':'Synthetic source','hospital':hospital}}],
                    'encounters':[{'id':'v','title':'Synthetic visit','hospital':hospital,
                        'existing_encounter_id':str(existing_event) if existing_event else None}],
                    'excluded_sources':[],'reviewed':True}
                await db.commit()
                return batch.id
        batches = await asyncio.gather(prepare('Synthetic hospital A'),prepare('Synthetic hospital B'))

        async def confirm_one(batch_id):
            async with sessions() as db:
                user = await db.get(User,owner_id)
                return await confirm_batch(batch_id,BatchConfirm(expected_version=1),user,db)
        results = await asyncio.wait_for(asyncio.gather(*(confirm_one(x) for x in batches)),30)
        assert await confirm_one(batches[0]) == results[0]
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(CareTopic)) == 1
            assert await db.scalar(select(func.count()).select_from(Document)) == 2
            children=list((await db.scalars(select(Encounter))).all())
            assert len(children)==2 and children[0].primary_topic_id==children[1].primary_topic_id
            parent_id=children[0].primary_topic_id
            supplemental=Encounter(owner_id=owner_id,title='Synthetic supplemental visit',
                hospital='Synthetic hospital C',primary_topic_id=parent_id)
            db.add(supplemental)
            await db.commit()
            supplemental_id=supplemental.id
            event=Encounter(owner_id=owner_id,title='Synthetic upgrade')
            db.add(event)
            await db.commit()
            event_id=event.id

        targets=[UploadCareIntent(intent_key=uuid4().hex,mode='existing_topic',topic_id=parent_id) for _ in range(2)]
        supplements=await asyncio.gather(*(prepare('Synthetic hospital C',target,supplemental_id) for target in targets))
        await asyncio.wait_for(asyncio.gather(*(confirm_one(x) for x in supplements)),30)
        async with sessions() as db:
            assert (await db.get(Encounter,supplemental_id)).version == 3
            assert await db.scalar(select(func.count()).select_from(Document).where(
                Document.encounter_id==supplemental_id)) == 2

        async def upgrade_one():
            async with sessions() as db:
                user=await db.get(User,owner_id)
                return await upgrade(event_id,Upgrade(expected_version=1,name='Synthetic upgrade'),user,db)
        upgraded=await asyncio.wait_for(asyncio.gather(upgrade_one(),upgrade_one()),30)
        assert upgraded[0]['topic_id']==upgraded[1]['topic_id']
        print('PASS: concurrent shared intent, concurrent confirmation, concurrent existing visit supplement, idempotent retry, concurrent upgrade')
    finally:
        await engine.dispose()
        if created:
            async with admin.connect() as db:
                await db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


if __name__ == '__main__':
    asyncio.run(main())
