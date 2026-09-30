import json
import httpx
import pytest
from app.config import Settings
from app.services.batch_extraction import BatchExtractor
from app.services.extraction import ExtractionError


def sources(count=20):
    return [{'id':f's{i}','kind':'text','label':f'合成单据{i}','text':f'完整合成原文{i}'} for i in range(count)]


def mock_handler(calls, *, missing=False, manual=False, truncate_first=False):
    def handler(request):
        body=json.loads(request.content)
        name=body['response_format']['json_schema']['name']
        calls.append((name,body))
        text=body['messages'][1]['content'][0]['text']
        if name=='batch_extraction' and truncate_first:
            return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})
        if name=='batch_merge_plan':
            ids=[row['id'] for row in json.loads(text.split('全部真实来源 ID：',1)[1].split('\n',1)[0])]
            if missing:ids=ids[:-1]
            groups=[{'id':f'g{i}','kind':'document','source_ids':[sid],'encounter_id':None} for i,sid in enumerate(ids)]
            if manual:
                chosen=['s0','s9','s19']
                groups=[g for g in groups if g['source_ids'][0] not in chosen]+[{'id':'drug','kind':'medication','source_ids':chosen,'encounter_id':None}]
            result={'groups':groups,'encounters':[],'excluded_sources':[],'review_items':[]}
        elif name=='group_extraction':
            plan=json.loads(text.split('当前资料组：',1)[1].split('\n',1)[0])
            result={'id':'model-reused-id','kind':plan['kind'],'source_ids':plan['source_ids'],'encounter_id':None,'document':{'type':'其他医疗资料','title':'合成记录','parsed_content':None},'medications':[{'name':'合成药品'}] if plan['kind']=='medication' else []}
        else:raise AssertionError(name)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
    return handler


def cfg():return Settings(_env_file=None,model_api_key='test',model_name='vision',model_strict_json_schema=True,model_batch_concurrency=2)


@pytest.mark.asyncio
async def test_twenty_files_use_global_plan_then_per_group_details_without_giant_json():
    calls=[]
    result=await BatchExtractor(cfg(),httpx.MockTransport(mock_handler(calls))).extract_batch(sources(),{})
    assert [name for name,_ in calls].count('batch_merge_plan')==1
    assert [name for name,_ in calls].count('group_extraction')==20
    assert not any(name=='batch_extraction' for name,_ in calls)
    assert len(result.groups)==20
    assert len({g.id for g in result.groups})==20
    assert {sid for g in result.groups for sid in g.source_ids}=={f's{i}' for i in range(20)}
    assert all('完整合成原文' in g.document.parsed_content for g in result.groups)
    assert result.reviewed is False


@pytest.mark.asyncio
async def test_manual_drug_group_across_the_batch_is_never_split():
    calls=[]
    grouping={'groups':[{'id':'manual','kind':'medication','source_ids':['s0','s9','s19']}],'encounters':[]}
    result=await BatchExtractor(cfg(),httpx.MockTransport(mock_handler(calls,manual=True))).extract_batch(sources(),grouping)
    drug=[g for g in result.groups if g.kind=='medication']
    assert len(drug)==1
    assert set(drug[0].source_ids)=={'s0','s9','s19'}
    assert all(f'完整合成原文{i}' in drug[0].document.parsed_content for i in [0,9,19])


@pytest.mark.asyncio
async def test_plan_missing_a_source_fails_before_details_are_requested():
    calls=[]
    with pytest.raises(ExtractionError,match='分组规划'):
        await BatchExtractor(cfg(),httpx.MockTransport(mock_handler(calls,missing=True))).extract_batch(sources(),{})
    assert [name for name,_ in calls]==['batch_merge_plan']


@pytest.mark.asyncio
async def test_small_batch_merge_truncation_reuses_transcripts_and_switches_to_plan():
    calls=[]
    result=await BatchExtractor(cfg(),httpx.MockTransport(mock_handler(calls,truncate_first=True))).extract_batch(sources(3),{})
    assert len(result.groups)==3
    assert [name for name,_ in calls]==['batch_extraction','batch_merge_plan','group_extraction','group_extraction','group_extraction']


@pytest.mark.asyncio
async def test_small_batch_invalid_merge_switches_to_bounded_plan():
    calls=[]
    normal=mock_handler(calls)
    def handler(request):
        body=json.loads(request.content)
        if body['response_format']['json_schema']['name']=='batch_extraction':
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"groups":"invalid"}'}}]})
        return normal(request)
    result=await BatchExtractor(cfg(),httpx.MockTransport(handler)).extract_batch(sources(3),{})
    assert {sid for group in result.groups for sid in group.source_ids}=={'s0','s1','s2'}
    assert len(result.groups)==3


