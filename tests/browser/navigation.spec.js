const {test,expect}=require('@playwright/test');
const path=require('path');const fs=require('fs');
const uuid=index=>`00000000-0000-4000-8000-${String(index).padStart(12,'0')}`;
function doc(index){return{id:uuid(index),document_type:'检验报告',title:`合成资料 ${index}`,primary_date:`2026-09-${String(1+index%9).padStart(2,'0')}`,primary_date_raw:'报告日期',hospital:'合成医院',department:'检验科',doctor:null,amount:null,key_information:[`合成结果 ${index}`],parsed_content:null,encounter_id:index<=24?uuid(100+Math.ceil(index/2)):null,version:1,patient_scope:'self',type_specific_data:{}}}
function visit(index){return{id:uuid(100+index),title:`合成诊疗 ${index}`,hospital:index===12?'另一医院':'合成医院',department:'检验科',date:index>10?'2025-12-12':`2026-09-${String(index).padStart(2,'0')}`,date_basis:'report',date_basis_label:'报告日期',event_kind:'laboratory',event_kind_label:'检验',document_count:2,document_types:{检验报告:2},facts:[{text:`来源摘录 ${index}`,origin:'source',source_refs:[{document_id:uuid(index*2-1)}]}],topic_ids:[],version:1}}
test.beforeEach(async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));page.__errors=errors;
  const docs=Array.from({length:35},(_,index)=>doc(index+1));
  const events=Array.from({length:12},(_,index)=>visit(index+1));
  await page.route('https://archive.test/**',async route=>{
    const url=new URL(route.request().url()),p=url.pathname;
    if(p.startsWith('/api/')){
      const hospital=url.searchParams.get('hospital');const visible=events.filter(item=>!hospital||item.hospital===hospital);
      let data=p==='/api/system/status'?{model:{configured:true}}:
        p==='/api/auth/me'?{id:'u1',email:'tester@example.test',role:'admin'}:
        p==='/api/overview'?{documents:{total:35,dated:35,undated:0},hospitals:2,latest_date:'2026-09-09',types:[],months:[]}:
        p==='/api/costs/summary'?{receipts:{total:0},totals_by_currency:[],years:[],undated:{known_count:0,unknown_count:0},excluded_count:0}:
        p==='/api/metrics'||p==='/api/metric-entries'||p==='/api/drafts'||p==='/api/medications'||p==='/api/batches'||p==='/api/care-topics'?{items:[]}:
        p==='/api/encounters'?{items:[]}:
        p==='/api/documents'?{items:docs,next_cursor:null}:
        p==='/api/care-hierarchy'?{summary:{event_count:visible.length,hospital_count:new Set(visible.map(item=>item.hospital)).size,latest_date:'2026-09-10',pending_count:0},items:url.searchParams.has('month')?visible.slice(10):visible.slice(0,10),older_months:visible.length>10?[{month:'2025-12',count:visible.length-10}]:[],hospitals:[...new Set(events.map(item=>item.hospital))]}:
        p==='/api/care-hierarchy/search'?{items:docs.filter(d=>!d.encounter_id),total:11,next_offset:null}:
        p==='/api/care-history'?{summary:{event_count:visible.length,hospital_count:new Set(visible.map(item=>item.hospital)).size,latest_date:'2026-09-10',undated_count:0,pending_count:0},recent:visible.slice(0,10),older_months:visible.length>10?[{month:'2025-12',count:visible.length-10}]:[],hospitals:[...new Set(events.map(item=>item.hospital))]}:
        p==='/api/care-history/events'?{items:visible.slice(10),total:visible.length-10,next_offset:null}:{items:[]};
      const docId=p.match(/^\/api\/documents\/([0-9a-f-]+)$/)?.[1];
      if(docId){const item=docs.find(value=>value.id===docId);data={...item,lab_results:[],attachments:[],extraction_metadata:{},receipt:null}}
      const eventId=p.match(/^\/api\/care-history\/events\/([0-9a-f-]+)$/)?.[1];
      if(eventId){const item=events.find(value=>value.id===eventId);data={...item,documents:docs.filter(value=>value.encounter_id===eventId),related_documents:[],milestones:[],user_note:null,date_sources:[],document_date_range:null}}
      return route.fulfill({json:data});
    }
    const file=path.join(__dirname,'../../app/web',p==='/'?'index.html':path.basename(p));
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
});
test.afterEach(async({page})=>expect(page.__errors).toEqual([]));

