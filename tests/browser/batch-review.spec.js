const {test,expect}=require('@playwright/test');
const path=require('path');
const fs=require('fs');

test.beforeEach(async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));page.__errors=errors;
  await page.route('https://archive.test/**', async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.startsWith('/api/')){
      const data=url.pathname==='/api/system/status'?{model:{configured:true}}:
        url.pathname==='/api/auth/me'?{id:'u1',email:'tester@example.test',role:'admin'}:{items:[]};
      return route.fulfill({json:data});
    }
    const file=path.join(__dirname,'../../app/web',url.pathname==='/'?'index.html':path.basename(url.pathname));
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('https://archive.test/');
  await page.locator('[data-view="upload"]').click();
});

test.afterEach(async({page})=>{expect(page.__errors).toEqual([])});

test('review changes the whole batch target without grouping controls',async({page})=>{
  const batch={id:'care-review',status:'pending_confirmation',version:1,care_context:{mode:'new_topic',name:'合成过程'},
    grouping:{},files:[],sources:[],payload:{groups:[{id:'g1',kind:'document',source_ids:['s1'],
    document:{type:'其他医疗资料',title:'合成原件',key_information:[],source_refs:[],details:{}},
    lab_results:[],medications:[],evidence:[],review_items:[]}],encounters:[],excluded_sources:[],reviewed:false}};
  for(let i=2;i<=20;i++)batch.payload.groups.push({...structuredClone(batch.payload.groups[0]),id:`g${i}`,source_ids:[`s${i}`]});
  let saved;
  await page.route('**/api/batches/care-review/draft',route=>{
    if(route.request().method()==='PUT'){saved=route.request().postDataJSON();batch.payload=saved.payload;batch.grouping.care_targets=saved.care_targets;if(saved.care_context)batch.care_context=saved.care_context;batch.version++}
    return route.fulfill({json:batch});
  });
  await page.evaluate(()=>window.batchReview.open('care-review'));
  await expect(page.locator('#reviewCareMode')).toHaveValue('new_topic');
  await expect(page.locator('#reviewCareName')).toHaveValue('合成过程');
  await expect(page.getByText('恢复上传时的选择',{exact:true})).toHaveCount(0);
  await expect(page.locator('#batchReviewDialog > #batchReviewDestination')).toHaveCount(1);
  await expect(page.locator('#batchFields #batchReviewDestination')).toHaveCount(0);
  await expect(page.locator('.review-group')).toHaveCount(20);
  await expect(page.locator('#batchSourceThumbs')).not.toBeVisible();
  await expect(page.locator('#batchSourceThumbs [data-show-source]')).toHaveCount(0);
  await expect(page.locator('.review-source-actions, #moveReviewSource, #shareReviewSource, #mergeReviewGroup, #excludeReviewSource, #sourceTarget, #visitEditors, #reviewSplitHospitals, [data-edit="encounter_id"], #batchAdvancedJson, #addReviewMed')).toHaveCount(0);
  await expect(page.locator('#batchFields')).not.toContainText('调整诊疗分组');
  await page.locator('#batchReviewed').check();
  await page.evaluate(()=>{window.chooseCareRecords=async()=>null});
  await page.locator('#reviewCareMode').selectOption('existing');
  await expect(page.locator('#reviewCareMode')).toHaveValue('new_topic');
  await expect(page.locator('#batchReviewed')).toBeChecked();
  await page.evaluate(()=>{window.chooseCareRecords=async()=>[{id:'topic-a',title:'大事件 A',selection_kind:'topic'}]});
  await page.locator('#reviewCareMode').selectOption('existing');
  await page.locator('.review-group').nth(19).click();
  await expect(page.locator('#batchReviewDestination')).toContainText('大事件 A');
  await page.locator('#saveBatchReview').click();
  await expect(page.locator('#toast')).toContainText('草稿已保存');
  expect(saved.care_targets).toEqual({});
  expect(saved.care_context).toMatchObject({mode:'existing_topic',name:'大事件 A',topic_id:'topic-a'});
  expect(saved.payload.groups).toHaveLength(20);
  await page.locator('#reviewCareMode').selectOption('small');
  await page.locator('#reviewCareMode').selectOption('new_topic');
  await page.locator('#reviewCareName').fill('术后复诊');
  await page.locator('#saveBatchReview').click();
  await expect(page.locator('#toast')).toContainText('草稿已保存');
  expect(saved.care_context).toMatchObject({mode:'new_topic',name:'术后复诊'});
  await page.locator('.review-destination-menu > summary').click();
  await page.locator('#reviewCareArchive').click();
  await page.locator('#saveBatchReview').click();
  await expect(page.locator('#toast')).toContainText('草稿已保存');
  expect(saved.care_targets).toEqual({});
  expect(saved.care_context.mode).toBe('archive');
  await page.locator('[data-edit="document.type"]').selectOption('门诊病历');
  await page.locator('#saveBatchReview').click();
  expect(saved.payload.groups[19].document.type).toBe('门诊病历');
});

