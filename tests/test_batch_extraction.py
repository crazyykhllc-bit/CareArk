import json
import re

import httpx
import pytest

from app.config import Settings
from app.services.batch_extraction import BatchExtractor
from app.services.extraction import ExtractionError


@pytest.mark.asyncio
async def test_single_image_source_is_bound_by_request_not_model_generated_id():
    def handler(request):
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'sources':[{'source_id':'invented-or-mistyped-id','content':'完整表格原文','review_items':['字迹模糊']} ]})}}]})
    extractor=BatchExtractor(Settings(_env_file=None,model_api_key='test',model_name='test'),httpx.MockTransport(handler))
    result=await extractor._transcribe_once([{'id':'36e00e1d-fa19-4e0f-9e26-29a8c37b232e','kind':'image','label':'单页','data':b'fake'}])
    assert result.sources[0].source_id=='36e00e1d-fa19-4e0f-9e26-29a8c37b232e'
    assert result.sources[0].content=='完整表格原文'
    assert result.sources[0].review_items==['字迹模糊']


@pytest.mark.asyncio
@pytest.mark.parametrize('input_ids,output_ids',[
    (['s0','s1'],['s0','wrong']),
    (['s0','s1'],['s0','s0']),
    (['s0','s1'],['s0']),
    (['s0'],[]),
    (['s0'],['s0','s0']),
])
async def test_ambiguous_transcription_sources_are_rejected_at_page_stage(input_ids,output_ids):
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'sources':[{'source_id':sid,'content':'原文'} for sid in output_ids]})}}]}))
    extractor=BatchExtractor(Settings(_env_file=None,model_api_key='test',model_name='test'),transport)
    with pytest.raises(ExtractionError,match='单页识别') as error:
        await extractor._transcribe_once([{'id':sid,'kind':'image','label':'图片','data':b'fake'} for sid in input_ids])
    assert error.value.code=='invalid_transcription_sources'
    assert error.value.retryable


@pytest.mark.asyncio
async def test_joint_request_labels_sources_and_includes_schema_for_json_mode():
    captured = []
    def handler(request):
        payload = json.loads(request.content)
        captured.append(payload)
        has_image = any(x['type'] == 'image_url' for x in payload['messages'][1]['content'])
        content = ({'sources': [{'source_id': 's1', 'content': '可见文字'}]} if has_image else {
            'groups': [], 'excluded_sources': [{'source_id': 's1', 'reason': '测试'}], 'reviewed': True,
        })
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            **content})}}]})
    extractor = BatchExtractor(Settings(model_api_key='test-key', model_name='test-vision', model_strict_json_schema=False), httpx.MockTransport(handler))
    result = await extractor.extract_batch([{
        'id': 's1', 'label': '第一页', 'kind': 'image', 'data': b'fake', 'mime_type': 'image/jpeg'
    }], {'groups': []})
    assert result.reviewed is False
    assert len(captured) == 2
    assert 'JSON Schema' in captured[0]['messages'][0]['content']
    assert any('s1' in x.get('text', '') for x in captured[0]['messages'][1]['content'])
    images = [x for x in captured[0]['messages'][1]['content'] if x['type'] == 'image_url']
    assert len(images) == 1
    assert images[0]['image_url']['url'].startswith('data:image/jpeg;base64,')


