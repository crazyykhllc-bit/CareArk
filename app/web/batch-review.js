/* Human review of grouped sources, extracted fields and visit associations. */
(() => {
  const r={batch:null,payload:null,index:0,source:null,meds:[],dirty:false,busy:false};
  const esc=escapeHtml;
  const types=['挂号单 / 就诊单','门诊病历','检验报告','检查报告','处方 / 用药单','医疗发票 / 收费单','其他医疗资料'];
  const needsManualDetail=group=>(group?.review_items||[]).some(item=>item.startsWith('自动提取失败：'));
  const dialog=document.createElement('dialog');dialog.id='batchReviewDialog';dialog.className='batch-review-dialog';
  dialog.innerHTML=`<header class="dialog-head"><div><span class="section-index">资料核对</span><h3>核对本次资料</h3></div><button type="button" class="icon-btn" id="batchReviewClose" aria-label="关闭批次核对">×</button></header><section id="batchReviewDestination" class="batch-review-destination"></section><p id="batchReviewPartialNotice" class="batch-partial-notice" role="status" hidden></p><div class="batch-review-layout"><aside class="batch-group-list" id="reviewGroups"></aside><section class="batch-source-column"><div class="batch-source-view" id="batchSourceView"></div><div id="batchSourceLinks"></div><div id="batchSourceThumbs" class="batch-source-thumbs"></div></section><section class="batch-fields" id="batchFields"></section></div><footer class="batch-review-footer"><p id="batchReviewError" class="form-error" role="alert"></p><label class="review-ack"><input type="checkbox" id="batchReviewed"><span id="batchReviewedLabel"></span></label><button type="button" class="btn" id="saveBatchReview">保存草稿</button><button type="button" class="btn primary" id="confirmBatchReview">确认整批归档</button></footer>`;
  document.body.append(dialog);
  const closePrompt=document.createElement('dialog');closePrompt.id='batchCloseDialog';closePrompt.className='batch-close-dialog';
  closePrompt.setAttribute('aria-labelledby','batchCloseTitle');
  closePrompt.innerHTML=`<h3 id="batchCloseTitle">要保存本次修改吗？</h3><p>你有未保存的修改。可以保存草稿后关闭，也可以放弃本次修改。</p><p class="form-error" id="batchCloseError" role="alert"></p><div class="batch-close-actions"><button type="button" class="btn" id="batchCloseContinue" autofocus>继续核对</button><button type="button" class="btn danger-outline" id="batchCloseDiscard">放弃修改</button><button type="button" class="btn primary" id="batchCloseSave">保存并关闭</button></div>`;
  document.body.append(closePrompt);
  const current=()=>r.payload?.groups[r.index];
  function dirty(){r.dirty=true;r.payload.reviewed=false;$('batchReviewed').checked=false}
  function input(label,path,value,type='text'){return `<label>${label}<input type="${type}" data-edit="${path}" value="${esc(value??'')}"></label>`}
  function textArea(label,path,value){return `<label class="span-all">${label}<textarea rows="3" data-edit="${path}">${esc(value??'')}</textarea></label>`}
  function markHospitalReview(){
    $('batchFields').querySelectorAll('[data-edit="document.hospital"], [data-edit$=".hospital"]').forEach(input=>{
      input.classList.remove('needs-review');input.setAttribute('aria-invalid','false');input.removeAttribute('title');
    });
  }
  function applyBatchTarget(target){
    r.uniformTarget=target;
    r.careTargets=Object.fromEntries(r.payload.groups.map(g=>[g.id,structuredClone(target)]));
    r.pendingIntent={...target,intent_key:crypto.randomUUID()};
    dirty();render();
  }
  function paintDestination(){
    const defaults=r.batch.care_context||{mode:'small'};
    const targets=r.payload.groups.map(g=>r.careTargets[g.id]||defaults);
    const signature=t=>JSON.stringify([t.mode,t.topic_id||null,t.event_id||null,t.name||null]);
    const mixed=new Set(targets.map(signature)).size>1;
    const target=r.uniformTarget||targets[0]||defaults;
    r.displayTarget=target;
    const mode=target.mode.startsWith('existing_')?'existing':target.mode;
    const labels={small:'新建小事件',new_topic:'新建大事件',existing:'补充已有资料'};
    $('batchReviewDestination').innerHTML=`<div><label class="review-batch-target">本批全部资料归属<select id="reviewCareMode" aria-label="本批全部资料归属">${mixed?'<option value="" selected disabled>请选择统一归属</option>':''}${Object.entries(labels).map(([value,label])=>`<option value="${value}" ${!mixed&&mode===value?'selected':''}>${label}</option>`).join('')}${mode==='archive'?'<option value="archive" selected>仅归档原始资料</option>':''}</select></label><p>更改一次即可应用于本批全部资料；每份单据保留自己的医院和识别结果。</p></div><div class="review-batch-target-options">${mode==='existing'?`<strong title="${esc(target.name||'已选择事件')}">${esc(target.name||'已选择事件')}</strong><button type="button" class="btn small" id="reviewCareChoose">更换事件</button>`:mode==='small'||mode==='new_topic'?`<label>事件名称（可留空）<input id="reviewCareName" maxlength="300" value="${esc(target.name||'')}" placeholder="${mode==='new_topic'?'例如：手术与随访':'例如：一次门诊'}"></label>`:''}<details class="review-destination-menu"><summary>暂不加入事件？</summary><p>只归档到原始资料，不加入健康档案事件。适合暂时无法确定归属的旧报告等资料。</p><button type="button" class="btn small" id="reviewCareArchive">仅归档原始资料</button></details></div>`;
  }
  async function chooseTarget(){
    const rows=await window.chooseCareRecords({title:'选择本批资料归属',kind:'topic',kinds:['topic','event'],multiple:false,hint:'本批全部资料将进入所选事件，各份单据保留自己的医院信息。'});
    if(rows?.length){const row=rows[0],isTopic=row.selection_kind==='topic';applyBatchTarget({mode:isTopic?'existing_topic':'existing_event',name:row.title||row.name,[isTopic?'topic_id':'event_id']:row.id})}
    else paintDestination();
  }
  function blank(kind,ids){return {id:crypto.randomUUID(),kind,source_ids:ids,encounter_id:null,patient_identity:null,
    document:{type:'其他医疗资料',title:kind==='medication'?'待核对药品':'待核对资料',primary_date:null,primary_date_raw:null,hospital:null,department:null,doctor:null,amount:null,key_information:[],parsed_content:null,source_refs:[],patient_scope:'unconfirmed',details:{}},
    lab_results:[],medications:kind==='medication'?[{name:'待核对药品',packages:[]}]:[],evidence:[],review_items:['恢复资料后请核对并填写字段']}}
  async function open(id){
    if(r.dirty&&dialog.open){toast('请先保存当前草稿');return}
    try{const [batch,meds]=await Promise.all([api.get(`/api/batches/${id}/draft`),api.get('/api/medications')]);
      if(r.batch?.id!==batch.id)warmed.clear();
      r.pendingIntent=null;r.batch=batch;r.payload=structuredClone(batch.payload);r.index=0;r.source=null;r.meds=meds.items;r.dirty=false;
      r.careTargets=structuredClone(batch.grouping?.care_targets||{});
      const values=Object.values(r.careTargets);r.uniformTarget=values.length&&values.length===r.payload.groups.length&&values.every(t=>JSON.stringify(t)===JSON.stringify(values[0]))?values[0]:(!batch.care_context&&!values.length?{mode:'small'}:null);
      $('batchReviewError').textContent='';$('batchReviewed').checked=r.payload.reviewed;
      $('batchReviewedLabel').textContent=`我已核对资料，并确认本批全部属于“${state.activeProfileName||'我'}”的档案`;
      render();dialog.showModal();
    }catch(error){toast(errorText(error))}
  }
  function sourceInfo(id){const source=r.batch.sources.find(s=>s.id===id);if(!source)return null;const file=r.batch.files.find(f=>f.attachment_id===source.attachment_id);return {...source,filename:source.label,mime_type:file?.mime_type||'',preview_url:file?.preview_url,thumbnail_url:file?.thumbnail_url,content_url:source.content_url+(source.page_index&&file?.mime_type==='application/pdf'?`#page=${source.page_index}`:'')}}
  const warmed=new Set();
  function warmNearby(id){
    if(!dialog.open||!state.user)return;
    const ids=[...new Set(r.payload.groups.flatMap(g=>g.source_ids))],index=ids.indexOf(id);
    if(index<0)return;
    for(const nextId of ids.slice(index+1,index+3)){
      const source=sourceInfo(nextId),url=source?.preview_url;
      if(!url||warmed.has(url))continue;
      warmed.add(url);const image=new Image();image.decoding='async';image.fetchPriority='low';image.src=url;
    }
  }
  function preview(id){
    r.source=id;const source=sourceInfo(id),view=$('batchSourceView');
    const key=source?(source.preview_url||source.content_url):'';
    if(view.dataset.previewKey!==key){
      view.dataset.previewKey=key;view.innerHTML=attachmentPreview(source);
      const image=view.querySelector('img');
      if(image){const loaded=()=>{if(image.isConnected&&r.source===id)warmNearby(id)};image.addEventListener('load',loaded,{once:true});if(image.complete&&image.naturalWidth)loaded()}
    }
    $('batchSourceLinks').innerHTML=source?`<span>${esc(source.label)}</span> <a href="${esc(source.content_url)}" target="_blank" rel="noopener">查看原件</a>`:'';
  }
  function render(){
    const group=current();paintDestination();
    const reviewItems=[...(r.payload.review_items||[]),...(group?.review_items||[])];
    const incomplete=r.payload.groups.filter(needsManualDetail).length;
    const notice=$('batchReviewPartialNotice');notice.hidden=!incomplete;
    notice.textContent=incomplete?`${incomplete} 份资料的详细字段未能自动提取，原件和转写原文已保留。请打开标记为“需人工补全”的资料，对照原件检查后再归档。`:'';
    $('reviewGroups').innerHTML=`<p>${r.batch.files.length} 个文件 · ${r.payload.groups.length} 份资料</p><div class="review-group-options">`+r.payload.groups.map((g,i)=>`<button type="button" class="review-group ${i===r.index?'active':''} ${needsManualDetail(g)?'needs-manual':''}" data-review-index="${i}" title="${esc(g.document.title)}"><span>${g.kind==='medication'?'药品':'资料'} · ${g.source_ids.length} 张原图</span><strong>${esc(g.document.title)}</strong>${needsManualDetail(g)?'<small>需人工补全</small>':''}</button>`).join('')+`</div><details class="review-issues"><summary>核对提示${reviewItems.length?`（${reviewItems.length} 项）`:''}</summary>${reviewItems.map(t=>`<p>${esc(t)}</p>`).join('')||'<p>请对照原图核对字段</p>'}</details><div id="unassignedSources"></div>`;
    const assigned=new Set(r.payload.groups.flatMap(g=>g.source_ids));const unused=r.batch.sources.filter(s=>!assigned.has(s.id));
    $('unassignedSources').innerHTML=unused.length?`<h4>未归档资料</h4>`+unused.map(s=>`<div class="unused-source"><strong>${esc(s.label)}</strong><p>${esc(r.payload.excluded_sources.find(e=>e.source_id===s.id)?.reason||'需要处置')}</p><button type="button" class="btn small" data-restore-source="${s.id}">恢复这份资料</button></div>`).join(''):'';
    if(!group){$('batchFields').innerHTML='<p>本批没有参与归档的资料；可在左侧恢复资料继续核对</p>';$('batchSourceThumbs').innerHTML='';$('batchSourceThumbs').classList.add('hidden');preview(null);return}
    const ids=group.source_ids;
    if(!ids.includes(r.source))r.source=ids[0];preview(r.source);
    $('batchSourceThumbs').classList.toggle('hidden',ids.length<2);
    $('batchSourceThumbs').innerHTML=ids.length>1?ids.map(id=>{const s=sourceInfo(id);const shared=r.payload.groups.filter(g=>g.source_ids.includes(id)).length>1;return `<div class="review-source"><button type="button" class="${r.source===id?'active':''}" data-show-source="${id}">${s?.mime_type.startsWith('image/')?`<img src="${esc(s.thumbnail_url||s.preview_url||s.content_url)}" loading="lazy" decoding="async" alt="">`:''}<span>${esc(s?.label||id)}</span>${shared?'<em>共享来源</em>':''}</button></div>`}).join(''):'';
    const d=group.document;d.patient_scope??='unconfirmed';d.details??={};
    const medHtml=group.medications.map((m,i)=>`<section class="review-subsection span-all"><h4>药品 ${i+1}</h4><div class="review-field-grid">${[['药名','name'],['通用名','generic_name'],['商品名','brand_name'],['规格','strength'],['剂型','dosage_form'],['厂家','manufacturer'],['批准文号','approval_number'],['给药途径','route']].map(([label,k])=>input(label,`medications.${i}.${k}`,m[k])).join('')}${textArea('包装 / 处方用法原文',`medications.${i}.instructions`,m.instructions)}<label class="span-all">关联已有药品（可选）<select data-edit="medications.${i}.existing_medication_id"><option value="">新建或按完整身份匹配</option>${r.meds.map(x=>`<option value="${x.id}" ${m.existing_medication_id===x.id?'selected':''}>${esc([x.name,x.strength,x.manufacturer].filter(Boolean).join(' · '))}</option>`).join('')}</select></label></div><h4>包装与有效期</h4>${(m.packages||[]).map((p,j)=>`<div class="review-field-grid">${input('批号',`medications.${i}.packages.${j}.batch_number`,p.batch_number)}${input('有效期',`medications.${i}.packages.${j}.expiry_date`,p.expiry_date,'date')}${input('包装数量原文',`medications.${i}.packages.${j}.quantity_raw`,p.quantity_raw)}<button type="button" class="btn small" data-delete-package="${i}:${j}">移除此包装记录</button></div>`).join('')}<button type="button" class="btn small" data-add-package="${i}">添加包装记录</button>${(group.kind==='document'||group.medications.length>1)?` <button type="button" class="btn small" data-delete-med="${i}">移除此药品</button>`:''}</section>`).join('');
    let typedHtml='';
    if(d.type==='检查报告'){
      d.details.exam??={exam_name:null,clinical_info:null,exam_method:null,findings:[],impression:[]};const x=d.details.exam;
      typedHtml=`<section class="review-subsection span-all"><h4>检查报告字段</h4><div class="review-field-grid">${input('检查名称','document.details.exam.exam_name',x.exam_name)}${input('检查方法','document.details.exam.exam_method',x.exam_method)}${textArea('临床信息','document.details.exam.clinical_info',x.clinical_info)}${textArea('检查所见（每行一项）','document.details.exam.findings',(x.findings||[]).join('\n'))}${textArea('检查意见（每行一项）','document.details.exam.impression',(x.impression||[]).join('\n'))}</div></section>`;
    }
    if(d.type==='医疗发票 / 收费单'){
      d.details.receipt??={receipt_number:null,total_amount:null,insurance_amount:null,personal_amount:null,currency:'CNY',settlement_time:null,payment_method:null,line_items:[]};const x=d.details.receipt;
      typedHtml=`<section class="review-subsection span-all"><h4>票据字段</h4><div class="review-field-grid">${input('票据编号','document.details.receipt.receipt_number',x.receipt_number)}${input('总金额','document.details.receipt.total_amount',x.total_amount)}${input('医保支付','document.details.receipt.insurance_amount',x.insurance_amount)}${input('个人支付','document.details.receipt.personal_amount',x.personal_amount)}${input('币种','document.details.receipt.currency',x.currency||'CNY')}${input('结算时间原文','document.details.receipt.settlement_time',x.settlement_time)}${input('支付方式','document.details.receipt.payment_method',x.payment_method)}</div></section>`;
    }
    const labs=group.lab_results||[];
    const labsHtml=d.type==='检验报告'||labs.length?`<section class="review-subsection span-all"><h4>检验项目</h4><div class="review-lab-scroll"><table class="lab-table"><thead><tr><th>项目</th><th>结果</th><th>单位</th><th>参考范围</th><th>提示</th><th></th></tr></thead><tbody>${labs.map((l,i)=>`<tr>${['name','result','unit','reference_range','flag'].map(k=>`<td><input aria-label="${k}" data-edit="lab_results.${i}.${k}" value="${esc(l[k]??'')}"></td>`).join('')}<td><button type="button" data-delete-lab="${i}">×</button></td></tr>`).join('')}</tbody></table></div>${labs.map((l,i)=>`<details class="lab-context"><summary>${esc(l.name||`项目 ${i+1}`)}的匹配条件与时点</summary><div class="review-field-grid">${input('分析物稳定标识',`lab_results.${i}.analyte_key`,l.analyte_key)}${input('标本',`lab_results.${i}.specimen`,l.specimen)}${input('实际条件',`lab_results.${i}.condition`,l.condition)}${input('观察日期',`lab_results.${i}.observed_date`,l.observed_date,'date')}${input('试验时点（分钟）',`lab_results.${i}.timepoint_minutes`,l.timepoint_minutes,'number')}<label>结果类型<select data-edit="lab_results.${i}.result_type"><option value="unknown" ${!l.result_type||l.result_type==='unknown'?'selected':''}>待确认</option><option value="numeric" ${l.result_type==='numeric'?'selected':''}>数值</option><option value="qualitative" ${l.result_type==='qualitative'?'selected':''}>定性</option><option value="comparator" ${l.result_type==='comparator'?'selected':''}>比较符</option></select></label></div></details>`).join('')}<button type="button" class="btn small" id="addReviewLab">添加检验项目</button></section>`:'';
    $('batchFields').innerHTML=`<button class="btn small danger-outline" type="button" id="excludeCurrentDocument">不归档这份资料</button><div class="review-field-grid">${input('资料标题','document.title',d.title)}<label>资料类型<select data-edit="document.type">${types.map(t=>`<option ${d.type===t?'selected':''}>${t}</option>`).join('')}</select></label>${input('主要日期','document.primary_date',d.primary_date,'date')}${input('日期原文','document.primary_date_raw',d.primary_date_raw)}${input('医院','document.hospital',d.hospital)}${input('科室','document.department',d.department)}${input('医生','document.doctor',d.doctor)}${input('金额','document.amount',d.amount)}${input('患者标识原文','patient_identity',group.patient_identity)}${textArea('关键信息（每行一项）','document.key_information',d.key_information.join('\n'))}${textArea(d.type==='检查报告'?'检查所见、结论及其他原文':d.type==='医疗发票 / 收费单'?'收费项目与明细原文':'完整解析原文','document.parsed_content',d.parsed_content)}${typedHtml}${labsHtml}${medHtml}</div><details class="review-subsection"><summary>字段来源依据</summary>${(group.evidence||[]).map(e=>`<button class="evidence-link" type="button" data-show-source="${esc(e.source_id)}">${esc(e.field)}：${esc(e.quote)}</button>`).join('')||'<p>暂无字段级依据，请对照原图核对</p>'}</details>`;
    const labTable=$('batchFields').querySelector('.review-lab-scroll table');
    labTable?.querySelector('thead th:last-child')?.insertAdjacentHTML('beforebegin','<th>核对状态</th>');
    labTable?.querySelectorAll('tbody tr').forEach((row,index)=>{
      const status=labs[index].review_status||'pending';
      row.lastElementChild.insertAdjacentHTML('beforebegin',`<td><select aria-label="${esc(labs[index].name)}核对状态" data-edit="lab_results.${index}.review_status"><option value="pending" ${status==='pending'?'selected':''}>待核对</option><option value="confirmed" ${status==='confirmed'?'selected':''}>已核对</option></select></td>`);
    });
    markHospitalReview();
  }
  function setPath(path,value){
    const root=current();
    const parts=path.split('.');const key=parts.pop();let obj=root;for(const p of parts)obj=obj[p];
    obj[key]=['key_information','findings','impression'].includes(key)?value.split('\n').filter(Boolean):value||null;dirty();markHospitalReview();
  }
  async function save(confirm=false){
    if(r.busy)return; r.busy=true;$('batchReviewError').textContent='';
    $('confirmBatchReview').disabled=$('saveBatchReview').disabled=true;
    try{
      r.payload.reviewed=$('batchReviewed').checked;
      if(confirm&&!r.payload.reviewed)throw new Error('请先完成核对并勾选确认');
      if(r.uniformTarget)r.careTargets=Object.fromEntries(r.payload.groups.map(g=>[g.id,structuredClone(r.uniformTarget)]));
      const activeGroups=new Set(r.payload.groups.map(group=>group.id));
      const saved=await api.put(`/api/batches/${r.batch.id}/draft`,{expected_version:r.batch.version,payload:r.payload,
        ...(r.pendingIntent?{care_context:r.pendingIntent,care_targets:{}}:{care_targets:Object.fromEntries(Object.entries(r.careTargets||{}).filter(([key])=>activeGroups.has(key)))})});
      r.batch=saved;r.payload=structuredClone(saved.payload);r.dirty=false;
      if(r.pendingIntent){r.pendingIntent=null;r.uniformTarget=null;r.careTargets=structuredClone(saved.grouping?.care_targets||{});paintDestination()}
      if(confirm){await api.post(`/api/batches/${r.batch.id}/confirm`,{expected_version:r.batch.version});dialog.close();await Promise.all([loadDocuments(),loadMedications(),loadDrafts(),loadMetrics(),loadOverview()]);toast('整批资料已归档，健康指标与趋势已更新')}
      else toast('草稿已保存，下次可继续核对');
      return true;
    }catch(error){$('batchReviewError').textContent=errorText(error);return false}
    finally{r.busy=false;$('confirmBatchReview').disabled=$('saveBatchReview').disabled=false}
  }
  dialog.addEventListener('input',e=>{
    if(e.target.id==='reviewCareName'){const target={mode:r.displayTarget.mode,name:e.target.value||null};r.uniformTarget=target;r.careTargets=Object.fromEntries(r.payload.groups.map(g=>[g.id,structuredClone(target)]));r.pendingIntent={...target,intent_key:crypto.randomUUID()};r.displayTarget=target;dirty();return}
    const path=e.target.dataset.edit;if(path)setPath(path,e.target.value);
  });
  dialog.addEventListener('change',async e=>{try{
    if(e.target.id==='batchReviewed'){r.dirty=true;r.payload.reviewed=e.target.checked;return}
    if(e.target.id==='reviewCareMode'){if(e.target.value==='existing')await chooseTarget();else applyBatchTarget({mode:e.target.value});return}
    if(e.target.tagName==='SELECT'&&e.target.dataset.edit){setPath(e.target.dataset.edit,e.target.value);render()}
  }catch(error){paintDestination();$('batchReviewError').textContent=errorText(error)}});
  dialog.addEventListener('click',async e=>{try{
    const index=e.target.closest('[data-review-index]');if(index){r.index=Number(index.dataset.reviewIndex);render();return}
    const source=e.target.closest('[data-show-source]');if(source){preview(source.dataset.showSource);return}
    const g=current();const id=e.target.id;
    if(id==='excludeCurrentDocument'){
      if(!confirm('这份资料不参与本次归档？上传的原文件仍保留。'))return;
      const sources=g.source_ids;r.payload.groups=r.payload.groups.filter(item=>item!==g);
      for(const source_id of sources)if(!r.payload.groups.some(item=>item.source_ids.includes(source_id)))r.payload.excluded_sources.push({source_id,reason:'用户选择不归档这份资料'});
      r.index=0;dirty();render();return;
    }
    if(id==='reviewCareArchive'){applyBatchTarget({mode:'archive'});return}
    if(id==='reviewCareChoose')await chooseTarget();
    if(e.target.dataset.restoreSource){const sid=e.target.dataset.restoreSource;r.payload.excluded_sources=r.payload.excluded_sources.filter(x=>x.source_id!==sid);r.payload.groups.push(blank('document',[sid]));r.index=r.payload.groups.length-1;dirty();render()}

    if(e.target.dataset.deleteMed!==undefined){g.medications.splice(Number(e.target.dataset.deleteMed),1);dirty();render()}
    if(e.target.dataset.addPackage!==undefined){g.medications[Number(e.target.dataset.addPackage)].packages.push({batch_number:null,expiry_date:null,quantity_raw:null,source_ids:[...g.source_ids]});dirty();render()}
    if(e.target.dataset.deletePackage!==undefined){const [i,j]=e.target.dataset.deletePackage.split(':').map(Number);g.medications[i].packages.splice(j,1);dirty();render()}
    if(id==='addReviewLab'){g.lab_results.push({name:'待核对项目',result:null,unit:null,reference_range:null,flag:null,source_ref:null,analyte_key:null,specimen:null,condition:null,observed_date:null,timepoint_minutes:null,test_session_key:null,result_type:'unknown',review_status:'pending'});dirty();render()}
    if(e.target.dataset.deleteLab!==undefined){g.lab_results.splice(Number(e.target.dataset.deleteLab),1);dirty();render()}

  }catch(error){$('batchReviewError').textContent=errorText(error)}});
  $('saveBatchReview').addEventListener('click',()=>save());$('confirmBatchReview').addEventListener('click',()=>save(true));
  function finishClose(){closePrompt.close();r.dirty=false;r.pendingIntent=null;dialog.close()}
  function close(){if(r.busy)return;if(r.dirty){$('batchCloseError').textContent='';if(!closePrompt.open)closePrompt.showModal();return}dialog.close()}
  $('batchCloseContinue').addEventListener('click',()=>{if(!r.busy)closePrompt.close()});
  $('batchCloseDiscard').addEventListener('click',()=>{if(!r.busy)finishClose()});
  $('batchCloseSave').addEventListener('click',async()=>{
    if(r.busy)return;
    const buttons=closePrompt.querySelectorAll('button');buttons.forEach(button=>button.disabled=true);
    $('batchCloseError').textContent='';
    try{if(await save())finishClose();else $('batchCloseError').textContent=$('batchReviewError').textContent||'保存失败，请重试或继续核对'}
    finally{buttons.forEach(button=>button.disabled=false)}
  });
  closePrompt.addEventListener('cancel',e=>{if(r.busy)e.preventDefault()});
  $('batchReviewClose').addEventListener('click',close);dialog.addEventListener('cancel',e=>{e.preventDefault();close()});
  window.batchReview={open};
})();