test('care timeline groups reports into events and keeps the expanded month after visiting a source',async({page})=>{
  await page.goto('https://archive.test/#home');
  await expect(page.locator('#careTimeline .care-event')).toHaveCount(10);
  await expect(page.locator('#careEventCount')).toHaveText('12');
  await page.locator('[data-care-month="2025-12"]').click();
  await expect(page.locator('#careMonths .care-event')).toHaveCount(2);
  await page.locator('#careMonths [data-care-event]').first().click();
  await expect(page.locator('#careDetailPanel')).toBeVisible();
  await expect(page.locator('#careDetailPanel')).toContainText('来源资料');
  await page.locator('#careDetailPanel [data-document]').first().click();
  await expect(page.locator('#view-detail')).toBeVisible();
  await page.locator('#detailBack').click();
  await expect(page.locator('#careDetailPanel')).toBeVisible();
  await page.locator('#careDetailPanel [data-care-back]').click();
  await expect(page.locator('#careMonths .care-event')).toHaveCount(2);
});

test('raw archive still shows ten recent documents and folds older months',async({page})=>{
  await page.goto('https://archive.test/#home');
  await page.locator('[data-view="archive"]').first().click();
  await expect(page.locator('#archiveList .archive-recent [data-document]')).toHaveCount(10);
  const month=page.locator('#archiveList .archive-month');
  await expect(month).toHaveCount(1);
  await expect(month.locator('summary')).toContainText('25 份资料');
  await month.locator('summary').click();
  await expect(month.locator('[data-document]').first()).toBeVisible();
  await page.locator('#archiveSearch').fill('合成资料 35');
  await expect(page.locator('#archiveList [data-document]')).toHaveCount(1);
  await page.locator('[data-view="home"]').first().click();
  await expect(page.locator('#careTimeline .care-event')).toHaveCount(10);
});

test('care timeline filters by the actual event hospital',async({page})=>{
  await page.goto('https://archive.test/#home');
  await expect(page.locator('#careEventCount')).toHaveText('12');
  await page.locator('#careHospital').selectOption('另一医院');
  await expect(page.locator('#careEventCount')).toHaveText('1');
  await expect(page.locator('#careTimeline .care-event')).toHaveCount(1);
  await expect(page.locator('#careTimeline')).toContainText('合成诊疗 12');
});

test('returning from a topic event restores the topic and then its list',async({page})=>{
  const topicId=uuid(900),event=visit(1),undated={...visit(2),date:null};
  await page.route('https://archive.test/api/care-topics**',async route=>{
    const pathname=new URL(route.request().url()).pathname;
    const topic={id:topicId,name:'合成主题',note:null,status:'active',event_count:2,hospital_count:1,
      latest_date:event.date,version:1,events:[event,undated]};
    await route.fulfill({json:pathname.includes(topicId)?{...topic,documents:[],metric_summaries:[],costs_by_currency:[]}: {items:[topic]}});
  });
  await page.route('https://archive.test/api/care-hierarchy?*',route=>route.fulfill({json:{items:[{id:topicId,name:'合成主题',item_type:'topic',event_count:2,document_count:2,hospital_count:1,date:event.date}],summary:{event_count:1,hospital_count:1,latest_date:event.date,pending_count:0},hospitals:['合成医院'],older_months:[]}}));
  await page.goto('https://archive.test/#home');
  await page.locator('#careTopicsTab').click();
  await page.locator(`[data-care-topic="${topicId}"]`).click();
  await page.locator(`#careDetailPanel [data-care-event="${event.id}"]`).click();
  await expect(page.locator('#careDetailPanel')).toContainText('合成诊疗 1');
  await page.locator('#careDetailPanel [data-care-back]').click();
  await expect(page.locator('#careDetailPanel')).toContainText('合成主题');
  await expect(page.locator('#careDetailPanel')).toContainText('日期待核对 · 1 次诊疗');
  await expect(page.locator(`#careDetailPanel [data-care-event="${event.id}"]`)).toBeFocused();
  await page.locator('#careDetailPanel [data-care-back]').click();
  await expect(page.locator('#careTimelinePanel')).toBeVisible();
  await expect(page.locator('#careTimeline')).toContainText('合成主题');
  await expect(page.locator(`[data-care-topic="${topicId}"]`)).toBeFocused();
});

test('editing a title leaves unchanged source date out of the update',async({page})=>{
  const eventId=uuid(101);let update;
  await page.route(`https://archive.test/api/care-history/events/${eventId}`,async route=>{
    if(route.request().method()!=='PATCH')return route.fallback();
    update=route.request().postDataJSON();
    await route.fulfill({json:{id:eventId}});
  });
  await page.goto('https://archive.test/#home');
  await page.locator(`#careTimeline [data-care-event="${eventId}"]`).click();
  await page.locator('[data-care-edit-event]').click();
  await page.locator('#careEdit_title').fill('合成诊疗已更名');
  await page.locator('#careEditForm button[type="submit"]').click();
  await expect.poll(()=>update).toEqual({title:'合成诊疗已更名',expected_version:1});
});

