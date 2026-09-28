const {test,expect}=require('@playwright/test');
const path=require('path');
const fs=require('fs');

test.beforeEach(async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));page.__errors=errors;
  await page.route('https://archive.test/**',route=>{
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
});

test.afterEach(async({page})=>expect(page.__errors).toEqual([]));

test('planner splits 45 files into 20, 20, 5 and keeps manual groups intact',async({page})=>{
  const planned=await page.evaluate(()=>{
    const files=Array.from({length:45},(_,i)=>({key:`f${i}`,size:1,uploaded:false}));
    const limits={max_selection:100,max_files_per_batch:20,max_bytes_per_batch:100,max_bytes_per_file:25};
    const plain=window.planUploadBatches(files,[],[],limits,false);
    const grouped=window.planUploadBatches(files,[{ids:['f19','f20']}],[],limits,false);
    const resumed=window.planUploadBatches(files.map((f,i)=>({...f,uploaded:i<20})),[],[],limits,true);
    return {plain,grouped,resumed};
  });
  expect(planned.plain.map(batch=>batch.length)).toEqual([20,20,5]);
  expect(planned.grouped.findIndex(batch=>batch.includes('f19'))).toBe(planned.grouped.findIndex(batch=>batch.includes('f20')));
  expect(planned.resumed.map(batch=>batch.length)).toEqual([20,20,5]);
  expect(planned.resumed[0]).toEqual(Array.from({length:20},(_,i)=>`f${i}`));
});

test('planner rejects more than 100 files and groups too large for one server batch',async({page})=>{
  const result=await page.evaluate(()=>{
    const files=Array.from({length:101},(_,i)=>({key:`f${i}`,size:1,uploaded:false}));
    const limits={max_selection:100,max_files_per_batch:20,max_bytes_per_batch:100,max_bytes_per_file:25};
    const errors=[];
    try{window.planUploadBatches(files,[],[],limits,false)}catch(error){errors.push(error.message)}
    try{window.planUploadBatches(files.slice(0,21),[{ids:files.slice(0,21).map(f=>f.key)}],[],limits,false)}catch(error){errors.push(error.message)}
    return errors;
  });
  expect(result[0]).toContain('100');
  expect(result[1]).toContain('20');
});

async function mockBatchServer(page,{failOnceAt}={}){
  const state={batches:[],submits:[],submitPayloads:[],uploads:0,failed:false};
  await page.route('https://archive.test/api/batches/**',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();
    if(url.pathname==='/api/batches/limits')return route.fulfill({json:{
      max_selection:100,max_files_per_batch:20,max_bytes_per_batch:100000000,max_bytes_per_file:25000000,
    }});
    const id=url.pathname.match(/^\/api\/batches\/(b\d+)/)?.[1];
    const batch=state.batches.find(item=>item.id===id);
    if(!batch)return route.fulfill({status:404,json:{detail:'批次不存在'}});
    if(url.pathname.endsWith('/files')&&method==='POST'){
      state.uploads++;
      if(state.uploads===failOnceAt&&!state.failed){state.failed=true;return route.fulfill({status:503,json:{detail:'临时上传失败'}})}
      const body=route.request().postData()||'';
      const clientId=body.match(/name="client_file_id"\r?\n\r?\n([^\r\n]+)/)?.[1];
      expect(clientId).toBeTruthy();
      batch.files.push({id:`file-${state.uploads}`,client_file_id:clientId,filename:`文件${state.uploads}.png`,mime_type:'image/png'});
      batch.version++;return route.fulfill({json:batch});
    }
    if(url.pathname.endsWith('/submit')&&method==='POST'){
      state.submits.push(batch.files.length);state.submitPayloads.push(route.request().postDataJSON());batch.status='queued';batch.version++;
      return route.fulfill({json:batch});
    }
    if(url.pathname.endsWith('/grouping')&&method==='PUT'){
      batch.grouping=route.request().postDataJSON();batch.version++;return route.fulfill({json:batch});
    }
    return route.fulfill({json:batch});
  });
  await page.route('https://archive.test/api/batches',route=>{
    if(route.request().method()==='POST'){
      const batch={id:`b${state.batches.length+1}`,status:'receiving',version:1,files:[],grouping:{groups:[],encounters:[]},care_context:route.request().postDataJSON().care_context};
      state.batches.push(batch);return route.fulfill({status:201,json:batch});
    }
    return route.fulfill({json:{items:state.batches}});
  });
  return state;
}

function fakeFiles(count){return Array.from({length:count},(_,i)=>({name:`文件${i+1}.png`,mimeType:'image/png',buffer:Buffer.from(`image-${i+1}`)}))}

