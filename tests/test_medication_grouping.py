from app.batch_schemas import BatchExtraction, validate_sources
from app.services.medication_grouping import associate_unidentified_medication_faces


def extraction(*, second_name='待核对药品'):
    return BatchExtraction.model_validate({'groups': [
        {'id': 'named', 'kind': 'medication', 'source_ids': ['front', 'leaflet'],
         'document': {'type': '其他医疗资料', 'title': '甲药包装', 'parsed_content': '正面和说明书'},
         'medications': [{'name': '甲药', 'generic_name': '甲药通用名', 'packages': [
             {'quantity_raw': '120喷', 'source_ids': ['front', 'leaflet']}]}]},
        {'id': 'bottom', 'kind': 'medication', 'source_ids': ['bottom'],
         'document': {'type': '其他医疗资料', 'title': '待核对药品包装', 'parsed_content': '生产日期原文'},
         'medications': [{'name': second_name, 'packages': [
             {'batch_number': 'B42', 'expiry_date': '2027-09-20', 'source_ids': ['bottom']}]}],
         'evidence': [{'source_id': 'bottom', 'field': 'medications[0].packages[0].batch_number', 'quote': 'B42'}]},
    ]})


def test_unidentified_bottom_face_is_provisionally_attached_to_sole_identified_drug():
    result = associate_unidentified_medication_faces(extraction(), {'groups': []})
    validate_sources(result, {'front', 'leaflet', 'bottom'})
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.source_ids == ['front', 'leaflet', 'bottom']
    assert group.medications[0].name == '甲药'
    assert len(group.medications[0].packages) == 1
    assert group.medications[0].packages[0].batch_number == 'B42'
    assert group.medications[0].packages[0].quantity_raw == '120喷'
    assert set(group.medications[0].packages[0].source_ids) == {'front', 'leaflet', 'bottom'}
    assert '生产日期原文' in group.document.parsed_content
    assert any('人工核对' in item for item in group.review_items)


def test_other_named_drug_or_manual_split_is_not_assumed_to_be_same():
    assert len(associate_unidentified_medication_faces(extraction(second_name='乙药'), {'groups': []}).groups) == 2
    hint = {'groups': [{'kind': 'medication', 'source_ids': ['bottom']}]}
    assert len(associate_unidentified_medication_faces(extraction(), hint).groups) == 2


def test_two_identified_drug_candidates_leave_unidentified_face_separate():
    result = extraction()
    another = result.groups[0].model_copy(deep=True)
    another.id = 'other'
    another.source_ids = ['other-front']
    another.medications[0].name = '乙药'
    result.groups.append(another)
    assert len(associate_unidentified_medication_faces(result, {'groups': []}).groups) == 3