test('legacy suggestion shows its source and submits reviewed title and date',async({page})=>{
  const suggestionId=uuid(800),documentId=uuid(25);let accepted;
  await page.route('https://archive.test/api/care-hierarchy?*',async route=>route.fulfill({json:{
    summary:{event_count:0,hospital_count:0,latest_date:null,undated_count:0,pending_count:1},
    recent:[],older_months:[],hospitals:[]}}));
  await page.route('https://archive.test/api/care-suggestions**',async route=>{
    if(route.request().method()==='POST'){
      accepted=route.request().postDataJSON();return route.fulfill({json:{id:suggestionId,status:'accepted'}});
    }
    return route.fulfill({json:{items:accepted?[]:[{id:suggestionId,kind:'document_event',version:1,
      payload:{document_id:documentId,title:'原建议',date:'2026-03-01',hospital:'合成医院'}}],next_offset:null}});
  });
  await page.goto('https://archive.test/#home');
  await page.locator('#careSuggestionsBtn').click();
  await expect(page.locator(`[data-care-suggestion-card="${suggestionId}"]`)).toContainText('查看来源资料');
  await page.locator(`[data-care-suggestion-title="${suggestionId}"]`).fill('核对后标题');
  await page.locator(`[data-care-suggestion-date="${suggestionId}"]`).fill('2026-03-02');
  await page.locator(`[data-care-suggestion-basis="${suggestionId}"]`).selectOption('examination');
  await page.locator(`[data-care-accept="${suggestionId}"]`).click();
  await expect.poll(()=>accepted).toEqual({expected_version:1,title:'核对后标题',date:'2026-03-02',date_basis:'examination'});
});

test('batch accepting reviewed suggestions keeps a failed item and its edits',async({page})=>{
  const first=uuid(801),second=uuid(802),accepted=[];
  await page.route('https://archive.test/api/care-hierarchy?*',async route=>route.fulfill({json:{
    summary:{event_count:0,hospital_count:0,latest_date:null,undated_count:0,pending_count:2},
    recent:[],older_months:[],hospitals:[]}}));
  await page.route('https://archive.test/api/care-suggestions**',async route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(route.request().method()==='POST'){
      if(pathname.includes(second))return route.fulfill({status:409,json:{detail:'来源已变化'}});
      accepted.push(route.request().postDataJSON());return route.fulfill({json:{id:first,status:'accepted'}});
    }
    return route.fulfill({json:{items:[first,second].filter(id=>id===second||!accepted.length).map(id=>({
      id,kind:'document_event',version:1,payload:{document_id:uuid(id===first?25:26),
        title:`建议 ${id===first?1:2}`,date:'2026-03-01',hospital:'合成医院',date_basis:'report'}})),next_offset:null}});
  });
  await page.goto('https://archive.test/#home');
  await page.locator('#careSuggestionsBtn').click();
  await page.locator(`[data-care-suggestion-title="${second}"]`).fill('保留的修正');
  await page.locator(`[data-care-select-suggestion="${first}"]`).check();
  await page.locator(`[data-care-select-suggestion="${second}"]`).check();
  await page.locator('#careAcceptSelected').click();
  await expect(page.locator(`[data-care-suggestion-card="${first}"]`)).toHaveCount(0);
  await expect(page.locator(`[data-care-suggestion-title="${second}"]`)).toHaveValue('保留的修正');
  await expect(page.locator(`[data-care-suggestion-error="${second}"]`)).toContainText('来源已变化');
  expect(accepted).toHaveLength(1);
});

test('linking source documents proposes a title and blocks an empty title locally',async({page})=>{
  await page.goto('https://archive.test/#home');
  await page.locator('#careAddEvent').click();
  await page.locator('#careEditPick').click();
  await page.locator(`#carePickerResults input[value="${uuid(25)}"]`).check();
  await page.locator('#carePickerConfirm').click();
  await expect(page.locator('#careEdit_title')).toHaveValue('合成资料 25');
  await expect(page.locator('#careEdit_hospital')).toHaveValue('合成医院');
  await page.locator('#careEdit_title').fill('');
  await page.locator('#careEditForm button[type="submit"]').click();
  await expect(page.locator('#careEditError')).toContainText('请填写事件名称');
  await expect(page.locator('#careEditDialog')).toBeVisible();
});