@pytest.mark.asyncio
async def test_large_batch_is_extracted_in_chunks_then_consolidated():
    captured = []

    def handler(request):
        payload = json.loads(request.content)
        captured.append(payload)
        user_text = '\n'.join(
            item.get('text', '') for item in payload['messages'][1]['content']
        )
        if '分段识别结果：' in user_text:
            ids = re.findall(r'"id": "(s\d+)"', user_text.split('分段识别结果：', 1)[0])
            result = {
                'groups': [],
                'excluded_sources': [{'source_id': source_id, 'reason': '测试'} for source_id in ids],
                'reviewed': False,
            }
        else:
            ids = re.findall(r'来源 ID: (s\d+)', user_text)
            result = {'sources': [{'source_id': source_id, 'content': '可见文字'} for source_id in ids]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]})

    settings = Settings(
        model_api_key='test-key', model_name='test-vision',
        model_strict_json_schema=False, model_max_sources_per_request=2,
    )
    sources = [
        {'id': f's{i}', 'label': f'第{i}页', 'kind': 'image', 'data': b'fake', 'mime_type': 'image/jpeg'}
        for i in range(5)
    ]
    result = await BatchExtractor(settings, httpx.MockTransport(handler)).extract_batch(sources, {'groups': []})

    assert len(captured) == 4
    assert [len([x for x in call['messages'][1]['content'] if x['type'] == 'image_url']) for call in captured] == [2, 2, 1, 0]
    assert [call['max_tokens'] for call in captured] == [4000, 4000, 4000, 16000]
    assert {item.source_id for item in result.excluded_sources} == {f's{i}' for i in range(5)}


@pytest.mark.asyncio
async def test_truncated_output_and_request_capacity_are_explicit_failures():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}))
    extractor = BatchExtractor(Settings(model_api_key='test-key', model_name='test-vision'), transport)
    with pytest.raises(ExtractionError, match='截断'):
        await extractor.extract_batch([], {})
    extractor.settings.model_max_request_bytes = 1024
    with pytest.raises(ExtractionError, match='容量'):
        await extractor.extract_batch([{'id': 's1', 'kind': 'text', 'label': '文档', 'text': 'x' * 10000}], {})


@pytest.mark.asyncio
async def test_insufficient_balance_is_actionable_without_exposing_provider_message():
    transport = httpx.MockTransport(lambda request: httpx.Response(403, json={
        'code': 'INSUFFICIENT_BALANCE', 'message': 'secret-provider-information'}))
    extractor = BatchExtractor(Settings(model_api_key='test-key', model_name='test-vision'), transport)
    with pytest.raises(ExtractionError, match='余额不足') as caught:
        await extractor.extract_batch([], {})
    assert not caught.value.retryable
    assert 'secret' not in str(caught.value)


@pytest.mark.asyncio
async def test_upstream_disconnect_is_retryable_model_failure():
    def disconnect(_request):
        raise httpx.RemoteProtocolError('server disconnected')

    extractor = BatchExtractor(
        Settings(model_api_key='test-key', model_name='test-vision'),
        httpx.MockTransport(disconnect),
    )
    with pytest.raises(ExtractionError, match='连接超时或不可用') as caught:
        await extractor.extract_batch([], {})
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_transient_chunk_failure_retries_only_that_model_request(monkeypatch):
    calls = 0

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr('app.services.batch_extraction.asyncio.sleep', no_wait)

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={'error': {'code': 'temporarily_unavailable'}})
        payload = json.loads(request.content)
        has_image = any(x['type'] == 'image_url' for x in payload['messages'][1]['content'])
        result = ({'sources': [{'source_id': 's1', 'content': '可见文字'}]} if has_image else {
            'groups': [], 'excluded_sources': [{'source_id': 's1', 'reason': '测试'}], 'reviewed': False,
        })
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            **result,
        })}}]})

    settings = Settings(model_api_key='test-key', model_name='test-vision', model_max_retries=2)
    result = await BatchExtractor(settings, httpx.MockTransport(handler)).extract_batch(
        [{'id': 's1', 'label': '第一页', 'kind': 'image', 'data': b'fake'}], {}
    )

    assert calls == 3
    assert result.excluded_sources[0].source_id == 's1'


