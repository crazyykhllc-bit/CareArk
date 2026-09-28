/* Persistent mixed uploads. One batch can contain several document, drug and visit groups. */
(() => {
  const ui = {files:[], selected:new Set(), groups:[], encounters:[], batch:null, busy:false, anchor:0, queue:[], timer:null};
  const labels={receiving:'等待上传完成并提交',queued:'等待识别',preprocessing:'正在整理文件',extracting:'视觉模型联合识别中',pending_confirmation:'等待人工核对',failed:'处理失败',archived:'已归档'};
  const esc=escapeHtml;
  ui.care={mode:null,name:null,topic_id:null,event_id:null};ui.intentKey=null;ui.careLocked=false;
  const uploadGrid=$('uploadForm').closest('.upload-grid');
  const entry=document.createElement('section');entry.id='uploadIntent';entry.className='panel upload-intent';
  entry.innerHTML=`<span class="section-index">第一步 · 选择资料归属</span><h3>这次要上传什么资料？</h3><p>先选择事件类型或已有事件，再添加文件。</p><div class="upload-intent-options"><button type="button" data-upload-intent="small"><strong>新建小事件</strong><span>一次独立诊疗，后续也可以升级为大事件</span></button><button type="button" data-upload-intent="new_topic"><strong>新建大事件</strong><span>手术、住院或持续治疗，可陆续补充各次诊疗资料</span></button><button type="button" data-upload-intent="existing"><strong>补充已有资料</strong><span>先选择已有大事件或小事件，再为它上传资料</span></button></div>`;
  uploadGrid.before(entry);
  const care=document.createElement('section');care.className='review-subsection';
  care.innerHTML=`<h3 id="uploadCareHeading">这些资料归到哪里</h3><div class="review-field-grid"><label>事件归属<select id="uploadCareMode"><option value="">请选择</option><option value="small">新建小事件</option><option value="new_topic">新建大事件</option><option value="existing_topic">补充已有大事件</option><option value="existing_event">补充已有小事件</option><option value="archive">仅归档原始资料</option></select></label><label id="uploadCareNameLabel">事件名称（可留空，核对时确认）<input id="uploadCareName" maxlength="300" placeholder="例如：手术前后与随访"></label></div><p id="uploadCareSelected" role="status"></p><button type="button" class="btn small hidden" id="uploadCareChoose">搜索已有事件 / 更换</button><p id="uploadCareLock" class="batch-help"></p>`;
  $('uploadForm').prepend(care);
  const changeIntent=document.createElement('button');changeIntent.type='button';changeIntent.className='btn small';changeIntent.id='uploadChangeIntent';changeIntent.textContent='重新选择事件类型';care.prepend(changeIntent);
  $('uploadCareMode').closest('label').classList.add('hidden');
  function drawCare(){
    const locked=ui.busy||ui.careLocked;
    const ready=Boolean(ui.care.mode)&&(!(ui.care.mode||'').startsWith('existing_')||Boolean(ui.care.topic_id||ui.care.event_id));
    entry.classList.toggle('hidden',ready);uploadGrid.classList.toggle('hidden',!ready);$('fileInput').disabled=!ready||ui.busy;changeIntent.disabled=locked;
    $('uploadCareHeading').textContent=({small:'新建小事件',new_topic:'新建大事件',existing_topic:'补充已有大事件',existing_event:'补充已有小事件',archive:'仅归档原始资料'})[ui.care.mode]||'这些资料归到哪里';
    $('uploadCareMode').value=ui.care.mode||'';$('uploadCareMode').disabled=locked;
    $('uploadCareName').placeholder=ui.care.mode==='small'?'例如：一次感冒就诊':'例如：手术前后与随访';
    $('uploadCareName').value=ui.care.name||'';$('uploadCareName').disabled=locked;
    const existing=(ui.care.mode||'').startsWith('existing_');
    $('uploadCareNameLabel').classList.toggle('hidden',existing||ui.care.mode==='archive');
    $('uploadCareChoose').classList.toggle('hidden',!existing);$('uploadCareChoose').disabled=locked;
    $('uploadCareSelected').textContent=existing?(ui.care.name||'请搜索并选择已有目标'):ui.care.mode==='archive'?'仅保存原件、指标及费用，不建立诊疗事件':'资料会按实际诊疗分组；跨医院资料保留各次诊疗';
    $('uploadCareLock').textContent=ui.careLocked?'本次上传已开始，所有自动子批次使用同一归属。核对页可按资料组改选。':'';
  }
  function setCareTarget(target){
    if(ui.busy||ui.careLocked){toast('请先完成当前上传，再更换本次归属');return false}
    ui.care={mode:target.mode||null,name:target.name||null,topic_id:target.topic_id||null,event_id:target.event_id||null};
    ui.intentKey=null;drawCare();return true;
  }
  entry.addEventListener('click',async e=>{
    const button=e.target.closest('[data-upload-intent]');if(!button||ui.busy||ui.careLocked)return;
    const mode=button.dataset.uploadIntent;
    if(mode!=='existing'){setCareTarget({mode});return}
    const owner=state.user?.id;
    const rows=await window.chooseCareRecords({title:'选择要补充的事件',kind:'topic',kinds:['topic','event'],multiple:false,hint:'可选择大事件或小事件；上传资料会归入选定事件。'});
    if(rows?.length&&state.user?.id===owner){const row=rows[0],topic=row.selection_kind==='topic';setCareTarget({mode:topic?'existing_topic':'existing_event',name:row.title||row.name,[topic?'topic_id':'event_id']:row.id})}
  });
  changeIntent.addEventListener('click',()=>setCareTarget({mode:null}));
  $('uploadCareMode').addEventListener('change',e=>setCareTarget({mode:e.target.value}));
  $('uploadCareName').addEventListener('input',e=>{ui.care.name=e.target.value.trim()||null});
  $('uploadCareChoose').addEventListener('click',async()=>{
    const kind=ui.care.mode==='existing_topic'?'topic':'event';
    const rows=await window.chooseCareRecords({title:kind==='topic'?'补充已有大事件':'补充已有小事件',kind,kinds:[kind],multiple:false,hint:'选择本次上传的归属；各份原件仍独立保存。'});
    if(rows?.length)setCareTarget({mode:kind==='topic'?'existing_topic':'existing_event',name:rows[0].title||rows[0].name,[kind==='topic'?'topic_id':'event_id']:rows[0].id});
  });
  const controls=`<button type="button" class="btn small" data-batch-action="medication">设为同一药品</button><button type="button" class="btn small" data-batch-action="document">设为同一份资料</button><button type="button" class="btn small" data-batch-action="encounter">关联同一次就诊</button><button type="button" class="btn small" data-batch-action="ungroup">取消资料分组</button><button type="button" class="btn small" data-batch-action="unvisit">取消就诊关联</button>`;
  const tray=document.createElement('div');
  tray.id='batchTray';
  tray.innerHTML=`<p class="batch-help">可勾选多张，或用 Ctrl / Shift 多选后右键分组。未分组文件由模型自动整理；同次就诊里的不同单据仍分别保存。</p><div class="batch-toolbar" id="batchToolbar"><button type="button" class="btn small" data-batch-action="all">全选文件</button>${controls}<button type="button" class="btn small" data-batch-action="remove">移除所选</button></div><div id="batchFiles" class="batch-files"></div><p id="batchSelection" role="status"></p>`;
  $('uploadSubmit').before(tray);
  $('fileInput').required=false;
  $('uploadSubmit').textContent='上传并按分组识别';
  const history=document.createElement('section');
  history.className='panel batch-history';
  history.innerHTML='<div class="panel-head"><h3>上传任务</h3><button type="button" id="refreshBatches" class="btn small">刷新任务</button></div><div id="batchHistory"></div>';
  $('view-upload').append(history);
  const menu=document.createElement('div');
  menu.id='batchContext'; menu.className='batch-context hidden'; menu.setAttribute('role','menu'); menu.innerHTML=controls;
  document.body.append(menu);

  function markStatus(message,working=false){
    $('uploadProgress').classList.remove('hidden');
    $('uploadStatus').textContent=message;
    $('uploadStatus').classList.toggle('processing',working);
    $('uploadProgressBar').parentElement.classList.toggle('indeterminate',working);
    $('uploadProgressBar').parentElement.removeAttribute('aria-valuenow');
    $('uploadProgressBar').style.width=working?'35%':'100%';
  }
  function draw(){
    drawCare();
    $('batchFiles').innerHTML=ui.files.map((f,i)=>{
      const group=ui.groups.find(g=>g.ids.includes(f.key)), visit=ui.encounters.find(g=>g.ids.includes(f.key));
      return `<article class="batch-file ${ui.selected.has(f.key)?'selected':''}" tabindex="0" data-file-key="${esc(f.key)}" aria-selected="${ui.selected.has(f.key)}"><label class="batch-check"><input type="checkbox" aria-label="选择 ${esc(f.name)}" ${ui.selected.has(f.key)?'checked':''}></label><div class="batch-thumb">${f.type.startsWith('image/')?`<img src="${esc(f.url)}" alt="">`:'<span>▤</span>'}</div><strong title="${esc(f.name)}">${esc(f.name)}</strong><div class="batch-tags"><span class="pill green">${esc(group?.label||'自动整理')}</span>${visit?`<span class="pill">${esc(visit.label)}</span>`:''}</div><small>${f.uploaded?'已上传':f.error?esc(f.error):'等待上传'}</small></article>`;
    }).join('');
    $('batchSelection').textContent=`${ui.files.length} 个文件 · 已选择 ${ui.selected.size} 个`;
    $('selectedFile').textContent=ui.files.length?`已添加 ${ui.files.length} 个文件，系统将自动分批；点击继续添加`:'点击选择文件';
    $('uploadSubmit').disabled=ui.busy||!ui.files.length;
  }
  function addFiles(files){
    if(ui.busy||!ui.care.mode||((ui.care.mode||'').startsWith('existing_')&&!ui.care.topic_id&&!ui.care.event_id))return;
    if(ui.files.length+files.length>100){
      $('fileInput').value='';
      const message='一次最多选择 100 个文件，请分次上传；当前选择未加入队列';
      markStatus(message);toast(message);return;
    }
    for(const file of files)ui.files.push({key:crypto.randomUUID(),file,name:file.name,type:file.type,url:URL.createObjectURL(file)});
    $('fileInput').value='';draw();
  }
  function selectFile(el,event){
    if(event.target.closest?.('label')&&event.target.type!=='checkbox')return;
    const key=el.dataset.fileKey, index=ui.files.findIndex(f=>f.key===key);
    if(event.shiftKey){for(let i=Math.min(ui.anchor,index);i<=Math.max(ui.anchor,index);i++)ui.selected.add(ui.files[i].key)}
    else if(event.ctrlKey||event.metaKey||event.target.type==='checkbox'){ui.selected.has(key)?ui.selected.delete(key):ui.selected.add(key)}
    else {ui.selected.clear();ui.selected.add(key)}
    ui.anchor=index;draw();
  }
  async function action(kind){
    menu.classList.add('hidden');if(ui.busy)return;
    if(kind==='all'){ui.selected=new Set(ui.files.map(f=>f.key));draw();return}
    const ids=[...ui.selected];if(!ids.length){toast('请先选择文件');return}
    if(kind==='remove'){
      for(const f of ui.files.filter(x=>ui.selected.has(x.key))){
        if(f.uploaded&&ui.batch){ui.batch=await request(`/api/batches/${ui.batch.id}/files/${f.serverId}`,{method:'DELETE'})}
        if(f.url.startsWith('blob:'))URL.revokeObjectURL(f.url);
      }
      ui.files=ui.files.filter(f=>!ui.selected.has(f.key));
      for(const list of [ui.groups,ui.encounters])for(const g of list)g.ids=g.ids.filter(x=>!ids.includes(x));
      ui.selected.clear();
    }else{
      const field=['encounter','unvisit'].includes(kind)?'encounters':'groups';
      // Regrouping a subset removes it from its old group without losing other files.
      ui[field]=ui[field].map(g=>({...g,ids:g.ids.filter(id=>!ids.includes(id))})).filter(g=>g.ids.length);
      if(!['ungroup','unvisit'].includes(kind)){const prefix=kind==='encounter'?'就诊':kind==='medication'?'药品组':'资料组';let n=1;while(ui[field].some(g=>g.label===`${prefix} ${n}`))n++;ui[field].push({id:crypto.randomUUID(),kind,ids,label:`${prefix} ${n}`})}
    }
    ui.groups=ui.groups.filter(g=>g.ids.length);ui.encounters=ui.encounters.filter(g=>g.ids.length);draw();await persistGrouping();
  }
  async function persistGrouping(){
    if(!ui.batch||ui.batch.status!=='receiving')return;
    const convert=g=>({id:g.id,label:g.label,file_ids:g.ids.map(key=>ui.files.find(f=>f.key===key)?.serverId).filter(Boolean)});
    ui.batch=await api.put(`/api/batches/${ui.batch.id}/grouping`,{expected_version:ui.batch.version,
      groups:ui.groups.map(g=>({...convert(g),kind:g.kind})).filter(g=>g.file_ids.length),encounters:ui.encounters.map(convert).filter(g=>g.file_ids.length)});
  }
  async function start(event){
    event?.preventDefault();if(ui.busy||!ui.files.length||!ui.care.mode)return;
    ui.busy=true;draw();markStatus('正在核对分批容量',true);
    try{
      if(ui.care.mode==='existing_topic'&&!ui.care.topic_id||ui.care.mode==='existing_event'&&!ui.care.event_id)throw new Error('请搜索并选择已有事件');
      ui.intentKey??=crypto.randomUUID();
      const limits=await api.get('/api/batches/limits');
      const planned=planUploadBatches(ui.files,ui.groups,ui.encounters,limits,Boolean(ui.batch));
      const total=ui.files.length;let completed=0;
      for(let index=0;index<planned.length;index++){
        const keys=new Set(planned[index]);
        const chunk=ui.files.filter(file=>keys.has(file.key));
        markStatus(`正在上传第 ${index+1} / ${planned.length} 批`,true);
        if(!ui.batch)ui.batch=await api.post('/api/batches',{care_context:{...ui.care,intent_key:ui.intentKey,
          topic_id:ui.care.mode==='existing_topic'?ui.care.topic_id:null,event_id:ui.care.mode==='existing_event'?ui.care.event_id:null}});
        ui.careLocked=true;drawCare();
        for(const f of chunk){
          if(f.uploaded)continue;
          const data=new FormData();data.append('file',f.file);data.append('client_file_id',f.key);
          try{ui.batch=await api.post(`/api/batches/${ui.batch.id}/files`,data);const item=ui.batch.files.find(x=>x.client_file_id===f.key);f.uploaded=true;f.serverId=item.id;f.error=null}
          catch(error){f.error=errorText(error);throw error}
          $('uploadProgressLabel').textContent=`已上传 ${completed+chunk.filter(x=>x.uploaded).length} / ${total}`;
          draw();
        }
        const convert=g=>({id:g.id,label:g.label,file_ids:g.ids.map(key=>ui.files.find(f=>f.key===key).serverId)});
        const groups=ui.groups.filter(g=>g.ids.some(key=>keys.has(key)));
        const encounters=ui.encounters.filter(g=>g.ids.some(key=>keys.has(key)));
        ui.batch=await api.post(`/api/batches/${ui.batch.id}/submit`,{expected_version:ui.batch.version,
          groups:groups.map(g=>({...convert(g),kind:g.kind})),encounters:encounters.map(convert)});
        completed+=chunk.length;
        $('uploadProgressLabel').textContent=`已提交 ${completed} / ${total}`;
        for(const f of chunk)if(f.url.startsWith('blob:'))URL.revokeObjectURL(f.url);
        ui.files=ui.files.filter(f=>!keys.has(f.key));
        ui.groups=ui.groups.filter(g=>!g.ids.some(key=>keys.has(key)));
        ui.encounters=ui.encounters.filter(g=>!g.ids.some(key=>keys.has(key)));
        ui.selected=new Set([...ui.selected].filter(key=>!keys.has(key)));
        ui.batch=null;draw();await refresh();
      }
      markStatus(`${total} 个文件已分 ${planned.length} 批提交，正在识别`,true);
      toast(`已提交 ${planned.length} 个任务，可在上传任务中查看进度`);
      ui.intentKey=null;ui.careLocked=false;ui.care={mode:null,name:null,topic_id:null,event_id:null};
    }catch(error){try{await persistGrouping()}catch{}markStatus(errorText(error));toast(`上传暂停：${errorText(error)}；已上传文件无需重传，刷新后未上传文件需重新选择`)}
    finally{ui.busy=false;draw()}
  }
  function renderPending(){
    const drafts=ui.queue.filter(b=>b.status==='pending_confirmation');
    document.querySelectorAll('[data-batch-review]').forEach(el=>{if(el.closest('#draftList'))el.remove()});
    if(drafts.length){$('draftList').querySelector('.empty')?.remove();$('draftList').insertAdjacentHTML('afterbegin',drafts.map(b=>`<article class="draft-card" tabindex="0" data-batch-review="${b.id}"><span class="pill green">批次核对</span><h4>${b.files.length} 个文件 · ${b.payload?.groups?.length||0} 个资料组</h4><p>核对原件与识别结果，确认后归档到所选事件</p></article>`).join(''))}
    const total=(state.drafts?.length||0)+drafts.length;$('pendingBadge').textContent=total;$('homePendingCount').textContent=total;
  }
  async function refresh(){
    if(!state.user)return;
    const owner=state.user.id;
    try{
      const result=await api.get('/api/batches');if(state.user?.id!==owner)return;ui.queue=result.items;
      $('batchHistory').innerHTML=ui.queue.length?ui.queue.map(b=>`<div class="batch-task"><div><strong>${b.files.length} 个文件</strong><p class="${['queued','preprocessing','extracting'].includes(b.status)?'progress-copy processing':''}">${esc(labels[b.status]||b.status)}</p>${b.error_message?`<p class="form-error">${esc(b.error_message)}</p>`:''}</div><div>${b.status==='pending_confirmation'?`<button class="btn small primary" data-batch-review="${b.id}">核对资料</button>`:b.status==='failed'?`<button class="btn small" data-batch-retry="${b.id}">重试识别</button> <button class="btn small" data-batch-reopen="${b.id}">调整/拆批</button>`:b.status==='receiving'?`<button class="btn small" data-batch-resume="${b.id}">继续上传与分组</button>`:''}</div></div>`).join(''):'<div class="empty">暂无未完成任务</div>';
      for(const b of ui.queue.filter(b=>['receiving','failed','pending_confirmation'].includes(b.status))){
        const row=$('batchHistory').querySelector(`[data-batch-review="${b.id}"], [data-batch-retry="${b.id}"], [data-batch-resume="${b.id}"]`)?.parentElement;
        row?.insertAdjacentHTML('beforeend',` <button type="button" class="btn small" data-batch-cancel="${b.id}">取消任务</button>`);
      }
      renderPending();
      if(!ui.busy){const active=ui.queue.find(b=>['queued','preprocessing','extracting'].includes(b.status));if(active)markStatus(labels[active.status],true);else if(!ui.files.length)markStatus(ui.queue.some(b=>b.status==='pending_confirmation')?'识别完成，请核对资料':'暂无正在识别的任务')}
    }catch(error){if(error.status!==401)toast(errorText(error))}
  }
  function reset(){for(const f of ui.files)if(f.url.startsWith('blob:'))URL.revokeObjectURL(f.url);ui.files=[];ui.groups=[];ui.encounters=[];ui.batch=null;ui.queue=[];ui.selected.clear();ui.care={mode:null,name:null,topic_id:null,event_id:null};ui.intentKey=null;ui.careLocked=false;draw();$('batchHistory').innerHTML='';$('uploadProgress').classList.add('hidden')}
  async function resume(id){
    if(ui.busy||ui.files.length){toast('请先完成当前文件的上传或移除当前选择');return}
    const b=await api.get(`/api/batches/${id}`);ui.batch=b;
    const ctx=b.care_context||{mode:'small'};ui.care={mode:ctx.mode,name:ctx.name,topic_id:ctx.topic_id,event_id:ctx.event_id};ui.intentKey=ctx.intent_key||crypto.randomUUID();ui.careLocked=true;
    ui.files=b.files.map(f=>({key:f.client_file_id,serverId:f.id,name:f.filename,type:f.mime_type,size:f.size_bytes,url:f.content_url,uploaded:true}));
    const map=g=>({...g,ids:g.file_ids.map(id=>b.files.find(f=>f.id===id)?.client_file_id).filter(Boolean)});
    ui.groups=(b.grouping.groups||[]).map(map);ui.encounters=(b.grouping.encounters||[]).map(map);draw();showView('upload');
  }
  $('uploadForm').removeEventListener('submit',handleUpload);
  $('uploadForm').addEventListener('submit',start);
  $('fileInput').addEventListener('change',e=>addFiles(e.target.files));
  $('refreshBatches').addEventListener('click',refresh);
  $('batchFiles').addEventListener('click',e=>{const el=e.target.closest('[data-file-key]');if(el)selectFile(el,e)});
  $('batchFiles').addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.matches('[data-file-key]')){e.preventDefault();selectFile(e.target,{...e,ctrlKey:true,target:e.target})}});
  $('batchFiles').addEventListener('contextmenu',e=>{const el=e.target.closest('[data-file-key]');if(!el)return;e.preventDefault();if(!ui.selected.has(el.dataset.fileKey)){ui.selected=new Set([el.dataset.fileKey]);draw()}menu.style.left=`${Math.min(e.clientX,innerWidth-230)}px`;menu.style.top=`${Math.max(8,Math.min(e.clientY,innerHeight-260))}px`;menu.classList.remove('hidden')});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')menu.classList.add('hidden')});
  document.addEventListener('click',async e=>{try{
    const btn=e.target.closest('[data-batch-action]');if(btn)await action(btn.dataset.batchAction);
    else if(!e.target.closest('#batchContext'))menu.classList.add('hidden');
    const review=e.target.closest('[data-batch-review]');if(review)await window.batchReview.open(review.dataset.batchReview);
    const retry=e.target.closest('[data-batch-retry]');if(retry){await api.post(`/api/batches/${retry.dataset.batchRetry}/retry`,{});await refresh()}
    const res=e.target.closest('[data-batch-resume]');if(res)await resume(res.dataset.batchResume);
    const reopen=e.target.closest('[data-batch-reopen]');if(reopen){await api.post(`/api/batches/${reopen.dataset.batchReopen}/reopen`,{});await refresh();await resume(reopen.dataset.batchReopen)}
    const cancel=e.target.closest('[data-batch-cancel]');if(cancel){const b=ui.queue.find(row=>row.id===cancel.dataset.batchCancel);if(b){await api.post(`/api/batches/${b.id}/cancel`,{expected_version:b.version});if(ui.batch?.id===b.id)reset();await refresh();toast('上传任务已取消，未确认资料没有建立事件')}}
  }catch(error){toast(errorText(error))}});
  const previousLoadDrafts=loadDrafts;
  loadDrafts=async()=>{await previousLoadDrafts();await refresh()};
  $('refreshPending').removeEventListener('click',previousLoadDrafts);$('refreshPending').addEventListener('click',loadDrafts);
  const previousReset=resetAuth;resetAuth=async()=>{reset();return previousReset()};
  ui.timer=setInterval(refresh,4000);
  window.batches={refresh,reset,renderPending,setCareTarget};draw();
})();
