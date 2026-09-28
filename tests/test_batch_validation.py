import pytest

from app.batch_schemas import BatchExtraction, validate_sources


def group(id, sources, patient=None):
    return {'id': id, 'kind': 'document', 'source_ids': sources, 'patient_identity': patient,
            'document': {'type': '检查报告', 'title': '示例报告'}}


def test_shared_page_allowed_but_unknown_or_unaccounted_sources_rejected():
    payload = BatchExtraction.model_validate({'groups': [group('a', ['s1']), group('b', ['s1'])]})
    validate_sources(payload, {'s1'})
    with pytest.raises(ValueError, match='未分组'):
        validate_sources(payload, {'s1', 's2'})
    with pytest.raises(ValueError, match='不存在'):
        validate_sources(payload, {'s2'})


def test_patient_identity_raw_variants_do_not_block_reviewed_confirmation():
    groups = [group('a', ['s1'], '童某'), group('b', ['s2'], '董某')]
    for item in groups:
        item['encounter_id'] = 'visit'
    payload = BatchExtraction.model_validate({'groups': groups, 'encounters': [
        {'id': 'visit', 'title': '就诊', 'patient_identity': '益某'}], 'reviewed': True})
    validate_sources(payload, {'s1', 's2'}, confirm=True)
    payload.reviewed = False
    with pytest.raises(ValueError, match='核对'):
        validate_sources(payload, {'s1', 's2'}, confirm=True)


def test_drug_identity_uses_product_fields_not_model_key():
    from app.services.batch_confirmation import identity_key
    from app.batch_schemas import BatchMedication
    a = BatchMedication(name='A', strength='10mg', dosage_form='片剂', manufacturer='甲厂')
    b = a.model_copy(update={'strength': '20mg'})
    assert identity_key(a) == identity_key(a)
    assert identity_key(a) != identity_key(b)
    unknown = BatchMedication(name='A')
    assert identity_key(unknown) != identity_key(unknown)


def test_cross_hospital_visit_can_be_confirmed_after_review():
    groups = [group('a', ['s1']), group('b', ['s2'])]
    for item, hospital in zip(groups, ['甲医院', '乙医院']):
        item['encounter_id'] = 'visit'
        item['document']['hospital'] = hospital
    payload = BatchExtraction.model_validate({'groups': groups, 'encounters': [{'id': 'visit', 'title': '就诊'}], 'reviewed': True})
    validate_sources(payload, {'s1', 's2'})
    validate_sources(payload, {'s1', 's2'}, confirm=True)
    payload.reviewed = False
    with pytest.raises(ValueError, match='核对'):
        validate_sources(payload, {'s1', 's2'}, confirm=True)


def test_known_hospital_aliases_and_combined_name_share_one_visit():
    groups = [group('a', ['s1']), group('b', ['s2']), group('c', ['s3'])]
    for item, hospital in zip(groups, [
        '上海市肺科医院', '上海市职业病防治医院', '上海市肺科医院、上海市职业病防治院',
    ]):
        item['encounter_id'] = 'visit'
        item['document']['hospital'] = hospital
    payload = BatchExtraction.model_validate({'groups': groups, 'encounters': [
        {'id': 'visit', 'title': '就诊', 'hospital': '上海市职业病防治院'}], 'reviewed': True})
    validate_sources(payload, {'s1', 's2', 's3'}, confirm=True)


def test_combined_hospital_original_text_is_preserved_after_review():
    groups = [group('a', ['s1']), group('b', ['s2'])]
    groups[0]['encounter_id'] = groups[1]['encounter_id'] = 'visit'
    groups[0]['document']['hospital'] = '上海市肺科医院、其他医院'
    groups[1]['document']['hospital'] = '上海市肺科医院'
    payload = BatchExtraction.model_validate({'groups': groups, 'encounters': [
        {'id': 'visit', 'title': '就诊'}], 'reviewed': True})
    validate_sources(payload, {'s1', 's2'}, confirm=True)
    payload.reviewed = False
    with pytest.raises(ValueError, match='核对'):
        validate_sources(payload, {'s1', 's2'}, confirm=True)