@pytest.mark.asyncio
async def test_streamed_json_chunks_are_reassembled():
    events = [
        {'choices': [{'delta': {'content': '{"groups":[],'}, 'finish_reason': None}]},
        {'choices': []},
        {'choices': [{'delta': {'content': '"excluded_sources":[],"reviewed":false}'}, 'finish_reason': 'stop'}]},
    ]
    body = ''.join(f"data: {json.dumps(event)}\n\n" for event in events) + 'data: [DONE]\n\n'
    transport = httpx.MockTransport(lambda _request: httpx.Response(
        200, headers={'content-type': 'text/event-stream'}, content=body,
    ))

    result = await BatchExtractor(
        Settings(model_api_key='test-key', model_name='test-vision'), transport,
    ).extract_batch([], {})

    assert result.groups == []


@pytest.mark.asyncio
async def test_rate_limited_primary_uses_backup_for_batch_requests():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append((request.url.host, request.headers['authorization'], payload['model']))
        if request.url.host == 'primary.test':
            return httpx.Response(429, json={'error': {'message': 'rate limited'}})
        has_image = any(item['type'] == 'image_url' for item in payload['messages'][1]['content'])
        result = ({'sources': [{'source_id': 's1', 'content': '可见文字'}]} if has_image else {
            'groups': [], 'excluded_sources': [{'source_id': 's1', 'reason': '测试'}], 'reviewed': False,
        })
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(result)}}]})

    settings = Settings(model_base_url='https://primary.test/v1', model_api_key='primary-key',
                        model_name='primary-vision', model_fallback_base_url='https://backup.test/v1',
                        model_fallback_api_key='backup-key', model_fallback_name='backup-vision')
    result = await BatchExtractor(settings, httpx.MockTransport(handler)).extract_batch(
        [{'id': 's1', 'label': '报告', 'kind': 'image', 'data': b'fake'}], {})

    assert result.excluded_sources[0].source_id == 's1'
    assert calls == [
        ('primary.test', 'Bearer primary-key', 'primary-vision'),
        ('backup.test', 'Bearer backup-key', 'backup-vision'),
        ('primary.test', 'Bearer primary-key', 'primary-vision'),
        ('backup.test', 'Bearer backup-key', 'backup-vision'),
    ]


@pytest.mark.asyncio
async def test_bad_primary_request_does_not_switch_to_backup():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(400, json={'error': {'message': 'bad schema'}})

    settings = Settings(model_base_url='https://primary.test/v1', model_api_key='primary-key',
                        model_name='primary-vision', model_fallback_base_url='https://backup.test/v1',
                        model_fallback_api_key='backup-key', model_fallback_name='backup-vision')
    with pytest.raises(ExtractionError, match='HTTP 400'):
        await BatchExtractor(settings, httpx.MockTransport(handler)).extract_batch([], {})
    assert calls == ['primary.test']


@pytest.mark.asyncio
async def test_second_backup_handles_images_and_merge_with_its_own_json_format():
    calls=[]
    def handler(request):
        body=json.loads(request.content);key=request.headers['authorization'];calls.append((key,body))
        if key!='Bearer second':return httpx.Response(503,json={'error':{'message':'unavailable'}})
        assert body['response_format']=={'type':'json_object'}
        assert body['messages'][0]['content'].count('JSON Schema:')==1
        has_image=any(x['type']=='image_url' for x in body['messages'][1]['content'])
        result=({'sources':[{'source_id':'s1','content':'合成文字'}]} if has_image else {'groups':[], 'excluded_sources':[{'source_id':'s1','reason':'测试'}], 'reviewed':False})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(result)},'finish_reason':'stop'}]})
    cfg=Settings(_env_file=None,model_base_url='https://same.test/v1',model_api_key='primary',model_name='vision',
        model_fallback_base_url='https://same.test/v1',model_fallback_api_key='first',model_fallback_name='vision',
        model_fallback2_base_url='https://deep.test',model_fallback2_api_key='second',model_fallback2_name='deepseek-flash',
        model_fallback2_strict_json_schema=False,model_max_retries=0)
    result=await BatchExtractor(cfg,httpx.MockTransport(handler)).extract_batch([{'id':'s1','label':'合成图片','kind':'image','data':b'fake'}],{})
    assert result.excluded_sources[0].source_id=='s1'
    assert [key for key,_ in calls]==['Bearer primary','Bearer first','Bearer second']*2
    assert all(body['response_format']['type']=='json_schema' for key,body in calls if key!='Bearer second')
    assert all('JSON Schema:' not in body['messages'][0]['content'] for key,body in calls if key!='Bearer second')