test('excluding a document preserves shared sources and can be restored',async({page})=>{
  const group=(id,sources)=>({id,kind:'document',source_ids:sources,
    document:{type:'其他医疗资料',title:id,key_information:[],source_refs:[],details:{}},
    lab_results:[],medications:[],evidence:[],review_items:[]});
  const batch={id:'exclude-review',status:'pending_confirmation',version:1,grouping:{},files:[],
    sources:[{id:'s1',label:'误传原图',kind:'text'},{id:'shared',label:'共享原图',kind:'text'}],
    payload:{groups:[group('g1',['s1','shared']),group('g2',['shared'])],encounters:[],excluded_sources:[],reviewed:false}};
  let saved;
  await page.route('**/api/batches/exclude-review/draft',route=>{
    if(route.request().method()==='PUT'){saved=route.request().postDataJSON();batch.payload=saved.payload;batch.version++}
    return route.fulfill({json:batch});
  });
  await page.evaluate(()=>window.batchReview.open('exclude-review'));
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#excludeCurrentDocument').click();
  await expect(page.locator('.review-group')).toHaveCount(1);
  await page.locator('#saveBatchReview').click();
  await expect(page.locator('#toast')).toContainText('草稿已保存');
  expect(saved.payload.groups[0].source_ids).toEqual(['shared']);
  expect(saved.payload.excluded_sources).toEqual([{source_id:'s1',reason:'用户选择不归档这份资料'}]);
  await page.getByRole('button',{name:'恢复这份资料',exact:true}).click();
  await page.locator('#saveBatchReview').click();
  await expect(page.locator('.review-group')).toHaveCount(2);
  expect(saved.payload.excluded_sources).toEqual([]);
  expect(saved.payload.groups.flatMap(g=>g.source_ids)).toContain('s1');
});

test('multiple selection and right click distinguish document and encounter groups',async({page})=>{
  await page.locator('[data-upload-intent="small"]').click();
  await page.locator('#fileInput').setInputFiles([
    {name:'药盒正面.png',mimeType:'image/png',buffer:Buffer.from('image-one')},
    {name:'药盒背面.png',mimeType:'image/png',buffer:Buffer.from('image-two')},
    {name:'检验报告.png',mimeType:'image/png',buffer:Buffer.from('image-three')},
  ]);
  await expect(page.locator('.batch-file')).toHaveCount(3);
  await page.locator('.batch-file').nth(0).click();
  await page.locator('.batch-file').nth(1).click({modifiers:['Control']});
  await page.locator('.batch-file').nth(1).click({button:'right'});
  await page.locator('#batchContext').getByRole('button',{name:'设为同一药品',exact:true}).click();
  await expect(page.locator('.batch-file').nth(0)).toContainText('药品组 1');
  await expect(page.locator('.batch-file').nth(1)).toContainText('药品组 1');
  await page.getByRole('button',{name:'全选文件',exact:true}).click();
  await page.locator('#batchToolbar').getByRole('button',{name:'关联同一次就诊',exact:true}).click();
  await expect(page.locator('.batch-file').nth(2)).toContainText('就诊 1');
  await expect(page.locator('.batch-file').nth(0)).toContainText('药品组 1');
});

