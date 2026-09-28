import pytest
from pydantic import ValidationError

from app.batch_schemas import GroupDetailExtraction
from app.schemas import ExtractionDraft
from app.services.care_history import classify_document


def valid_payload():
    return {
        "document": {
            "type": "检验报告",
            "title": "甲状腺功能",
            "primary_date": None,
            "primary_date_raw": "日期不清",
            "hospital": None,
            "department": None,
            "doctor": None,
            "amount": None,
            "key_information": [],
            "parsed_content": None,
            "source_refs": [],
        },
        "lab_results": [],
        "medications": [],
        "review_items": ["主要日期无法确认"],
    }


def test_uncertain_fields_can_be_null():
    draft = ExtractionDraft.model_validate(valid_payload())

    assert draft.document.primary_date is None
    assert draft.review_items == ["主要日期无法确认"]


def test_extra_fields_are_rejected():
    payload = valid_payload()
    payload["invented"] = True

    with pytest.raises(ValidationError):
        ExtractionDraft.model_validate(payload)


def test_lab_result_preserves_non_numeric_original():
    payload = valid_payload()
    payload["lab_results"] = [{
        "name": "促甲状腺激素",
        "result": "<0.01",
        "unit": "mIU/L",
        "reference_range": "0.27-4.2",
        "flag": "↓",
        "source_ref": {"page": 1, "quote": "TSH <0.01 ↓"},
    }]

    draft = ExtractionDraft.model_validate(payload)

    assert draft.lab_results[0].result == "<0.01"


def test_outpatient_record_is_valid_in_single_and_batch_extraction():
    payload = valid_payload()
    payload['document']['type'] = '门诊病历'
    payload['document']['title'] = '合成门诊记录'

    single = ExtractionDraft.model_validate(payload)
    batch = GroupDetailExtraction.model_validate({
        'id': 'g1', 'kind': 'document', 'source_ids': ['s1'],
        'document': {**payload['document'], 'parsed_content': None},
    })

    assert single.document.type == batch.document.type == '门诊病历'
    assert classify_document(batch.document.type) == 'outpatient'