@pytest.mark.asyncio
async def test_truncated_chunk_retries_same_endpoint_with_merge_budget_only_once():
    from app.batch_schemas import SourceTranscriptionBatch
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append((request.url.host,body['max_tokens']))
        result={'sources':[{'source_id':'s1','content':'完整合成文字'}]}
        return httpx.Response(200,json={'choices':[{'finish_reason':'length' if len(calls)==1 else 'stop','message':{'content':json.dumps(result)}}]})
    cfg=Settings(_env_file=None,model_api_key='test-key',model_name='vision',model_base_url='https://primary.test/v1',model_max_output_tokens=16000)
    result=await BatchExtractor(cfg,httpx.MockTransport(handler))._request([{'type':'text','text':'合成资料'}],'JSON',result_model=SourceTranscriptionBatch,schema_name='source_transcription',max_output_tokens=4000)
    assert result.sources[0].content=='完整合成文字'
    assert calls==[('primary.test',4000),('primary.test',16000)]


@pytest.mark.asyncio
async def test_chunk_expansion_still_rejects_truncated_content():
    from app.batch_schemas import SourceTranscriptionBatch
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content)['max_tokens'])
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})
    cfg=Settings(_env_file=None,model_api_key='test-key',model_name='vision',model_max_output_tokens=16000)
    with pytest.raises(ExtractionError,match='截断'):
        await BatchExtractor(cfg,httpx.MockTransport(handler))._request([], 'JSON', result_model=SourceTranscriptionBatch,schema_name='source_transcription',max_output_tokens=4000)
    assert calls==[4000,16000]


@pytest.mark.asyncio
async def test_official_deepseek_disables_thinking_without_sending_parameter_to_primary():
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append((request.url.host,body))
        if request.url.host=='primary.test':return httpx.Response(503,json={})
        assert body['thinking']=={'type':'disabled'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"groups":[],"excluded_sources":[],"reviewed":false}'}}]})
    cfg=Settings(_env_file=None,model_api_key='primary',model_name='vision',model_base_url='https://primary.test/v1',model_fallback2_base_url='https://api.deepseek.com',model_fallback2_api_key='second',model_fallback2_name='deepseek-flash')
    await BatchExtractor(cfg,httpx.MockTransport(handler))._request([], 'JSON')
    assert 'thinking' not in calls[0][1]


@pytest.mark.asyncio
async def test_truncation_on_second_backup_does_not_restart_unavailable_primary_chain():
    from app.batch_schemas import SourceTranscriptionBatch
    calls=[]
    def handler(request):
        body=json.loads(request.content);key=request.headers['authorization'];calls.append((key,body['max_tokens']))
        if key!='Bearer second':return httpx.Response(503,json={})
        finish='length' if len(calls)==3 else 'stop'
        return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':'{"sources":[]}'}}]})
    cfg=Settings(_env_file=None,model_api_key='primary',model_name='vision',model_base_url='https://primary.test/v1',
        model_fallback_base_url='https://first.test/v1',model_fallback_api_key='first',model_fallback_name='vision',
        model_fallback2_base_url='https://api.deepseek.com',model_fallback2_api_key='second',model_fallback2_name='deepseek-flash',model_max_output_tokens=16000)
    await BatchExtractor(cfg,httpx.MockTransport(handler))._request([], 'JSON',result_model=SourceTranscriptionBatch,schema_name='source_transcription',max_output_tokens=4000)
    assert calls==[('Bearer primary',4000),('Bearer first',4000),('Bearer second',4000),('Bearer second',16000)]