test('new big event target survives automatic batches and partial upload retry',async({page})=>{
  const server=await mockBatchServer(page,{failOnceAt:22});
  await page.locator('[data-view="upload"]').click();
  await page.locator('[data-upload-intent="new_topic"]').click();
  await page.locator('#uploadCareName').fill('合成连续诊疗');
  await page.locator('#fileInput').setInputFiles(fakeFiles(45));
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.failed,{timeout:15000}).toBe(true);
  await expect(page.locator('.batch-file').filter({hasText:'临时上传失败'})).toHaveCount(1);
  await expect(page.locator('#uploadCareMode')).toBeDisabled();
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.submits).toEqual([20,20,5]);
  expect(new Set(server.batches.map(b=>b.care_context.intent_key)).size).toBe(1);
  expect(server.batches.every(b=>b.care_context.mode==='new_topic'&&b.care_context.name==='合成连续诊疗')).toBeTruthy();
  expect(server.submitPayloads.every(b=>b.groups.length===0&&b.encounters.length===0)).toBeTruthy();
});

test('100 supplemental files keep the same big event through five automatic batches',async({page})=>{
  test.setTimeout(45000);
  const server=await mockBatchServer(page);
  await page.evaluate(()=>window.batches.setCareTarget({mode:'existing_topic',topic_id:'topic-a',name:'大事件 A'}));
  await page.locator('[data-view="upload"]').click();
  await page.locator('#fileInput').setInputFiles(fakeFiles(100));
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.submits,{timeout:30000}).toEqual([20,20,20,20,20]);
  expect(new Set(server.batches.map(b=>b.care_context.intent_key)).size).toBe(1);
  expect(server.batches.every(b=>b.care_context.mode==='existing_topic'&&b.care_context.topic_id==='topic-a')).toBeTruthy();
});

test('detail supplement prefills existing target without stale source grouping',async({page})=>{
  await page.evaluate(()=>window.batches.setCareTarget({mode:'existing_topic',topic_id:'t1',name:'合成补充过程'}));
  await page.locator('[data-view="upload"]').click();
  await expect(page.locator('#uploadCareMode')).toHaveValue('existing_topic');
  await expect(page.locator('#uploadCareSelected')).toContainText('合成补充过程');
  await expect(page.locator('.batch-file')).toHaveCount(0);
});

test('resumed new parent context sends intent without generated parent id to next subbatch',async({page})=>{
  const server=await mockBatchServer(page);
  await page.route('https://archive.test/saved-*.png',route=>route.fulfill({body:Buffer.alloc(0),contentType:'image/png'}));
  server.batches.push({id:'b1',status:'receiving',version:21,care_context:{mode:'new_topic',name:'已建立过程',intent_key:'intent-1',topic_id:'generated-topic'},grouping:{groups:[],encounters:[]},files:
    Array.from({length:20},(_,i)=>({id:`saved-file-${i}`,client_file_id:`saved-${i}`,filename:`保存${i}.png`,mime_type:'image/png',size_bytes:10,content_url:`/saved-${i}.png`}))});
  await page.locator('[data-view="upload"]').click();
  await page.evaluate(()=>window.batches.refresh());
  await page.getByRole('button',{name:'继续上传与分组'}).click();
  await page.locator('#fileInput').setInputFiles(fakeFiles(1));
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.submits).toEqual([20,1]);
  expect(server.batches[1].care_context.intent_key).toBe('intent-1');
  expect(server.batches[1].care_context.topic_id).toBeNull();
});

test('45 selected files are uploaded and submitted as three independent tasks',async({page})=>{
  const server=await mockBatchServer(page);
  await page.locator('[data-view="upload"]').click();
  await page.locator('[data-upload-intent="small"]').click();
  await page.locator('#fileInput').setInputFiles(fakeFiles(45));
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.submits).toEqual([20,20,5]);
  await expect(page.locator('.batch-file')).toHaveCount(0);
  expect(server.uploads).toBe(45);
});

test('over 100 files are rejected before any batch or file is uploaded',async({page})=>{
  const server=await mockBatchServer(page);
  await page.locator('[data-view="upload"]').click();
  await page.locator('[data-upload-intent="small"]').click();
  await page.locator('#fileInput').setInputFiles(fakeFiles(101));
  await expect(page.locator('#toast')).toContainText('一次最多选择 100 个文件');
  await expect(page.locator('.batch-file')).toHaveCount(0);
  expect(server.batches).toHaveLength(0);
});

