import json

import httpx
import pytest

from app.config import Settings
from app.schemas import ExtractionDraft
from app.services.extraction import ExtractionError, OpenAICompatibleExtractor, strict_json_schema
from app.services.preprocess import PreparedDocument, TextPart


VALID_DRAFT = {
    "document": {
        "type": "检验报告",
        "title": "血常规",
        "primary_date": "2026-09-06",
        "primary_date_raw": "2026-09-06",
        "hospital": "示例医院",
        "department": None,
        "doctor": None,
        "amount": None,
        "key_information": [],
        "parsed_content": "白细胞 5.0",
        "source_refs": [],
    },
    "lab_results": [],
    "medications": [],
    "review_items": [],
}


def test_strict_schema_requires_every_object_property():
    schema = strict_json_schema(ExtractionDraft.model_json_schema())

    def assert_strict(node):
        if isinstance(node, dict):
            assert '(?' not in node.get('pattern', '')
            if node.get("type") == "object":
                assert "properties" in node
                assert node["required"] == list(node["properties"])
                assert node["additionalProperties"] is False
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict(value)

    assert_strict(schema)


@pytest.mark.asyncio
async def test_openai_compatible_adapter_sends_strict_schema():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(VALID_DRAFT)}}]})

    settings = Settings(model_api_key="secret", model_name="vision-model", model_base_url="https://model.test/v1")
    extractor = OpenAICompatibleExtractor(settings, transport=httpx.MockTransport(handler))

    draft = await extractor.extract(PreparedDocument(text_parts=[TextPart("血常规")]))

    assert captured["model"] == "vision-model"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert draft.document.type == "检验报告"


@pytest.mark.asyncio
async def test_missing_key_is_non_retryable():
    settings = Settings(model_api_key="", model_name="vision-model")

    with pytest.raises(ExtractionError, match="解析服务未配置") as caught:
        await OpenAICompatibleExtractor(settings).extract(PreparedDocument())

    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_rate_limit_is_retryable():
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={"error": {"message": "rate limited"}}))
    settings = Settings(model_api_key="secret", model_name="vision-model")

    with pytest.raises(ExtractionError) as caught:
        await OpenAICompatibleExtractor(settings, transport=transport).extract(PreparedDocument())

    assert caught.value.retryable is True
    assert caught.value.code == "model_rate_limited"


@pytest.mark.asyncio
async def test_model_disconnect_is_retryable():
    def disconnect(_request):
        raise httpx.RemoteProtocolError('server disconnected')

    settings = Settings(model_api_key="secret", model_name="vision-model")
    with pytest.raises(ExtractionError) as caught:
        await OpenAICompatibleExtractor(settings, httpx.MockTransport(disconnect)).extract(PreparedDocument())
    assert caught.value.retryable is True
    assert caught.value.code == "model_unavailable"


@pytest.mark.asyncio
async def test_single_document_switches_to_backup_on_rate_limit():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append((request.url.host, request.headers['authorization'], payload['model']))
        if request.url.host == 'primary.test':
            return httpx.Response(429, json={'error': {'message': 'rate limited'}})
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(VALID_DRAFT)}}]})

    settings = Settings(model_base_url='https://primary.test/v1', model_api_key='primary-key',
                        model_name='primary-vision', model_fallback_base_url='https://backup.test/v1',
                        model_fallback_api_key='backup-key', model_fallback_name='backup-vision')
    extractor = OpenAICompatibleExtractor(settings, httpx.MockTransport(handler))
    draft = await extractor.extract(PreparedDocument())

    assert draft.document.title == '血常规'
    assert extractor.last_model_name == 'backup-vision'
    assert calls == [
        ('primary.test', 'Bearer primary-key', 'primary-vision'),
        ('backup.test', 'Bearer backup-key', 'backup-vision'),
    ]


@pytest.mark.asyncio
async def test_second_backup_switches_format_and_key_after_two_503s():
    calls=[]
    def handler(request):
        payload=json.loads(request.content)
        calls.append((request.headers['authorization'], payload))
        if len(calls)<3:return httpx.Response(503, json={'error':{'message':'unavailable'}})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(VALID_DRAFT)}}]})
    cfg=Settings(_env_file=None,model_base_url='https://same.test/v1',model_api_key='primary',model_name='vision',
        model_fallback_base_url='https://same.test/v1',model_fallback_api_key='first',model_fallback_name='vision',
        model_fallback2_base_url='https://deep.test',model_fallback2_api_key='second',model_fallback2_name='deepseek-flash',
        model_fallback2_strict_json_schema=False)
    extractor=OpenAICompatibleExtractor(cfg,httpx.MockTransport(handler))
    result=await extractor.extract(PreparedDocument())
    assert result.document.title=='血常规'
    assert [key for key,_ in calls]==['Bearer primary','Bearer first','Bearer second']
    assert [body['response_format']['type'] for _,body in calls]==['json_schema','json_schema','json_object']
    assert 'JSON Schema:' in calls[2][1]['messages'][0]['content']
    assert 'JSON Schema:' not in calls[0][1]['messages'][0]['content']
    assert extractor.last_model_name=='deepseek-flash'


def test_second_backup_is_independent_of_first_and_requires_complete_config():
    from app.services.extraction import model_endpoints
    cfg=Settings(_env_file=None,model_fallback2_base_url='https://deep.test',model_fallback2_api_key='second',model_fallback2_name='deepseek-flash')
    assert len(model_endpoints(cfg))==2
    cfg.model_fallback2_api_key=''
    assert len(model_endpoints(cfg))==1


def test_json_object_mode_keeps_the_first_backup_enabled():
    from app.services.extraction import model_endpoints
    cfg=Settings(_env_file=None,model_strict_json_schema=False,model_fallback_base_url='https://backup.test',model_fallback_api_key='backup',model_fallback_name='vision')
    endpoints=model_endpoints(cfg)
    assert len(endpoints)==2
    assert all(not endpoint.strict_json_schema for endpoint in endpoints)