test('review keeps source pages and visit links while saving fields',async({page})=>{
  const imageRequests=[];page.on('request',request=>{if(request.url().includes('/fixture-preview-'))imageRequests.push(new URL(request.url()).pathname)});
  const doc={type:'检查报告',title:'报告两页',primary_date:null,primary_date_raw:null,hospital:'测试医院',department:null,doctor:null,amount:null,key_information:[],parsed_content:'合成测试资料',source_refs:[]};
  const batch={id:'b1',status:'pending_confirmation',version:1,grouping:{},files:[
    {id:'f1',attachment_id:'a1',filename:'第一页.png',mime_type:'image/png',content_url:'/fixture-one',preview_url:'/fixture-preview-one',thumbnail_url:'/fixture-thumb-one'},
    {id:'f2',attachment_id:'a2',filename:'第二页.png',mime_type:'image/png',content_url:'/fixture-two',preview_url:'/fixture-preview-two',thumbnail_url:'/fixture-thumb-two'}],sources:[
    {id:'s1',attachment_id:'a1',page_index:1,label:'第一页',kind:'image',content_url:'/fixture-one'},
    {id:'s2',attachment_id:'a2',page_index:1,label:'第二页',kind:'image',content_url:'/fixture-two'}],
    payload:{groups:[{id:'g1',kind:'document',source_ids:['s1','s2'],encounter_id:'v1',patient_identity:null,document:doc,lab_results:[{name:'胱抑素 C',result:'0.91',unit:'mg/L',source_id:'s1',result_type:'numeric',review_status:'pending'}],medications:[],evidence:[],review_items:[]}],encounters:[{id:'v1',title:'合成就诊',hospital:'测试医院'}],excluded_sources:[],review_items:[],reviewed:false}};
  await page.route('**/fixture-*',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1800"><rect width="800" height="1800" fill="white"/><rect x="8" y="8" width="784" height="1784" fill="none" stroke="blue" stroke-width="10"/><text x="100" y="200" font-size="50">TEST REPORT</text><text x="100" y="1700" font-size="50">END OF PAGE</text></svg>'}));
  await page.route('**/api/batches/b1/draft',async route=>{if(route.request().method()==='PUT'){const body=route.request().postDataJSON();batch.payload=body.payload;batch.version++;}await route.fulfill({json:batch})});
  await page.route('**/api/batches',route=>route.fulfill({json:{items:[batch]}}));
  await page.evaluate(()=>window.batches.refresh());
  await page.getByRole('button',{name:'核对资料',exact:true}).click();
  await expect(page.locator('#batchReviewDialog')).toBeVisible();
  await expect(page.locator('#batchSourceThumbs')).toBeVisible();
  await expect(page.locator('#batchSourceThumbs [data-show-source]')).toHaveCount(2);
  await page.locator('[data-edit="lab_results.0.review_status"]').selectOption('confirmed');
  const image=page.locator('#batchSourceView img');await expect(image).toBeVisible();
  await expect(image).toHaveAttribute('src','/fixture-preview-one');
  await expect.poll(()=>imageRequests.includes('/fixture-preview-two')).toBe(true);
  await expect(page.locator('#batchSourceLinks a')).toHaveAttribute('href','/fixture-one');
  await expect(page.locator('#batchSourceThumbs img').first()).toHaveAttribute('src','/fixture-thumb-one');
  await image.evaluate(el=>{el.dataset.persist='same-node'});
  await page.locator('#reviewCareMode').selectOption('new_topic');
  await expect(image).toHaveAttribute('data-persist','same-node');
  const dims=await image.evaluate(el=>({width:el.clientWidth,height:el.clientHeight,container:el.parentElement.clientHeight,fit:getComputedStyle(el).objectFit,loaded:el.complete&&el.naturalHeight>0}));
  expect(dims.fit).toBe('contain');expect(dims.loaded).toBeTruthy();expect(dims.height).toBeLessThanOrEqual(dims.container);
  await page.screenshot({path:'test-results/batch-review-desktop.png'});
  await expect(page.locator('[data-select-source]')).toHaveCount(0);
  await page.locator('[data-show-source="s2"]').click();
  await expect(image).toHaveAttribute('src','/fixture-preview-two');
  await expect(page.locator('#batchSourceLinks')).toContainText('第二页');
  await page.locator('[data-edit="document.title"]').fill('已核对检查报告');
  await page.locator('#saveBatchReview').click();
  await expect(page.locator('#toast')).toContainText('草稿已保存');
  expect(batch.payload.groups).toHaveLength(1);
  expect(batch.payload.groups[0].source_ids).toEqual(['s1','s2']);
  expect(batch.payload.groups[0].encounter_id).toBe('v1');
  expect(batch.payload.encounters).toEqual([{id:'v1',title:'合成就诊',hospital:'测试医院'}]);
  expect(batch.payload.groups[0].document.title).toBe('已核对检查报告');
  expect(batch.payload.groups[0].lab_results[0].review_status).toBe('confirmed');
  await page.locator('#batchReviewClose').click();
  await page.getByRole('button',{name:'核对资料',exact:true}).click();
  await expect(page.locator('.review-group')).toHaveCount(1);
  await page.setViewportSize({width:390,height:844});
  await expect(page.locator('#batchSourceView img')).toBeVisible();
  await page.screenshot({path:'test-results/batch-review-mobile.png'});
});

test('different hospital originals do not show blocking validation errors',async({page})=>{
  const makeGroup=(id,source,hospital)=>({id,kind:'document',source_ids:[source],encounter_id:'v1',
    patient_identity:null,document:{type:'检验报告',title:id,hospital,patient_scope:'self',
      key_information:[],parsed_content:'',source_refs:[],details:{}},
    lab_results:[],medications:[],evidence:[],review_items:[]});
  const batch={id:'b2',status:'pending_confirmation',version:1,grouping:{},files:[
    {id:'f1',attachment_id:'a1',filename:'一.png',mime_type:'image/png',content_url:'/fixture-one'},
    {id:'f2',attachment_id:'a2',filename:'二.png',mime_type:'image/png',content_url:'/fixture-two'}],sources:[
    {id:'s1',attachment_id:'a1',page_index:1,label:'一',kind:'image',content_url:'/fixture-one'},
    {id:'s2',attachment_id:'a2',page_index:1,label:'二',kind:'image',content_url:'/fixture-two'}],
    payload:{groups:[makeGroup('g1','s1','上海市肺科医院'),makeGroup('g2','s2','上海市职业病防治院')],
      encounters:[{id:'v1',title:'就诊',hospital:'上海市肺科医院'}],excluded_sources:[],review_items:[],reviewed:true}};
  await page.route('**/api/batches/b2/draft',route=>route.fulfill({json:batch}));
  await page.route('**/fixture-*',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'}));
  await page.evaluate(()=>window.batchReview.open('b2'));
  const hospital=page.locator('[data-edit="document.hospital"]');
  await expect(hospital).not.toHaveClass(/needs-review/);
  await page.locator('.review-group').nth(1).click();
  await hospital.fill('其他医院');
  await expect(hospital).toHaveAttribute('aria-invalid','false');
  await expect(hospital).not.toHaveClass(/needs-review/);
  await page.locator('.review-group').nth(0).click();
  await expect(hospital).not.toHaveClass(/needs-review/);
  await page.locator('.review-group').nth(1).click();
  await hospital.fill('上海市肺科医院、上海市职业病防治医院');
  await expect(hospital).toHaveAttribute('aria-invalid','false');
  await expect(hospital).not.toHaveClass(/needs-review/);
});


async function editableReview(page,careContext={mode:'small'},groupCount=1,reviewItems=[],failedIndex=null){
  const state={saves:0,confirmations:0,failSave:false};
  const batch={id:'close-test',status:'pending_confirmation',version:1,care_context:careContext,grouping:{},files:[],sources:[],
    payload:{groups:[{id:'g',kind:'document',source_ids:['s'],document:{type:'其他医疗资料',title:'合成报告',key_information:[],source_refs:[],details:{}},lab_results:[],medications:[],evidence:[],review_items:[]}],encounters:[],excluded_sources:[],reviewed:false}};
  for(let i=1;i<groupCount;i++)batch.payload.groups.push({...structuredClone(batch.payload.groups[0]),id:`g${i}`,source_ids:[`s${i}`],document:{...batch.payload.groups[0].document,title:`第 ${i+1} 份合成检验报告及核对资料`}});
  batch.payload.review_items=reviewItems;
  if(failedIndex!==null)batch.payload.groups[failedIndex].review_items=['自动提取失败：请对照原件补全字段'];
  await page.route('**/api/batches/close-test/draft',route=>{
    if(route.request().method()==='PUT'){
      state.saves++;
      if(state.failSave)return route.fulfill({status:503,json:{detail:'合成保存失败'}});
      const saved=route.request().postDataJSON();batch.payload=saved.payload;batch.grouping.care_targets=saved.care_targets;
      if(saved.care_context)batch.care_context=saved.care_context;batch.version++;
    }
    return route.fulfill({json:batch});
  });
  await page.route('**/api/batches/close-test/confirm',route=>{state.confirmations++;return route.fulfill({json:{}})});
  await page.evaluate(()=>window.batchReview.open('close-test'));
  return state;
}

test('incomplete extraction is prominent and names the affected document',async({page})=>{
  await editableReview(page,{mode:'small'},2,[],1);
  await expect(page.locator('#batchReviewPartialNotice')).toBeVisible();
  await expect(page.locator('#batchReviewPartialNotice')).toContainText('1 份资料');
  await expect(page.locator('.review-group').nth(0)).not.toContainText('需人工补全');
  await expect(page.locator('.review-group').nth(1)).toContainText('需人工补全');
  await page.locator('.review-group').nth(1).click();
  await expect(page.locator('#batchReviewPartialNotice')).toContainText('对照原件');
});

test('closing an edited review offers continue, discard and save without archiving',async({page})=>{
  const state=await editableReview(page);
  const title=page.locator('[data-edit="document.title"]');
  await title.fill('修改的报告');
  await page.locator('#batchReviewClose').click();
  await expect(page.locator('#batchCloseDialog')).toBeVisible();
  await page.screenshot({path:'test-results/batch-close-prompt.png'});
  await page.locator('#batchCloseContinue').click();
  await expect(title).toHaveValue('修改的报告');
  await page.keyboard.press('Escape');
  await expect(page.locator('#batchCloseDialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('#batchCloseDialog')).not.toBeVisible();
  await expect(title).toHaveValue('修改的报告');
  await page.locator('#batchReviewClose').click();
  await page.locator('#batchCloseDiscard').click();
  await expect(page.locator('#batchReviewDialog')).not.toBeVisible();
  expect(state.saves).toBe(0);
  await page.evaluate(()=>window.batchReview.open('close-test'));
  await expect(title).toHaveValue('合成报告');
  await title.fill('保留的修改');
  await page.locator('#batchReviewClose').click();
  await page.locator('#batchCloseSave').click();
  await expect(page.locator('#batchReviewDialog')).not.toBeVisible();
  expect(state.saves).toBe(1);expect(state.confirmations).toBe(0);
  await page.evaluate(()=>window.batchReview.open('close-test'));
  await expect(title).toHaveValue('保留的修改');
  await page.locator('#batchReviewClose').click();
  await expect(page.locator('#batchReviewDialog')).not.toBeVisible();
  await expect(page.locator('#batchCloseDialog')).not.toBeVisible();
});

test('failed save keeps the close prompt and edits available for retry',async({page})=>{
  const state=await editableReview(page);state.failSave=true;
  await page.locator('[data-edit="document.title"]').fill('失败时仍保留');
  await page.locator('#batchReviewClose').click();
  await page.locator('#batchCloseSave').click();
  await expect(page.locator('#batchCloseError')).toContainText('合成保存失败');
  await expect(page.locator('#batchCloseDialog')).toBeVisible();
  await expect(page.locator('#batchCloseSave')).toBeEnabled();
  state.failSave=false;
  await page.locator('#batchCloseSave').click();
  await expect(page.locator('#batchReviewDialog')).not.toBeVisible();
  expect(state.confirmations).toBe(0);
});

test('review remains reachable without horizontal overflow across screen sizes',async({page})=>{
  await editableReview(page,{mode:'existing_topic',topic_id:'t1',name:'合成长期诊疗主题'.repeat(12)});
  for(const [width,height] of [[1920,1080],[1440,900],[1024,768],[820,700],[768,1024],[390,844],[360,640],[844,390]]){
    await page.setViewportSize({width,height});
    const geometry=await page.locator('#batchReviewDialog').evaluate(el=>{
      const rect=el.getBoundingClientRect(),target=el.querySelector('#batchReviewDestination');
      const layout=el.querySelector('.batch-review-layout');
      return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,targetOverflow:target.scrollWidth-target.clientWidth,layoutHeight:layout.clientHeight};
    });
    expect(geometry.left).toBeGreaterThanOrEqual(-1);expect(geometry.right).toBeLessThanOrEqual(width+1);
    expect(geometry.top).toBeGreaterThanOrEqual(-1);expect(geometry.bottom).toBeLessThanOrEqual(height+1);
    expect(geometry.targetOverflow,`${width}x${height}`).toBeLessThanOrEqual(1);
    expect(geometry.layoutHeight,`${width}x${height}`).toBeGreaterThan(60);
    await page.locator('[data-edit="document.title"]').scrollIntoViewIfNeeded();
    const titleRect=await page.locator('[data-edit="document.title"]').boundingBox();
    const layoutRect=await page.locator('.batch-review-layout').boundingBox();
    expect(titleRect.y).toBeGreaterThanOrEqual(layoutRect.y-1);
    expect(titleRect.y+titleRect.height).toBeLessThanOrEqual(layoutRect.y+layoutRect.height+1);
    expect(titleRect.x).toBeGreaterThanOrEqual(0);expect(titleRect.x+titleRect.width).toBeLessThanOrEqual(width);
    const buttonRect=await page.locator('#confirmBatchReview').boundingBox();
    expect(buttonRect.y+buttonRect.height).toBeLessThanOrEqual(height);
    if(width===844)await page.screenshot({path:'test-results/batch-review-landscape.png'});
  }
});

test('display preview failure falls back to the original image once',async({page})=>{
  await page.route('**/fixture-preview-failed',route=>route.fulfill({status:503,body:''}));
  await page.route('**/fixture-original',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="white"/></svg>'}));
  await page.evaluate(()=>{
    const holder=document.createElement('div');holder.id='fallbackFixture';
    holder.innerHTML=attachmentPreview({mime_type:'image/png',filename:'合成图片',content_url:'/fixture-original',preview_url:'/fixture-preview-failed'});
    document.body.append(holder);
  });
  await expect(page.locator('#fallbackFixture img')).toHaveAttribute('src','/fixture-original');
  await expect.poll(()=>page.locator('#fallbackFixture img').evaluate(el=>el.complete&&el.naturalWidth>0)).toBe(true);
  await expect(page.locator('#fallbackFixture img')).not.toHaveAttribute('data-original-src',/.+/);
});

for(const [mode,context] of [['small',{mode:'small'}],['big',{mode:'new_topic',name:'合成手术'}],['existing',{mode:'existing_topic',topic_id:'t1',name:'合成诊疗主题'.repeat(12)}]]){
  test(`review ${mode} target remains usable at extreme zoom viewport`,async({page})=>{
    await page.setViewportSize({width:384,height:184});
    await editableReview(page,context);
    // 384x184 approximates the 1920x920 screenshot at 500% zoom.
    for(const [width,height] of [[320,640],[640,360],[960,250],[384,184]]){
      await page.setViewportSize({width,height});
      const target=page.locator('#batchReviewDestination');
      expect(await target.evaluate(el=>el.scrollWidth-el.clientWidth),`${mode} ${width}x${height}`).toBeLessThanOrEqual(1);
      await page.locator('#reviewCareMode').scrollIntoViewIfNeeded();
      await expect(page.locator('#reviewCareMode')).toBeInViewport({ratio:1});
      await page.locator('[data-edit="document.title"]').scrollIntoViewIfNeeded();
      // Fractional scroll positions can clip a fraction of one pixel at the pane edge.
      await expect(page.locator('[data-edit="document.title"]')).toBeInViewport({ratio:.99});
      const bounds=await page.locator('[data-edit="document.title"]').boundingBox();
      expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);
      await page.locator('#batchReviewed').scrollIntoViewIfNeeded();
      await page.locator('#batchReviewed').check();
      await page.locator('#confirmBatchReview').scrollIntoViewIfNeeded();
      await expect(page.locator('#confirmBatchReview')).toBeInViewport({ratio:1});
      if(width===384)await page.screenshot({path:`test-results/review-extreme-${mode}.png`});
    }
    await page.locator('#saveBatchReview').click();
    await page.locator('#batchReviewClose').click();
    await expect(page.locator('#batchReviewDialog')).not.toBeVisible();
  });
}

test('13 document cards stay compact at the 250 percent zoom layout',async({page})=>{
  await page.setViewportSize({width:768,height:368});
  await editableReview(page,{mode:'small'},13,Array.from({length:30},(_,i)=>`第 ${i+1} 项字段存在待核对内容，请对照原件确认日期、医院和检验信息`));
  await expect(page.locator('.review-group')).toHaveCount(13);
  for(const [width,height] of [[768,368],[768,320],[640,360],[390,844],[384,184]]){
    await page.setViewportSize({width,height});
    const geometry=await page.locator('#reviewGroups').evaluate(el=>({height:el.getBoundingClientRect().height,cardHeights:[...el.querySelectorAll('.review-group')].map(card=>card.getBoundingClientRect().height),layoutOverflow:el.parentElement.scrollWidth-el.parentElement.clientWidth,dialogOverflow:el.closest('dialog').scrollWidth-el.closest('dialog').clientWidth}));
    expect(geometry.height,`${width}x${height}`).toBeLessThanOrEqual(200);
    expect(Math.max(...geometry.cardHeights)).toBeLessThanOrEqual(120);
    expect(geometry.layoutOverflow).toBeLessThanOrEqual(1);
    expect(geometry.dialogOverflow).toBeLessThanOrEqual(1);
  }
  await page.setViewportSize({width:768,height:368});
  await page.locator('.review-group').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:'test-results/review-13-files-compact-list.png'});
  await expect(page.locator('.review-issues summary')).toContainText('30 项');
  await page.locator('.review-issues summary').click();
  await expect(page.locator('.review-issues p')).toHaveCount(30);
  expect(await page.locator('.review-group').first().evaluate(el=>el.getBoundingClientRect().height)).toBeLessThanOrEqual(120);
  await page.locator('.review-issues summary').click();
  await page.locator('.review-group').nth(12).click();
  await expect(page.locator('[data-edit="document.title"]')).toHaveValue('第 13 份合成检验报告及核对资料');
  await page.locator('[data-edit="document.title"]').scrollIntoViewIfNeeded();
  await expect(page.locator('[data-edit="document.title"]')).toBeInViewport({ratio:.99});
  await page.screenshot({path:'test-results/review-13-files-250-percent.png'});
});