@pytest.mark.parametrize('groups,encounters,grouping',[
    ([{'id':'g','kind':'document','source_ids':['s0'],'encounter_id':'unknown'}],[],{}),
    ([{'id':'g','kind':'document','source_ids':['outsider']}],[],{}),
    ([{'id':'g','kind':'document','source_ids':['s0']}],[],{'encounters':[{'source_ids':['s0']}]}),
    ([{'id':'g','kind':'document','source_ids':['s0']},{'id':'g','kind':'document','source_ids':['s0']}],[],{}),
])
def test_invalid_relationships_cannot_proceed(groups,encounters,grouping):
    from app.batch_schemas import BatchMergePlan
    from app.services.batch_merge import validate_plan
    with pytest.raises(ExtractionError):
        validate_plan(BatchMergePlan(groups=groups,encounters=encounters),{'s0'},grouping)


@pytest.mark.asyncio
async def test_detail_truncation_preserves_source_for_manual_review():
    calls=[]
    normal=mock_handler(calls)
    def handler(request):
        body=json.loads(request.content)
        if body['response_format']['json_schema']['name']=='group_extraction':
            return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})
        return normal(request)
    result=await BatchExtractor(cfg(),httpx.MockTransport(handler)).extract_batch(sources(6),{})
    assert len(result.groups)==6
    assert {sid for group in result.groups for sid in group.source_ids}=={f's{i}' for i in range(6)}
    assert all('自动提取失败' in ' '.join(group.review_items) for group in result.groups)
    assert all('完整合成原文' in group.document.parsed_content for group in result.groups)
    assert all(group.lab_results==[] and group.medications==[] for group in result.groups)


@pytest.mark.asyncio
async def test_one_malformed_detail_does_not_discard_other_extracted_groups():
    calls=[]
    normal=mock_handler(calls)
    def handler(request):
        body=json.loads(request.content)
        if body['response_format']['json_schema']['name']=='group_extraction':
            text=body['messages'][1]['content'][0]['text']
            if '"source_ids": ["s1"]' in text:
                return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]})
        return normal(request)
    result=await BatchExtractor(cfg(),httpx.MockTransport(handler)).extract_batch(sources(6),{})
    failed=next(group for group in result.groups if group.source_ids==['s1'])
    successful=[group for group in result.groups if group.source_ids!=['s1']]
    assert failed.document.type=='其他医疗资料'
    assert '完整合成原文1' in failed.document.parsed_content
    assert any('自动提取失败' in notice for notice in failed.review_items)
    assert len(successful)==5
    assert all(group.document.title=='合成记录' for group in successful)
    assert all(not any('自动提取失败' in notice for notice in group.review_items) for group in successful)
    assert any('1 份资料' in notice for notice in result.review_items)


@pytest.mark.asyncio
async def test_failed_medication_detail_stays_editable_as_one_unknown_medication():
    calls=[]
    normal=mock_handler(calls,manual=True)
    def handler(request):
        body=json.loads(request.content)
        if body['response_format']['json_schema']['name']=='group_extraction':
            plan=json.loads(body['messages'][1]['content'][0]['text'].split('当前资料组：',1)[1].split('\n',1)[0])
            if plan['kind']=='medication':
                return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"id":1}'}}]})
        return normal(request)
    grouping={'groups':[{'id':'manual','kind':'medication','source_ids':['s0','s9','s19']}],'encounters':[]}
    result=await BatchExtractor(cfg(),httpx.MockTransport(handler)).extract_batch(sources(),grouping)
    drug=next(group for group in result.groups if group.kind=='medication')
    assert drug.source_ids==['s0','s9','s19']
    assert [item.name for item in drug.medications]==['待核对药品']
    assert '完整合成原文19' in drug.document.parsed_content
    assert any('自动提取失败' in notice for notice in drug.review_items)


def test_assembly_retains_global_visit_and_field_evidence():
    from app.batch_schemas import BatchMergePlan, GroupDetailExtraction, SourceTranscription
    from app.services.batch_merge import assemble_result
    plan=BatchMergePlan(groups=[{'id':'g','kind':'document','source_ids':['s0'],'encounter_id':'v'}],encounters=[{'id':'v','title':'合成就诊'}])
    detail=GroupDetailExtraction(id='different',kind='document',source_ids=['s0'],document={'type':'检验报告','title':'合成报告'},evidence=[{'source_id':'s0','field':'document.title','quote':'合成报告'}])
    result=assemble_result(plan,[detail],{'s0':SourceTranscription(source_id='s0',content='合成报告完整原文',review_items=['需核对'])},{'s0':'第一页'},{'s0'})
    assert result.groups[0].encounter_id==result.encounters[0].id=='v'
    assert result.groups[0].evidence[0].quote=='合成报告'
    assert '合成报告完整原文' in result.groups[0].document.parsed_content
    assert result.groups[0].review_items==['需核对']
