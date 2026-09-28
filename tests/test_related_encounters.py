import asyncio
import json
import uuid
from io import BytesIO
from zipfile import ZipFile

from app.models import Document, Encounter, User
from tests.test_uploads import setup_admin


def test_cross_hospital_related_care_keeps_visits_distinct(client, session_factory):
    owner = uuid.UUID(setup_admin(client)['id'])

    async def seed():
        async with session_factory() as db:
            document = Document(owner_id=owner, document_type='挂号单 / 就诊单', title='合成门诊',
                                hospital='合成肿瘤医院', key_information=[], extraction_metadata={},
                                type_specific_data={}, patient_scope='self')
            visit = Encounter(owner_id=owner, title='合成手术就诊', hospital='合成肺科医院', evidence=[])
            db.add_all([document, visit])
            await db.commit()
            return str(document.id), str(visit.id)

    document_id, visit_id = asyncio.run(seed())
    same_visit = client.patch(f'/api/documents/{document_id}/encounter', json={
        'expected_version': 1, 'encounter_id': visit_id})
    assert same_visit.status_code == 422
    assert '相关诊疗' in same_visit.json()['detail']

    path = f'/api/documents/{document_id}/related-encounters/{visit_id}'
    assert client.put(path).status_code == 200
    assert client.put(path).status_code == 200
    encounter = client.get('/api/encounters').json()['items'][0]
    assert encounter['related_document_ids'] == [document_id]
    assert client.get(f'/api/documents/{document_id}').json()['encounter_id'] is None
    with ZipFile(BytesIO(client.get('/api/export').content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['related_encounters'] == [{'document_id': document_id, 'encounter_id': visit_id}]

    assert client.delete(path).status_code == 200
    assert client.get('/api/encounters').json()['items'][0]['related_document_ids'] == []


def test_related_care_rejects_unknown_or_other_owner_ids(client, session_factory):
    owner = uuid.UUID(setup_admin(client)['id'])
    assert client.put(f'/api/documents/{uuid.uuid4()}/related-encounters/{uuid.uuid4()}').status_code == 404

    async def seed_other_owner():
        async with session_factory() as db:
            other = User(email='other@example.test', password_hash='unused', role='user', is_active=True)
            db.add(other)
            await db.flush()
            own_doc = Document(owner_id=owner, document_type='检查报告', title='本人资料',
                               key_information=[], extraction_metadata={}, type_specific_data={})
            other_doc = Document(owner_id=other.id, document_type='检查报告', title='其他账号资料',
                                 key_information=[], extraction_metadata={}, type_specific_data={})
            own_visit = Encounter(owner_id=owner, title='本人就诊', evidence=[])
            other_visit = Encounter(owner_id=other.id, title='其他账号就诊', evidence=[])
            db.add_all([own_doc, other_doc, own_visit, other_visit])
            await db.commit()
            return str(own_doc.id), str(other_doc.id), str(own_visit.id), str(other_visit.id)

    own_doc, other_doc, own_visit, other_visit = asyncio.run(seed_other_owner())
    assert client.put(f'/api/documents/{own_doc}/related-encounters/{other_visit}').status_code == 404
    assert client.put(f'/api/documents/{other_doc}/related-encounters/{own_visit}').status_code == 404
