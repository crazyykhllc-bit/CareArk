const {test,expect}=require('@playwright/test');
const fs=require('fs'),path=require('path');
test.beforeEach(async({page})=>{
  page.__errors=[];page.on('pageerror',e=>page.__errors.push(e.message));
  const event={id:'e1',title:'一次普通门诊',hospital:'合成医院',date:'2026-09-20',date_basis_label:'就诊日期',event_kind_label:'门诊',document_count:1,topic_ids:[],version:1,primary_topic_id:null,item_type:'event',facts:[]};
  const topic={id:'t1',name:'持续诊疗过程',title:'持续诊疗过程',item_type:'topic',date:'2026-08-01',date_end:'2026-09-22',document_count:6,event_count:3,hospital_count:2,status:'active',version:1};
  await page.route('https://hierarchy.test/**',async route=>{
    const req=route.request(),url=new URL(req.url()),p=url.pathname;
    if(p.startsWith('/api/')){
      let data={items:[]};
      if(p==='/api/auth/me')data={id:'u1',email:'tester@example.test',role:'admin'};
      if(p==='/api/system/status')data={model:{configured:true}};
      if(p==='/api/overview')data={documents:{total:7,dated:7},types:[],months:[]};
      if(p==='/api/costs/summary')data={receipts:{total:0},totals_by_currency:[],years:[],undated:{}};
      if(p==='/api/care-topics')data={items:[topic]};
      if(p==='/api/care-hierarchy')data={items:[event,topic],total:2,next_offset:null,older_months:[],hospitals:['合成医院'],summary:{event_count:2,hospital_count:2,latest_date:'2026-09-22',pending_count:0}};
      if(p==='/api/care-history')data={recent:[event],older_months:[],hospitals:['合成医院'],summary:{event_count:1,hospital_count:1,latest_date:event.date,pending_count:0}};
      if(p==='/api/care-history/events/e1')data={...event,documents:[],milestones:[],related_events:[],related_documents:[],date_sources:[]};
      if(p==='/api/care-history/events/e1/upgrade'){page.__upgrade=req.postDataJSON();data={id:'t1',topic_id:'t1',version:2}}
      if(p==='/api/care-topics/t1/overview'||p==='/api/care-topics/t1')data={...topic,events:[{...event,primary_topic_id:'t1'}],documents:[],metric_summaries:[],costs_by_currency:[]};
      if(p==='/api/care-hierarchy/search'){page.__search=url.searchParams.get('query');data={items:[{id:'d101',title:'第101份既有资料',item_type:'document',hospital:'另一医院',encounter_id:'e2',primary_topic_name:'原大事件'}],total:1,next_offset:null}}
      if(p==='/api/care-topics/t1/attach-documents'){page.__attach=req.postDataJSON();data={topic_id:'t1'}}
      return route.fulfill({json:data});
    }
    const f=path.join(__dirname,'../../app/web',p==='/'?'index.html':path.basename(p));return route.fulfill({body:fs.readFileSync(f),contentType:f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':'text/html'});
  });
});
test.afterEach(async({page})=>expect(page.__errors).toEqual([]));
test('one list shows small and big events and upgrades without reupload',async({page})=>{
  await page.goto('https://hierarchy.test/#home');
  await expect(page.locator('#careTimeline')).toContainText('持续诊疗过程');
  await expect(page.locator('#careTimeline')).toContainText('小事件');
  await page.locator('[data-care-event="e1"]').click();
  await page.getByRole('button',{name:'升级为大事件',exact:true}).click();
  await page.locator('#careActionName').fill('普通门诊后续诊疗');
  await page.locator('#careActionConfirm').click();
  await expect.poll(()=>page.__upgrade?.name).toBe('普通门诊后续诊疗');
  expect(page.__upgrade.expected_version).toBe(1);
});

test('hospital choices remain available after filtering and combining with event type',async({page})=>{
  await page.route('https://hierarchy.test/api/care-hierarchy?**',route=>{
    const query=new URL(route.request().url()).searchParams;
    const hospital=query.get('hospital');
    return route.fulfill({json:{
      items:hospital&&hospital!=='甲医院'?[]:[{id:'t-checkup',name:'全面体检',item_type:'topic',
        date:'2026-08-01',event_count:2,hospital_count:2,document_count:3}],
      total:hospital&&hospital!=='甲医院'?0:1,next_offset:null,older_months:[],
      hospitals:[{name:'甲医院',event_count:1},{name:'乙医院',event_count:1}],
      summary:{event_count:hospital&&hospital!=='甲医院'?0:1,hospital_count:2,pending_count:0}}});
  });
  await page.goto('https://hierarchy.test/#home');
  await page.locator('#careHospital').selectOption('甲医院');
  await expect(page.locator('#careHospital')).toHaveValue('甲医院');
  await expect(page.locator('#careHospital option')).toHaveCount(3);
  await page.locator('#careKind').selectOption('checkup');
  await expect(page.locator('#careHospital')).toHaveValue('甲医院');
  await expect(page.locator('#careHospital option')).toHaveCount(3);
  await expect(page.locator('#careTimeline')).toContainText('全面体检');
});
test('big event searches all saved documents independently of archive cache',async({page})=>{
  await page.goto('https://hierarchy.test/#home');
  await page.locator('[data-care-topic="t1"]').first().click();
  await page.getByRole('button',{name:'关联已有资料',exact:true}).click();
  await page.locator('#carePickerSearch').fill('第101份');
  await expect(page.locator('#carePickerResults')).toContainText('第101份既有资料');
  await page.locator('#carePickerResults input').check();
  await page.locator('#carePickerConfirm').click();
  await expect.poll(()=>page.__attach?.document_ids).toEqual(['d101']);
});

test('opening a big event shows progress while its details load',async({page})=>{
  let release;
  await page.route('https://hierarchy.test/api/care-topics/t1/overview',async route=>{
    await new Promise(resolve=>release=resolve);
    await route.fulfill({json:{id:'t1',name:'持续诊疗过程',events:[],documents:[],metric_summaries:[],costs_by_currency:[]}});
  });
  await page.goto('https://hierarchy.test/#home');
  const opening=page.locator('#careTimeline [data-care-topic="t1"]').first().click();
  await expect(page.locator('#careDetailPanel')).toBeVisible();
  await expect(page.locator('#careDetailPanel')).toContainText('正在打开');
  release();
  await opening;
  await expect(page.locator('#careDetailPanel')).toContainText('持续诊疗过程');
});

test('supplement upload inherits the big event target',async({page})=>{
  await page.goto('https://hierarchy.test/#home');
  await page.locator('[data-care-topic="t1"]').first().click();
  await page.getByRole('button',{name:'补充上传',exact:true}).click();
  await expect(page.locator('#uploadCareMode')).toHaveValue('existing_topic');
  await expect(page.locator('#uploadCareSelected')).toContainText('持续诊疗过程');
  await expect(page.locator('#view-upload')).toBeVisible();
});

test('undated history remains accessible and date range uses its start',async({page})=>{
  await page.route('https://hierarchy.test/api/care-hierarchy?**',route=>route.fulfill({json:{
    items:route.request().url().includes('month=undated')?[{id:'e-tail',item_type:'event',title:'历史待核对资料',document_count:1,topic_ids:[]}]:[
      {id:'t1',item_type:'topic',name:'持续诊疗过程',date:'2026-09-22',date_start:'2026-08-01',date_end:'2026-09-22',event_count:3}],
    total:11,next_offset:null,older_months:[],undated_count:1,hospitals:[],summary:{event_count:11,pending_count:0}}}));
  await page.goto('https://hierarchy.test/#home');
  await expect(page.locator('.care-big-event')).toContainText('2026.08.01');
  await page.locator('[data-care-month="undated"]').click();
  await expect(page.locator('#careMonths')).toContainText('历史待核对资料');
});

test('long titles and picker stay within a narrow screen',async({page},testInfo)=>{
  await page.route('https://hierarchy.test/api/care-hierarchy/search?**',route=>route.fulfill({json:{items:[{
    id:'d101',title:'第101份'+ '很长的医院名称与原始资料报告标题'.repeat(6),hospital:'合成医院',item_type:'document'}],total:1,next_offset:null}}));
  await page.setViewportSize({width:390,height:844});
  await page.goto('https://hierarchy.test/#home');
  await page.locator('[data-care-topic="t1"]').first().click();
  await page.getByRole('button',{name:'关联已有资料',exact:true}).click();
  await expect(page.locator('#carePickerResults')).toContainText('第101份');
  const widths=await page.evaluate(()=>({page:document.documentElement.scrollWidth,viewport:innerWidth,
    dialog:document.getElementById('carePickerDialog').getBoundingClientRect().width}));
  expect(widths.page).toBeLessThanOrEqual(widths.viewport);
  expect(widths.dialog).toBeLessThanOrEqual(widths.viewport);
  const checkbox=await page.locator('#carePickerResults input').boundingBox();
  const label=await page.locator('#carePickerResults label').boundingBox();
  expect(checkbox.x-label.x).toBeLessThan(25);
  await page.screenshot({path:testInfo.outputPath('care-picker-mobile.png'),fullPage:true});
});

test('changing picker type clears stale records until the new page arrives',async({page})=>{
  let release;
  await page.route('https://hierarchy.test/api/care-hierarchy/search?**',async route=>{
    if(new URL(route.request().url()).searchParams.get('kind')==='event'){
      await new Promise(resolve=>release=resolve);
      return route.fulfill({json:{items:[{id:'e99',title:'新类型诊疗',item_type:'event'}],total:1,next_offset:null}});
    }
    await route.fallback();
  });
  await page.goto('https://hierarchy.test/#home');
  await expect(page.locator('#careTimeline')).toContainText('持续诊疗过程');
  await page.evaluate(()=>{window.chooseCareRecords({kind:'document',kinds:['document','event'],multiple:false}).then(result=>window.pickerResult=result)});
  await expect(page.locator('#carePickerResults')).toContainText('第101份');
  await page.locator('#carePickerKind').selectOption('event');
  await expect(page.locator('#carePickerResults input')).toHaveCount(0);
  await expect.poll(()=>Boolean(release)).toBe(true);release();
  await expect(page.locator('#carePickerResults')).toContainText('新类型诊疗');
  await page.locator('#carePickerResults input').check();
  await page.locator('#carePickerConfirm').click();
  expect(await page.evaluate(()=>window.pickerResult[0].selection_kind)).toBe('event');
});

test('late detail response cannot populate an account after logout',async({page})=>{
  let release;
  await page.route('https://hierarchy.test/api/care-topics/t1/overview',async route=>{
    await new Promise(resolve=>release=resolve);
    await route.fulfill({json:{id:'t1',name:'旧账号资料',events:[],documents:[],metric_summaries:[],costs_by_currency:[]}});
  });
  await page.goto('https://hierarchy.test/#home');
  await page.locator('[data-care-topic="t1"]').first().click();
  await expect.poll(()=>Boolean(release)).toBe(true);
  await page.evaluate(()=>resetAuth());release();
  await expect(page.locator('#view-auth')).toBeVisible();
  await expect(page.locator('#careDetailPanel')).not.toContainText('旧账号资料');
});

test('splitting archived sources searches only the current visit and confirms the new name',async({page})=>{
  await page.route('https://hierarchy.test/api/care-history/events/e1',route=>route.fulfill({json:{
    id:'e1',title:'合成诊疗',hospital:'合成医院',event_kind_label:'门诊',version:1,topic_ids:[],
    documents:[{id:'d101',title:'单独检查资料',document_type:'检查报告'}],milestones:[],facts:[]}}));
  await page.route('https://hierarchy.test/api/care-history/events/e1/split-documents',route=>{
    page.__split=route.request().postDataJSON();return route.fulfill({json:{event_id:'e1'}});
  });
  await page.goto('https://hierarchy.test/#home');
  await page.locator('[data-care-event="e1"]').first().click();
  const requested=page.waitForRequest(req=>req.url().includes('/care-hierarchy/search?')&&req.url().includes('encounter_id=e1'));
  await page.getByRole('button',{name:'拆出部分资料'}).click();await requested;
  await expect(page.locator('#carePickerResults')).toContainText('第101份');
  await page.locator('#carePickerResults input').check();await page.locator('#carePickerConfirm').click();
  await page.locator('#careActionName').fill('独立检查事件');await page.locator('#careActionConfirm').click();
  await expect.poll(()=>page.__split?.document_ids).toEqual(['d101']);
  expect(page.__split.title).toBe('独立检查事件');
});