test('a failed second batch resumes without reuploading the first batch',async({page})=>{
  const server=await mockBatchServer(page,{failOnceAt:22});
  await page.locator('[data-view="upload"]').click();
  await page.locator('[data-upload-intent="small"]').click();
  await page.locator('#fileInput').setInputFiles(fakeFiles(45));
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.failed,{timeout:15000}).toBe(true);
  await expect(page.locator('.batch-file').filter({hasText:'临时上传失败'})).toHaveCount(1);
  expect(server.submits).toEqual([20]);
  await expect(page.locator('.batch-file')).toHaveCount(25);
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.submits).toEqual([20,20,5]);
  expect(server.batches.map(batch=>batch.files.length)).toEqual([20,20,5]);
  expect(server.uploads).toBe(46);
});

test('manual document group stays in one submitted batch near the split boundary',async({page})=>{
  const server=await mockBatchServer(page);
  await page.locator('[data-view="upload"]').click();
  await page.locator('[data-upload-intent="small"]').click();
  await page.locator('#fileInput').setInputFiles(fakeFiles(21));
  await page.locator('.batch-file').nth(19).click();
  await page.locator('.batch-file').nth(20).click({modifiers:['Control']});
  await page.locator('#batchToolbar [data-batch-action="document"]').click();
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.submits).toEqual([19,2]);
  expect(server.submitPayloads[1].groups).toHaveLength(1);
  expect(server.submitPayloads[1].groups[0].file_ids).toHaveLength(2);
});

test('an existing full receiving batch can be resumed and submitted without another upload',async({page})=>{
  const server=await mockBatchServer(page);
  await page.route('https://archive.test/saved-*.png',route=>route.fulfill({body:Buffer.alloc(0),contentType:'image/png'}));
  server.batches.push({id:'b1',status:'receiving',version:21,grouping:{groups:[],encounters:[]},files:
    Array.from({length:20},(_,i)=>({id:`file-${i+1}`,client_file_id:`saved-${i+1}`,filename:`已保存${i+1}.png`,
      mime_type:'image/png',size_bytes:10,content_url:`/saved-${i+1}.png`}))});
  await page.locator('[data-view="upload"]').click();
  await page.evaluate(()=>window.batches.refresh());
  await page.getByRole('button',{name:'继续上传与分组'}).click();
  await expect(page.locator('.batch-file')).toHaveCount(20);
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.submits).toEqual([20]);
  expect(server.uploads).toBe(0);
});


test('upload entry requires a choice and returns to choices after submission',async({page})=>{
  const server=await mockBatchServer(page);
  await page.locator('[data-view="upload"]').click();
  await expect(page.locator('#uploadIntent')).toBeVisible();
  await expect(page.locator('#uploadIntent button')).toHaveCount(3);
  await expect(page.locator('#uploadForm')).toBeHidden();
  await expect(page.locator('#fileInput')).toBeDisabled();
  await page.locator('[data-upload-intent="small"]').click();
  await expect(page.locator('#uploadForm')).toBeVisible();
  await page.locator('#fileInput').setInputFiles(fakeFiles(1));
  await page.locator('#uploadChangeIntent').click();
  await expect(page.locator('#uploadForm')).toBeHidden();
  await page.locator('[data-upload-intent="new_topic"]').click();
  await expect(page.locator('.batch-file')).toHaveCount(1);
  await page.locator('#uploadSubmit').click();
  await expect.poll(()=>server.submits).toEqual([1]);
  await expect(page.locator('#uploadIntent')).toBeVisible();
  expect(server.batches[0].care_context.mode).toBe('new_topic');
});

test('supplement entry stays closed on cancel and opens only after selecting a target',async({page})=>{
  await page.route('**/api/care-hierarchy/search?**',route=>route.fulfill({json:{items:[{id:'t1',name:'合成大事件'}],total:1,next_offset:null}}));
  await page.locator('[data-view="upload"]').click();
  await page.locator('[data-upload-intent="existing"]').click();
  await page.locator('#carePickerCancel').click();
  await expect(page.locator('#uploadForm')).toBeHidden();
  await page.locator('[data-upload-intent="existing"]').click();
  await page.locator('#carePickerResults input').check();
  await page.locator('#carePickerConfirm').click();
  await expect(page.locator('#uploadForm')).toBeVisible();
  await expect(page.locator('#uploadCareSelected')).toContainText('合成大事件');
  await page.evaluate(()=>window.batches.reset());
  await expect(page.locator('#uploadIntent')).toBeVisible();
});


test('model status shows both configured backups without credentials',async({page})=>{
  await page.route('**/api/system/status',route=>route.fulfill({json:{model:{configured:true,fallback_configured:true,fallback2_configured:true}}}));
  await page.reload();
  await expect(page.locator('#modelStatus')).toContainText('2 个备用已配置');
});
