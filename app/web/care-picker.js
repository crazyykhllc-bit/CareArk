/* Independent, paginated selection of archived care records. */
(() => {
  let active=null,request=0;
  const dialog=document.createElement('dialog');dialog.id='carePickerDialog';dialog.className='dialog care-edit-dialog care-picker-dialog';
  dialog.innerHTML=`<header class="dialog-head"><h3 id="carePickerTitle">选择已有资料</h3><button type="button" class="icon-btn" id="carePickerClose" aria-label="关闭">×</button></header><div class="care-picker-body"><p id="carePickerHint" class="care-muted"></p><div class="care-picker-search"><label>类型<select id="carePickerKind"><option value="document">原始资料</option><option value="event">诊疗事件</option><option value="topic">大事件</option></select></label><label>搜索<input type="search" id="carePickerSearch" placeholder="输入名称或医院"></label></div><p id="carePickerStatus" role="status"></p><div id="carePickerResults"></div><button class="btn small hidden" id="carePickerMore" type="button">加载更多</button><p class="form-error" id="carePickerError" role="alert"></p></div><footer class="care-picker-actions"><button class="btn" type="button" id="carePickerCancel">取消</button><button class="btn primary" type="button" id="carePickerConfirm">确认选择</button></footer>`;
  document.body.append(dialog);
  const el=id=>document.getElementById(id),esc=escapeHtml;
  function finish(value){const task=active;active=null;request++;dialog.close();task?.resolve(value)}
  window.cancelCarePicker=()=>finish(null);
  function paint(){
    if(!active)return;
    el('carePickerResults').innerHTML=active.items.map(row=>`<label class="care-picker-row"><input type="${active.multiple?'checkbox':'radio'}" name="carePickerChoice" value="${esc(row.id)}" ${active.selected.has(row.id)?'checked':''}><span><strong>${esc(row.title||row.name||'未命名')}</strong><small>${esc([row.date||row.primary_date,row.hospital].filter(Boolean).join(' · ')||'日期或医院待核对')}</small><small>${esc(row.primary_topic_name?'所属大事件：'+row.primary_topic_name:row.encounter_id?'已归入一次诊疗；关联时保留整次诊疗':'独立记录')}</small></span></label>`).join('')||'<div class="empty">没有找到符合条件的记录</div>';
    el('carePickerStatus').textContent=`找到 ${active.total} 项 · 已选择 ${active.selected.size} 项`;
    el('carePickerMore').classList.toggle('hidden',active.next==null);
  }
  async function load(append=false){
    if(!active)return;
    const task=active,seq=++request,kind=el('carePickerKind').value;el('carePickerError').textContent='';
    if(!append){task.items=[];el('carePickerResults').innerHTML='<div class="empty">正在读取…</div>';el('carePickerMore').classList.add('hidden')}
    const params=new URLSearchParams({kind,query:el('carePickerSearch').value.trim(),offset:append?task.next||0:0,limit:20});
    if(task.encounterId)params.set('encounter_id',task.encounterId);
    try{const result=await api.get('/api/care-hierarchy/search?'+params);if(active!==task||seq!==request)return;if(task.owner!==state.user?.id){finish(null);return}
      const rows=result.items.map(row=>({...row,selection_kind:kind}));
      task.items=append?[...task.items,...rows]:rows;task.total=result.total??task.items.length;task.next=result.next_offset;paint();
    }catch(error){if(active===task&&seq===request)el('carePickerError').textContent=errorText(error)}
  }
  el('carePickerResults').addEventListener('change',e=>{if(!active||e.target.tagName!=='INPUT')return;const row=active.items.find(item=>item.id===e.target.value);if(!row)return;
    if(!active.multiple)active.selected.clear();e.target.checked?active.selected.set(row.id,row):active.selected.delete(row.id);paint()});
  let timer;el('carePickerSearch').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>load(),250)});
  el('carePickerKind').addEventListener('change',()=>load());el('carePickerMore').onclick=()=>load(true);
  for(const id of ['carePickerClose','carePickerCancel'])el(id).onclick=()=>finish(null);
  dialog.addEventListener('cancel',e=>{e.preventDefault();finish(null)});
  el('carePickerConfirm').onclick=()=>{if(!active?.selected.size){el('carePickerError').textContent='请先选择一项';return}finish([...active.selected.values()])};
  window.chooseCareRecords=({title='选择已有资料',kind='document',kinds=[kind],multiple=true,hint='',selected=[],encounterId=null}={})=>{
    if(active)finish(null);
    return new Promise(resolve=>{active={resolve,owner:state.user?.id,encounterId,multiple,items:[],selected:new Map(selected.map(row=>[row.id,row])),total:0,next:null};
      el('carePickerTitle').textContent=title;el('carePickerHint').textContent=hint;
      for(const option of el('carePickerKind').options)option.hidden=!kinds.includes(option.value);
      el('carePickerKind').value=kind;el('carePickerKind').closest('label').classList.toggle('hidden',kinds.length===1);
      el('carePickerSearch').value='';el('carePickerResults').innerHTML='<div class="empty">正在读取…</div>';el('carePickerError').textContent='';dialog.showModal();load();
    });
  };
})();
