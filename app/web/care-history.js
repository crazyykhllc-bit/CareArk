(() => {
  const root = document.getElementById('careHistory');
  const esc = escapeHtml;
  const care = {tab:'timeline',mode:'list',summary:null,topics:[],editorDocuments:[],
    expanded:new Map(),filters:{},currentEvent:null,currentTopic:null,returnStack:[],editorOriginal:null,
    selectedSuggestions:new Set(),suggestionPage:null,trashPage:null,topicOrder:'asc',request:0,detailRequest:0,
    organizedOwner:null,organizePromise:null};
  const $c = id => document.getElementById(id);
  const text = value => esc(value == null || value === '' ? '未提供' : String(value));
  const labelDate = value => value ? value.replace(/-/g,'.') : '日期待核对';
  const kindOptions = [['other','其他诊疗'],['outpatient','门诊'],['inpatient','住院'],['examination','检查'],['laboratory','检验'],['checkup','体检'],['procedure','操作'],['followup','复诊']];
  const basisOptions = [['unknown','日期待核对'],['visit','就诊日期'],['admission','入院日期'],['examination','检查日期'],['sampling','采样日期'],['procedure','操作日期'],['report','报告日期'],['user_confirmed','人工确认日期']];
  const selectOptions = (options,selected) => options.map(([value,label])=>`<option value="${value}" ${selected===value?'selected':''}>${label}</option>`).join('');
  const returnFocus = target => {
    const selector=target?.focusEvent?`[data-care-event="${target.focusEvent}"]`:
      target?.focusTopic?`[data-care-topic="${target.focusTopic}"]`:null;
    const panel=target?.mode==='detail'?$c('careDetailPanel'):$c('careTimelinePanel');
    (selector?panel.querySelector(selector):$c(care.tab==='topics'?'careTopicsTab':'careTimelineTab'))?.focus({preventScroll:true});
  };
  function queryString(extra={}){
    const params=new URLSearchParams();
    const values={query:$c('careSearch').value.trim(),hospital:$c('careHospital').value,event_kind:$c('careKind').value,
      date_from:$c('careDateFrom').value,date_to:$c('careDateTo').value,topic_id:$c('careTopicFilter').value,
      kind:care.tab==='topics'?'topic':care.tab==='small'?'event':'all',...extra};
    Object.entries(values).forEach(([key,value])=>{if(value!==''&&value!==null&&value!==undefined)params.set(key,String(value))});
    return params.toString();
  }
  function eventCard(event){
    const facts=(event.facts||[]).slice(0,2).map(fact=>`<li>${text(fact.text)}${fact.origin==='user_note'?'<small>个人补充</small>':`<small>来自已核对资料</small>`}</li>`).join('');
    const types=Object.entries(event.document_types||{}).map(([name,count])=>`${text(name)} ${count}`).join(' · ');
    return `<article class="care-event" data-care-event-card="${event.id}" tabindex="-1"><div class="care-event-date"><strong>${text(labelDate(event.date))}</strong><span>${text(event.date_basis_label||'日期待核对')}</span></div><div class="care-event-main"><div class="care-event-heading"><span class="care-kind">${text(event.event_kind_label)}</span><h3>${text(event.title)}</h3></div><p class="care-event-location">${text([event.hospitals?.length?event.hospitals.join(' / '):event.hospital,event.department].filter(Boolean).join(' · ')||'医院待确认')}${event.date_end?` · 至 ${text(labelDate(event.date_end))}`:''}</p>${facts?`<ul class="care-event-facts">${facts}</ul>`:''}<div class="care-event-foot"><span>${event.document_count} 份资料${types?' · '+types:''}</span>${event.topic_ids?.length?`<span>${event.topic_ids.length} 个主题</span>`:''}<button type="button" class="btn small care-card-open" data-care-event="${event.id}" aria-label="查看${text(event.title)}的诊疗经过">查看经过 →</button></div></div></article>`;
  }
  function panels(){
    $c('careTimelinePanel').classList.toggle('hidden',care.mode!=='list');
    $c('careTopicsPanel').classList.add('hidden');
    $c('careDetailPanel').classList.toggle('hidden',care.mode!=='detail');
    $c('careSuggestionPanel').classList.toggle('hidden',care.mode!=='suggestions');
    $c('careTrashPanel').classList.toggle('hidden',care.mode!=='trash');
    $c('careTimelineTab').setAttribute('aria-selected',String(care.tab==='timeline'));
    $c('careTopicsTab').setAttribute('aria-selected',String(care.tab==='topics'));
    $c('careSmallTab')?.setAttribute('aria-selected',String(care.tab==='small'));
  }
  function paintSummary(){
    const summary=care.summary?.summary||{};
    $c('careEventCount').textContent=summary.event_count??'—';
    $c('careHospitalCount').textContent=summary.hospital_count??'—';
    $c('careLatestDate').textContent=labelDate(summary.latest_date);
    $c('careSuggestionCount').textContent=summary.pending_count??0;
    $c('careSuggestionsBtn').classList.toggle('hidden',!summary.pending_count);
  }
  function paintTimeline(){
    const summary=care.summary;if(!summary)return;
    const rows=summary.items||summary.recent||[];
    $c('careTimeline').innerHTML=rows.length?rows.map(hierarchyCard).join(''):'<div class="empty">暂无符合筛选条件的事件，可上传资料建立小事件或大事件。</div>';
    const months=[...(summary.older_months||[])];
    if(summary.undated_count&&!months.some(x=>x.month==='undated'))months.push({month:'undated',count:summary.undated_count});
    $c('careMonths').innerHTML=months.map(({month,count})=>`<section class="care-month"><button type="button" class="care-month-trigger" data-care-month="${text(month)}" aria-expanded="${care.expanded.has(month)}"><span>${care.expanded.has(month)?'−':'+'}　${text(month==='undated'?'日期待核对':month.replace('-', '年'))}${month==='undated'?'':'月'}</span><span>${count} 个事件</span></button><div class="care-month-body" id="care-month-${text(month)}">${care.expanded.get(month)?.items?.map(hierarchyCard).join('')||''}${care.expanded.get(month)?.next_offset!=null?`<button class="btn small" data-care-more="${text(month)}">加载更多</button>`:''}</div></section>`).join('');
    $c('careUndated').innerHTML='';
  }
  function hierarchyCard(item){
    if(item.item_type!=='topic')return eventCard(item).replace('<span class="care-kind">','<span class="care-kind">小事件 · ');
    return `<article class="care-event care-big-event"><div class="care-event-date"><strong>${text(labelDate(item.date_start||item.date||item.latest_date))}</strong><span>${item.date_end?'至 '+text(labelDate(item.date_end)):'诊疗日期范围'}</span></div><div class="care-event-main"><div class="care-event-heading"><span class="care-kind">大事件${item.status==='archived'?' · 已归档':''}</span><h3>${text(item.name||item.title)}</h3></div><p class="care-event-location">${item.event_count||0} 次诊疗 · ${item.hospital_count||0} 家医院 · ${item.document_count||0} 份资料</p>${item.note?`<p>${text(item.note)}</p>`:''}<div class="care-event-foot"><button type="button" class="btn small care-card-open" data-care-topic="${item.id}" aria-label="查看${text(item.name||item.title)}的完整过程">查看完整过程 →</button></div></div></article>`;
  }
  function paintTopics(){
    $c('careTopicList').innerHTML=care.topics.length?care.topics.map(topic=>`<article class="care-topic"><div><span class="care-kind">${topic.status==='archived'?'已归档主题':topic.origin==='auto'?'系统整理':'诊疗主题'}</span><h3>${text(topic.name)}</h3><p>${text(topic.note||'系统会根据已核对的资料和明确的诊疗关联继续整理；你也可以手动调整。')}</p><small>${topic.event_count} 次诊疗 · ${topic.hospital_count} 家医院 · 最近 ${text(labelDate(topic.latest_date))}</small></div><button class="btn small" type="button" data-care-topic="${topic.id}">查看主题 →</button></article>`).join(''):'<div class="empty">还没有足够明确的跨次诊疗关联。系统会在资料核对后自动整理，你也可以自行添加主题。</div>';
  }
  async function loadCareHistory(){
    if(!state.user)return;
    const request=++care.request,owner=state.user.id;
    try{
      let [summary,topics]=await Promise.all([api.get(`/api/care-hierarchy?${queryString({limit:10})}`),api.get('/api/care-topics')]);
      if(!summary.summary)summary=await api.get(`/api/care-history?${queryString()}`);
      if(request!==care.request||owner!==state.user?.id)return;
      care.summary=summary;care.topics=topics.items;
      const hospital=$c('careHospital'),previous=hospital.value;
      hospital.innerHTML='<option value="">全部医院</option>'+(summary.hospitals||[]).map(item=>{const name=typeof item==='string'?item:item.name;return `<option value="${text(name)}">${text(name)}</option>`}).join('');
      hospital.value=previous;
      const topicFilter=$c('careTopicFilter'),selected=topicFilter.value;
      topicFilter.innerHTML='<option value="">全部主题</option>'+care.topics.map(item=>`<option value="${item.id}">${text(item.name)}</option>`).join('');
      topicFilter.value=selected;
      paintSummary();paintTimeline();$c('careTopicList').innerHTML='';panels();
    }catch(error){$c('careTimeline').innerHTML=`<div class="empty">${text(errorText(error))}</div>`}
  }
  async function toggleMonth(month){
    if(care.expanded.has(month)){care.expanded.delete(month);paintTimeline();return}
    const extra={month,older:true};
    try{const page=await api.get(`/api/care-hierarchy?${queryString({...extra,limit:20})}`);
      care.expanded.set(month,page);paintTimeline();
    }catch(error){toast(errorText(error))}
  }
  async function moreMonth(month){
    const current=care.expanded.get(month);if(!current?.next_offset)return;
    const extra={month,older:true};
    try{const page=await api.get(`/api/care-hierarchy?${queryString({...extra,offset:current.next_offset,limit:20})}`);
      care.expanded.set(month,{items:[...current.items,...page.items],next_offset:page.next_offset});paintTimeline();
    }catch(error){toast(errorText(error))}
  }
  function documentRows(documents){
    const groups=new Map();for(const document of documents){const type=document.document_type||'其他资料';if(!groups.has(type))groups.set(type,[]);groups.get(type).push(document)}
    return [...groups].map(([type,items])=>`<details class="care-sources" ${groups.size===1?'open':''}><summary>${text(type)} <span>${items.length} 份</span></summary>${items.map(doc=>`<button class="care-source-row" type="button" data-document="${doc.id}"><span>${text(doc.title)}</span><small>${text(doc.primary_date||'日期待核对')} · ${text(doc.hospital||'医院待确认')}</small><span aria-hidden="true">↗</span></button>`).join('')}</details>`).join('');
  }
  function factRows(items,category){return items?.length?items.map((item,index)=>`<li><span>${text(item.text)}</span>${item.origin==='user_note'?'<small>个人补充</small>':(item.source_refs||[]).map(ref=>`<button class="care-source-link" type="button" data-care-source="${ref.document_id}">查看来源${ref.page?' · 第 '+ref.page+' 页':''}</button>`).join('')}${!item.id?.startsWith('document-')?`<button class="care-source-link" type="button" data-care-remove-fact="${category}:${index}">移除此项</button>`:''}</li>`).join(''):'<li class="care-muted">暂无已核对的事项摘录</li>'}
  async function openEvent(id,restore=false){
    const owner=state.user?.id,request=++care.detailRequest;
    try{if(!restore)care.returnStack.push({mode:care.mode,topicId:care.currentTopic?.id,eventId:care.currentEvent?.id,
      focusEvent:document.activeElement?.dataset?.careEvent,scroll:window.scrollY});
      const event=await api.get(`/api/care-history/events/${id}`);if(owner!==state.user?.id||request!==care.detailRequest)return;care.currentEvent=event;care.mode='detail';panels();
      const topicNames=care.topics.filter(topic=>event.topic_ids.includes(topic.id)).map(item=>item.name);
      $c('careDetailPanel').innerHTML=`<div class="care-panel-head"><button type="button" class="btn small" data-care-back>← 返回</button><div class="care-detail-actions"><button type="button" class="btn small" data-care-edit-event>编辑事件</button><button type="button" class="btn small" data-care-revisions="event">修改记录</button><button type="button" class="btn small danger-outline" data-care-trash-event>移入回收站</button></div></div><div class="care-detail-grid"><article class="card care-detail-primary"><span class="care-kind">${text(event.event_kind_label)}</span><h2>${text(event.title)}</h2><p class="care-detail-meta">${text([event.hospitals?.length?event.hospitals.join(' / '):event.hospital,event.department].filter(Boolean).join(' · ')||'医院待确认')} · ${text(event.date_basis_label)} ${text(labelDate(event.date))}${event.date_end?' 至 '+text(labelDate(event.date_end)):''}</p>${event.date_review_required?'<p class="care-review-hint">日期来源资料已修订，请核对这一日期。</p>':''}${event.document_date_range?`<p class="care-muted">资料日期范围：${text(event.document_date_range.join(' 至 '))}（不作为入院或出院日期）</p>`:''}<section><h3>诊疗经过</h3><ol class="care-fact-list">${factRows(event.milestones,'milestones')}</ol><button class="btn small" type="button" data-care-add-fact="milestones">添加有来源的事项</button></section><section><h3>记录摘录</h3><ol class="care-fact-list">${factRows(event.facts,'summary_facts')}</ol><button class="btn small" type="button" data-care-add-fact="summary_facts">添加原文摘录</button></section>${event.user_note?`<section><h3>个人备注</h3><p>${text(event.user_note)}</p></section>`:''}<section><h3>相关诊疗</h3>${event.related_events?.map(item=>`<button type="button" class="care-source-row" data-care-event="${item.id}"><span>${text(item.title)}</span><small>${text(item.hospital||'医院待确认')} · ${text(labelDate(item.date))}</small><span aria-hidden="true">→</span></button>`).join('')||''}${event.related_documents?.length?documentRows(event.related_documents):(!event.related_events?.length?'<p class="care-muted">暂无关联的其他诊疗资料</p>':'')}</section></article><aside class="care-detail-side"><section class="card"><h3>所属主题</h3><p class="care-muted">${topicNames.length?'已关联 '+topicNames.length+' 个主题':'尚未加入主题'}</p><div class="care-topic-members">${care.topics.map(topic=>`<label><input type="checkbox" data-care-membership="${topic.id}" ${event.topic_ids.includes(topic.id)?'checked':''}><span>${text(topic.name)}</span></label>`).join('')}</div></section><section class="card"><h3>来源资料 · ${event.documents.length} 份</h3>${event.documents.length?documentRows(event.documents):'<p class="care-muted">暂无原始资料</p>'}</section></aside></div>`;
      decorateEvent(event);
      if(!restore){history.pushState({},'',`#care-event/${id}`);window.scrollTo({top:0,behavior:'auto'})}
    }catch(error){toast(errorText(error))}
  }
  function decorateEvent(event){
    care.currentTopic=null;
    const actions=$c('careDetailPanel').querySelector('.care-detail-actions');
    actions.insertAdjacentHTML('afterbegin',`<button class="btn small primary" type="button" data-care-upload="event">补充资料</button>${event.primary_topic_id?'':`<button class="btn small" type="button" data-care-upgrade>升级为大事件</button>`}<button class="btn small" type="button" data-care-choose-parent>${event.primary_topic_id?'调整所属大事件':'加入已有大事件'}</button>`);
    const parent=care.topics.find(t=>t.id===event.primary_topic_id);
    const aside=$c('careDetailPanel').querySelector('.care-detail-side .card');
    if(event.documents?.length)$c('careDetailPanel').querySelector('.care-detail-actions').insertAdjacentHTML('beforeend','<button class="btn small" type="button" data-care-split>拆出部分资料</button>');
    aside.innerHTML=`<h3>所属大事件</h3>${parent?`<button class="care-source-row" type="button" data-care-topic="${parent.id}"><span>${text(parent.name)}</span><span>→</span></button><button class="btn small" type="button" data-care-detach>移出，恢复独立小事件</button>`:'<p class="care-muted">独立小事件；后续可以升级或加入已有大事件。</p>'}${event.topic_ids?.filter(id=>id!==event.primary_topic_id).length?'<p class="care-muted">另有相关诊疗引用，原有关系保留。</p>':''}`;
  }
  async function openTopic(id,restore=false){
    const owner=state.user?.id,request=++care.detailRequest;
    try{if(!restore)care.returnStack.push({mode:care.mode,topicId:care.currentTopic?.id,eventId:care.currentEvent?.id,focusTopic:document.activeElement?.dataset?.careTopic,scroll:window.scrollY});
      care.mode='detail';panels();
      $c('careDetailPanel').innerHTML='<div class="card care-topic-detail" role="status">正在打开完整过程…</div>';
      if(!restore)window.scrollTo({top:0,behavior:'auto'});
      const topic=await api.get(`/api/care-topics/${id}/overview`);if(owner!==state.user?.id||request!==care.detailRequest)return;care.currentTopic=topic;care.currentEvent=null;care.mode='detail';panels();
      const events=topic.events||[],dated=events.filter(x=>x.date).sort((a,b)=>a.date.localeCompare(b.date)),undated=events.filter(x=>!x.date);
      if(care.topicOrder==='desc')dated.reverse();
      const costs=topic.costs_by_currency||[],metrics=topic.metric_summaries||[];
      $c('careDetailPanel').innerHTML=`<div class="care-panel-head"><button class="btn small" type="button" data-care-back>← 返回健康档案</button><div class="care-detail-actions"><button class="btn small primary" type="button" data-care-upload="topic">补充上传</button><button class="btn small" type="button" data-care-attach-documents>关联已有资料</button><button class="btn small" type="button" data-care-attach-events>关联已有诊疗</button><button class="btn small" type="button" data-care-edit-topic>编辑大事件</button><button class="btn small" type="button" data-care-revisions="topic">修改记录</button><button class="btn small danger-outline" type="button" data-care-trash-topic>移入回收站</button></div></div><section class="card care-topic-detail"><span class="care-kind">大事件${topic.status==='archived'?' · 已归档':''}</span><h2>${text(topic.name||topic.title)}</h2>${topic.note?`<p>${text(topic.note)}</p>`:''}<p class="care-muted">${events.length} 次诊疗 · ${topic.hospital_count||0} 家医院 · ${(topic.documents||[]).length} 份资料</p><div class="care-topic-state"><button class="btn small" type="button" data-care-archive-topic>${topic.status==='archived'?'恢复为进行中':'归档大事件'}</button><button class="btn small" type="button" data-care-topic-sort>按日期${care.topicOrder==='asc'?'正序':'倒序'} · 切换</button>${events.length===1?'<button class="btn small" type="button" data-care-downgrade>恢复为小事件</button>':''}<button class="btn small" type="button" data-care-analyze>检查关联建议</button></div><p class="care-muted" id="careTopicAnalysisStatus"></p><h3>诊疗时间线</h3><div class="care-topic-events">${dated.map(eventCard).join('')}${undated.length?`<h3>日期待核对 · ${undated.length} 次诊疗</h3>${undated.map(eventCard).join('')}`:''}${!events.length?'<div class="empty">还没有诊疗资料。可补充上传或关联已有资料。</div>':''}</div></section><div class="care-detail-grid"><section class="card care-topic-detail"><h3>相关指标</h3>${metrics.length?metrics.map(m=>`<button class="care-source-row" type="button" data-metric-detail="${m.metric_id}"><span>${text(m.name)}<small> · ${m.result_count} 次结果</small></span><span>${text(m.latest?.result||'')} ${text(m.unit||'')}</span><span>→</span></button>`).join(''):'<p class="care-muted">暂无已核对的检验结果</p>'}</section><section class="card care-topic-detail"><h3>本事件费用</h3>${costs.length?costs.map(c=>`<p><strong>${text(c.currency)} ${text(c.total)}</strong> · ${c.known_count} 张金额已知${c.unknown_count?' · '+c.unknown_count+' 张待核对':''}</p>`).join(''):'<p class="care-muted">暂无有明确金额的票据</p>'}</section></div><section class="card care-topic-detail"><h3>原始资料索引</h3>${documentRows(topic.documents||[])||'<p class="care-muted">暂无原始资料</p>'}</section>`;
      const references=topic.related_events||[];
      if(references.length)$c('careDetailPanel').insertAdjacentHTML('beforeend',`<section class="card care-topic-detail"><h3>相关诊疗引用 · ${references.length}</h3><p class="care-muted">这些诊疗保留原归属，不计入本大事件的资料、指标和费用。未确定归属的旧关联也保留在这里，可逐项核对。</p>${references.map(event=>`${eventCard(event)}<button class="btn small" type="button" data-care-adopt="${event.id}">纳入本大事件</button>`).join('')}</section>`);
      $c('careDetailPanel').querySelector('.care-detail-actions').insertAdjacentHTML('beforeend','<button class="btn small" type="button" data-care-add-reference>添加相关引用</button>');
      $c('careDetailPanel').querySelector('.care-detail-actions').insertAdjacentHTML('beforeend','<button class="btn small danger-outline" type="button" data-care-trash-group>整组移入回收站</button>');
      if(!restore){history.pushState({},'',`#care-topic/${id}`);window.scrollTo({top:0,behavior:'auto'})}
    }catch(error){
      if(owner!==state.user?.id||request!==care.detailRequest)return;
      $c('careDetailPanel').innerHTML=`<div class="card care-topic-detail"><button class="btn small" type="button" data-care-back>← 返回健康档案</button><p class="form-error" role="alert">${text(errorText(error))}</p></div>`;
    }
  }
  async function hierarchyMutation(action){
    const row=care.currentEvent,t=care.currentTopic;
    try{
      if(action==='parent'){
        const chosen=await chooseCareRecords({title:'选择所属大事件',kind:'topic',multiple:false,hint:'选择后将这次诊疗移入该大事件；原始资料与统计保持原样。'});if(!chosen)return;
        if(row.primary_topic_id&&row.primary_topic_id!==chosen[0].id&&!confirm('将这次诊疗从原大事件移到所选大事件？'))return;
        await api.put(`/api/care-history/events/${row.id}/parent`,{expected_version:row.version,topic_id:chosen[0].id,action:'move'});await loadCareHistory();await openEvent(row.id,true);
      }else if(action==='detach'){
        await api.delete(`/api/care-history/events/${row.id}/parent?expected_version=${row.version}`);await loadCareHistory();await openEvent(row.id,true);
      }else if(action==='documents'){
        const chosen=await chooseCareRecords({title:'关联已有资料',kind:'document',hint:'已归入诊疗的资料将连同整次诊疗移入本大事件，保留各次医院和日期。'});if(!chosen)return;
        if(chosen.some(x=>x.primary_topic_id&&x.primary_topic_id!==t.id)&&!confirm('部分资料已属于其他大事件，是否将对应诊疗移到当前大事件？'))return;
        await api.post(`/api/care-topics/${t.id}/attach-documents`,{document_ids:chosen.map(x=>x.id)});await loadCareHistory();await openTopic(t.id,true);
      }else if(action==='events'||action==='references'){
        const chosen=await chooseCareRecords({title:'关联已有诊疗',kind:'event',hint:'各次诊疗保留原有医院、日期和原件。'});if(!chosen)return;
        if(action==='events'&&chosen.some(x=>x.primary_topic_id&&x.primary_topic_id!==t.id)&&!confirm('部分诊疗已属于其他大事件，是否移到当前大事件？'))return;
        await api.post(`/api/care-topics/${t.id}/attach-events`,{events:chosen.map(event=>({id:event.id,expected_version:event.version})),action:action==='references'?'reference':'move'});
        await loadCareHistory();await openTopic(t.id,true);
      }else if(action==='downgrade'){
        if(!confirm('将唯一一次诊疗恢复为独立小事件？大事件容器将移入回收站，资料与统计保留。'))return;
        const result=await api.post(`/api/care-topics/${t.id}/downgrade`,{expected_version:t.version});await loadCareHistory();await openEvent(result.event_id,true);
      }
      toast('事件归属已更新');
    }catch(error){toast(errorText(error))}
  }
  function showUpgrade(){
    const dialog=$c('careActionDialog');dialog.dataset.action='upgrade';dialog.querySelector('h3').textContent='升级为大事件';dialog.querySelector('form>p').textContent='原小事件将作为第一项诊疗保留；资料、指标和费用不会复制。';$c('careActionName').parentElement.firstChild.textContent='大事件名称';$c('careActionConfirm').textContent='确认升级';
    $c('careActionName').value=care.currentEvent.title;$c('careActionError').textContent='';$c('careActionDialog').showModal();
  }
  function suggestionCard(item){
    const doc=item.kind==='document_event',membership=item.kind==='topic_membership',payload=item.payload;
    return `<article class="care-suggestion" data-care-suggestion-card="${item.id}"><div class="care-suggestion-main"><strong>${doc?'独立诊疗事件建议':membership?'诊疗主题关联待核对':'相关诊疗主题建议'}</strong><p>${doc?'这份已核对资料尚未归入诊疗事件。接受前可以修正标题与日期。':membership?`模型认为“${text(payload.event_title)}”可能属于“${text(payload.topic_name)}”，请核对原文依据。`:'已确认的跨院关联，可由你命名为一个主题。'}</p>${doc?`<div class="care-suggestion-fields"><label>事件名称<input data-care-suggestion-title="${item.id}" value="${text(payload.title||'')}"></label><label>日期<input type="date" data-care-suggestion-date="${item.id}" value="${text(payload.date||'')}"></label><label>日期含义<select data-care-suggestion-basis="${item.id}">${selectOptions(basisOptions,payload.date_basis||(payload.event_kind==='outpatient'?'visit':payload.date?'report':'unknown'))}</select></label></div><small>${text(payload.hospital||'医院待确认')} · 1 份来源资料</small><div><button class="btn small" type="button" data-document="${payload.document_id}">查看来源资料</button></div><label class="care-suggestion-check"><input type="checkbox" data-care-select-suggestion="${item.id}" ${care.selectedSuggestions.has(item.id)?'checked':''}> 已核对，加入批量处理</label>`:membership?`<blockquote>${text(payload.quote)}</blockquote><button class="btn small" type="button" data-document="${payload.document_id}">查看来源资料</button>`:`<label>大事件名称<input data-care-suggestion-name="${item.id}" placeholder="请填写大事件名称"></label><small>关联 ${payload.event_ids?.length||0} 次已确认诊疗；原事件仍各自保留。</small>`}<p class="form-error" role="alert" data-care-suggestion-error="${item.id}"></p></div><div class="care-suggestion-actions"><button class="btn small primary" type="button" data-care-accept="${item.id}" data-version="${item.version}">接受</button><button class="btn small" type="button" data-care-dismiss="${item.id}" data-version="${item.version}">忽略</button></div></article>`;
  }
  function paintSelectedSuggestions(){
    $c('careSelectedCount').textContent=care.selectedSuggestions.size;
    $c('careAcceptSelected').classList.toggle('hidden',care.selectedSuggestions.size===0);
  }
  function suggestionPayload(item){
    const id=item.id,payload={expected_version:item.version};
    if(item.kind==='topic_relation')payload.title=root.querySelector(`[data-care-suggestion-name="${id}"]`)?.value.trim()||null;
    if(item.kind==='document_event'){
      const title=root.querySelector(`[data-care-suggestion-title="${id}"]`)?.value.trim();
      const date=root.querySelector(`[data-care-suggestion-date="${id}"]`)?.value||null;
      const basis=root.querySelector(`[data-care-suggestion-basis="${id}"]`)?.value||'unknown';
      if(!title)throw new Error('请填写事件名称');
      if(title!==item.payload.title)payload.title=title;
      if(date!==(item.payload.date||null))payload.date=date;
      const originalBasis=item.payload.date_basis||(item.payload.event_kind==='outpatient'?'visit':'report');
      if(date&&(basis!==originalBasis||date!==(item.payload.date||null)))payload.date_basis=basis;
    }
    return payload;
  }
  async function showSuggestions(append=false){
    try{const offset=append?care.suggestionPage?.next_offset:0;if(append&&offset==null)return;
      const result=await api.get(`/api/care-suggestions?offset=${offset}&limit=20`);
      const ownership=await api.get('/api/care-hierarchy/ownership-review?limit=20');
      care.ownershipReviews=ownership.items||[];
      const items=append?[...(care.suggestionPage?.items||[]),...result.items]:result.items;
      if(!append)care.selectedSuggestions.clear();
      care.suggestionPage={items,next_offset:result.next_offset};care.mode='suggestions';panels();
      $c('careSuggestionList').innerHTML=items.length?items.map(suggestionCard).join('')+(result.next_offset!=null?'<button class="btn" type="button" data-care-more-suggestions>加载更多建议</button>':''):'<div class="empty">暂无待整理建议</div>';
      if(care.ownershipReviews.length)$c('careSuggestionList').insertAdjacentHTML('afterbegin',`<section><h3>旧关联归属待核对 · ${ownership.total}</h3><p class="care-muted">同一次诊疗曾关联多个主题，请选择一个主要所属大事件；其余关联保留为相关引用。</p>${care.ownershipReviews.map(row=>`<article class="care-suggestion"><div><strong>${text(row.title)}</strong><p>${text(row.hospital||'医院待确认')} · ${text(labelDate(row.date))}</p></div><button class="btn small" type="button" data-care-review-ownership="${row.id}">核对主要归属</button></article>`).join('')}${ownership.next_offset!=null?'<p class="care-muted">本页先展示20项，完成后继续核对下一页。</p>':''}</section>`);
      paintSelectedSuggestions();
      if(!append)window.scrollTo({top:0,behavior:'auto'});
    }catch(error){toast(errorText(error))}
  }
  async function showTrash(append=false){
    try{const offset=append?care.trashPage?.next_offset:0;if(append&&offset==null)return;
      const [events,topics]=await Promise.all([api.get(`/api/care-history/events?deleted=true&limit=20&offset=${offset}`),api.get('/api/care-topics?deleted=true')]);
      const items=append?[...(care.trashPage?.items||[]),...events.items]:events.items;
      care.trashPage={items,next_offset:events.next_offset};
      care.mode='trash';panels();
      $c('careTrashList').innerHTML=[...items.map(item=>`<article class="care-suggestion"><div><strong>${text(item.title)}</strong><p>诊疗事件 · ${text(labelDate(item.date))}</p></div><button class="btn small" type="button" data-care-restore-event="${item.id}" data-version="${item.version}">恢复事件</button></article>`),...topics.items.map(item=>`<article class="care-suggestion"><div><strong>${text(item.name)}</strong><p>诊疗主题</p></div><button class="btn small" type="button" data-care-restore-topic="${item.id}" data-version="${item.version}">恢复主题</button></article>`)].join('')+(events.next_offset!=null?'<button class="btn" type="button" data-care-more-trash>加载更多回收站事件</button>':'')||'<div class="empty">回收站为空</div>';
      if(!append)window.scrollTo({top:0,behavior:'auto'});
    }catch(error){toast(errorText(error))}
  }
  function back(){
    care.detailRequest++;
    const target=care.returnStack.pop();care.mode='list';
    if(target?.mode==='detail'&&target.eventId){history.replaceState({},'',`#care-event/${target.eventId}`);openEvent(target.eventId,true).then(()=>{window.scrollTo({top:target.scroll||0,behavior:'auto'});returnFocus(target)});return}
    if(target?.mode==='detail'&&target.topicId){history.replaceState({},'',`#care-topic/${target.topicId}`);openTopic(target.topicId,true).then(()=>{window.scrollTo({top:target.scroll||0,behavior:'auto'});returnFocus(target)});return}
    history.replaceState({},'','#home');panels();window.scrollTo({top:target?.scroll||0,behavior:'auto'});returnFocus(target);
  }
  function showEditor(kind,existing=null){
    const dialog=$c('careEditDialog');dialog.dataset.kind=kind;dialog.dataset.id=existing?.id||'';dialog.dataset.version=existing?.version||'';
    $c('careEditTitle').textContent=kind==='topic'?(existing?'编辑大事件':'新建大事件'):(existing?'编辑诊疗事件':'添加小事件');
    $c('careTopicFields').classList.toggle('hidden',kind!=='topic');$c('careEventFields').classList.toggle('hidden',kind!=='event');
    $c('careEditName').value=existing?.name||'';$c('careEditNote').value=existing?.note||'';
    for(const field of ['title','hospital','department','date','date_end','user_note'])$c(`careEdit_${field}`).value=existing?.[field]||'';
    $c('careEdit_event_kind').innerHTML=selectOptions(kindOptions,existing?.event_kind||'other');
    $c('careEdit_date_basis').innerHTML=selectOptions(basisOptions,existing?.date_basis||(existing?.date?'user_confirmed':'unknown'));
    care.editorDocuments=[];
    $c('careEditDocuments').innerHTML='';
    $c('careEditSources').classList.toggle('hidden',!!existing);
    $c('careEditSelected').textContent='尚未选择资料，可先创建空事件后补充上传';
    dialog.dataset.autoTitle='false';
    care.editorOriginal=existing?kind==='topic'?{name:existing.name||'',note:existing.note||null}:{
      title:existing.title||'',hospital:existing.hospital||null,department:existing.department||null,
      date:existing.date||null,date_end:existing.date_end||null,date_basis:existing.date_basis||'user_confirmed',
      event_kind:existing.event_kind||'other',user_note:existing.user_note||null}:null;
    $c('careEditError').textContent='';dialog.showModal();
  }
  function selectedEventDocuments(){
    const selected=new Set([...$c('careEditDocuments').selectedOptions].map(option=>option.value));
    return care.editorDocuments.filter(doc=>selected.has(doc.id));
  }
  function suggestEventTitleFromDocuments(){
    const docs=selectedEventDocuments();if(!docs.length)return;
    const hospitalKeys=new Set(docs.map(doc=>hospitalKey(doc.hospital)).filter(Boolean));
    const error=$c('careEditError');
    if(hospitalKeys.size>1){error.textContent='所选资料来自不同医院，不能合成同一次诊疗。请分开建立事件，再放进同一大事件，或点击“改为大事件”。';return}
    error.textContent='';
    if(!$c('careEdit_hospital').value&&docs[0].hospital)$c('careEdit_hospital').value=docs[0].hospital;
    const title=$c('careEdit_title'),dialog=$c('careEditDialog');
    if(title.value&&dialog.dataset.autoTitle!=='true')return;
    const dates=[...new Set(docs.map(doc=>doc.primary_date).filter(Boolean))].sort();
    const dateLabel=dates.length===1?dates[0]:dates.length>1?`${dates[0]} 至 ${dates.at(-1)}`:'';
    title.value=docs.length===1?docs[0].title:
      [docs[0].hospital,dateLabel,'诊疗资料'].filter(Boolean).join(' · ');
    dialog.dataset.autoTitle='true';
  }
  function showFactEditor(category){
    if(!care.currentEvent?.documents?.length)return toast('请先关联原始资料，再添加有来源的事项');
    const dialog=$c('careFactDialog');dialog.dataset.category=category;
    $c('careFactTitle').textContent=category==='milestones'?'添加本次诊疗事项':'添加原文摘录';
    $c('careFactText').value='';$c('careFactDate').value='';$c('careFactBasis').innerHTML=selectOptions(basisOptions,'unknown');
    $c('careFactDocument').innerHTML=care.currentEvent.documents.map(item=>`<option value="${item.id}">${text(item.title)}</option>`).join('');
    $c('careFactError').textContent='';dialog.showModal();
  }
  async function saveFact(event){
    event.preventDefault();const row=care.currentEvent,category=$c('careFactDialog').dataset.category;
    const doc=row.documents.find(item=>item.id===$c('careFactDocument').value);
    const textValue=$c('careFactText').value.trim();if(!doc||!textValue)return;
    const fact={id:crypto.randomUUID(),text:textValue,origin:'source',date:$c('careFactDate').value||null,
      date_basis:$c('careFactBasis').value,source_refs:[{document_id:doc.id,document_version:doc.version,
        source_unit_id:null,page:null,field:'user_confirmed_excerpt',quote:textValue}]};
    const existing=(category==='milestones'?row.milestones:row.facts).filter(item=>!item.id?.startsWith('document-'));
    try{await api.patch(`/api/care-history/events/${row.id}`,{expected_version:row.version,[category]:[...existing,fact]});
      $c('careFactDialog').close();await openEvent(row.id,true);toast('已保存并关联来源');
    }catch(error){$c('careFactError').textContent=errorText(error)}
  }
  async function saveEditor(event){
    event.preventDefault();const dialog=$c('careEditDialog'),kind=dialog.dataset.kind,id=dialog.dataset.id;
    const payload=kind==='topic'?{name:$c('careEditName').value.trim(),note:$c('careEditNote').value||null}:{
      title:$c('careEdit_title').value.trim(),hospital:$c('careEdit_hospital').value||null,
      department:$c('careEdit_department').value||null,date:$c('careEdit_date').value||null,
      date_end:$c('careEdit_date_end').value||null,date_basis:$c('careEdit_date').value?$c('careEdit_date_basis').value:'unknown',
      event_kind:$c('careEdit_event_kind').value,user_note:$c('careEdit_user_note').value||null};
    try{
      if(kind==='event'&&!payload.title){$c('careEditError').textContent='请填写事件名称；选择来源资料后会自动生成可修改的建议名称。';$c('careEdit_title').focus();return}
      if(kind==='event'&&!id&&new Set(selectedEventDocuments().map(doc=>hospitalKey(doc.hospital)).filter(Boolean)).size>1){
        $c('careEditError').textContent='所选资料来自不同医院，不能合成同一次诊疗。请分开建立事件，再放进同一大事件，或点击“改为大事件”。';return}
      if(kind==='event'&&!id&&selectedEventDocuments().some(doc=>doc.encounter_id)){ $c('careEditError').textContent='所选资料已属于一次诊疗，可改为大事件将整次诊疗纳入，或到已有诊疗补充资料。';return }
      let result;
      if(id){
        const changes=Object.fromEntries(Object.entries(payload).filter(([key,value])=>value!==care.editorOriginal?.[key]));
        if(!Object.keys(changes).length){dialog.close();return}
        changes.expected_version=Number(dialog.dataset.version);
        result=await api.patch(kind==='topic'?`/api/care-topics/${id}`:`/api/care-history/events/${id}`,changes);
      }
      else{payload.document_ids=care.editorDocuments.map(doc=>doc.id);result=await api.post(kind==='topic'?'/api/care-topics':'/api/care-history/events',payload)}
      dialog.close();await loadCareHistory();if(kind==='event')await openEvent(result.id,true);else await openTopic(result.id,true);toast('已保存');
    }catch(error){$c('careEditError').textContent=errorText(error)}
  }
  async function showRevisions(kind){
    const id=kind==='event'?care.currentEvent?.id:care.currentTopic?.id;
    if(!id)return;try{const data=await api.get(kind==='event'?`/api/care-history/events/${id}/revisions`:`/api/care-topics/${id}/revisions`);
      $c('careRevisionList').innerHTML=data.items.length?data.items.map(row=>`<div class="care-revision"><strong>${text(row.created_at.slice(0,19).replace('T',' '))}</strong><p>版本 ${row.from_version} → ${row.from_version+1} · ${text(row.changed_fields.join('、'))}</p></div>`).join(''):'<p class="care-muted">暂无修改记录</p>';$c('careRevisionDialog').showModal();
    }catch(error){toast(errorText(error))}
  }
  root.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.dataset.careTab){care.tab=button.dataset.careTab;care.mode='list';care.expanded.clear();await loadCareHistory();return}
    if(button.dataset.careMonth){await toggleMonth(button.dataset.careMonth);return}
    if(button.dataset.careMore){await moreMonth(button.dataset.careMore);return}
    if(button.dataset.careUpgrade!==undefined){showUpgrade();return}
    if(button.dataset.careSplit!==undefined){
      const rows=await chooseCareRecords({title:'拆出当前诊疗中的资料',kind:'document',encounterId:care.currentEvent.id,hint:'只调整这些原件的诊疗归属，不复制报告、趋势点或票据。拆出的诊疗仍保留原大事件归属，可随后再移出或调整。'});if(!rows)return;
      care.splitDocuments=rows.map(x=>x.id);const dialog=$c('careActionDialog');dialog.dataset.action='split';dialog.querySelector('h3').textContent='拆出为一次单独诊疗';dialog.querySelector('form>p').textContent=`已选择 ${rows.length} 份资料。请输入新诊疗名称，原始资料和统计保持不变。`;$c('careActionName').parentElement.firstChild.textContent='诊疗名称';$c('careActionConfirm').textContent='确认拆出';$c('careActionName').value=rows[0].title||care.currentEvent.title;$c('careActionError').textContent='';dialog.showModal();return;
    }
    if(button.dataset.careChooseParent!==undefined){await hierarchyMutation('parent');return}
    if(button.dataset.careDetach!==undefined){await hierarchyMutation('detach');return}
    if(button.dataset.careAttachDocuments!==undefined){await hierarchyMutation('documents');return}
    if(button.dataset.careAttachEvents!==undefined){await hierarchyMutation('events');return}
    if(button.dataset.careAddReference!==undefined){await hierarchyMutation('references');return}
    if(button.dataset.careReviewOwnership){
      const row=care.ownershipReviews.find(x=>x.id===button.dataset.careReviewOwnership);
      const chosen=await chooseCareRecords({title:'核对主要所属大事件',kind:'topic',multiple:false,hint:'选择主要归属后，其余旧关联作为相关引用保留。'});
      if(!chosen)return;
      try{await api.put(`/api/care-history/events/${row.id}/parent`,{expected_version:row.version,topic_id:chosen[0].id});await loadCareHistory();await showSuggestions()}catch(error){toast(errorText(error))}return;
    }
    if(button.dataset.careAdopt){
      const row=care.currentTopic?.related_events?.find(x=>x.id===button.dataset.careAdopt);
      if(!row)return;
      if(row.primary_topic_id&&!confirm('这次诊疗已有所属大事件，是否移入当前大事件？'))return;
      try{await api.post(`/api/care-topics/${care.currentTopic.id}/attach-events`,{events:[{id:row.id,expected_version:row.version}]});await loadCareHistory();await openTopic(care.currentTopic.id,true)}catch(error){toast(errorText(error))}return;
    }
    if(button.dataset.careDowngrade!==undefined){await hierarchyMutation('downgrade');return}
    if(button.dataset.careTrashGroup!==undefined){
      const t=care.currentTopic;
      if(!confirm(`将本大事件、${t.events.length} 次诊疗和 ${t.documents.length} 份原始资料一起移入回收站？相关趋势点、费用和药品来源将按资料回收规则退出统计；相关引用不受影响。`))return;
      try{await api.post(`/api/care-topics/${t.id}/trash-group`,{expected_version:t.version});care.mode='list';await loadCareHistory();await loadDocuments();await loadOverview();toast('整组已移入回收站，可在事件回收站恢复')}catch(error){toast(errorText(error))}return;
    }
    if(button.dataset.careUpload){const row=button.dataset.careUpload==='topic'?care.currentTopic:care.currentEvent;if(window.batches?.setCareTarget){await window.batches.setCareTarget({mode:button.dataset.careUpload==='topic'?'existing_topic':'existing_event',topic_id:button.dataset.careUpload==='topic'?row.id:null,event_id:button.dataset.careUpload==='event'?row.id:null,name:row.name||row.title});showView('upload')}else toast('上传入口正在初始化，请稍后重试');return}
    if(button.dataset.careAnalyze!==undefined){const t=care.currentTopic,status=$c('careTopicAnalysisStatus');status.textContent='正在核查原文关联…';try{const result=await api.post(`/api/care-topics/${t.id}/analyze`,{});if(care.currentTopic?.id===t.id)status.textContent=`${result.linked_events||0} 项明确关联，${result.pending_suggestions||0} 项待核对建议。`}catch(error){status.textContent=errorText(error)}return}
    if(button.dataset.careBack!==undefined){back();return}
    if(button.dataset.careEvent){await openEvent(button.dataset.careEvent);return}
    if(button.dataset.careTopic){await openTopic(button.dataset.careTopic);return}
    if(button.dataset.careSource){openDocument(button.dataset.careSource);return}
    if(button.id==='careAddEvent'){showEditor('event');return}
    if(button.id==='careAddTopic'){showEditor('topic');return}
    if(button.id==='careSuggestionsBtn'){await showSuggestions();return}
    if(button.dataset.careMoreSuggestions!==undefined){await showSuggestions(true);return}
    if(button.id==='careTrashBtn'){await showTrash();return}
    if(button.dataset.careMoreTrash!==undefined){await showTrash(true);return}
    if(button.dataset.careRestoreEvent||button.dataset.careRestoreTopic){
      const eventId=button.dataset.careRestoreEvent,topicId=button.dataset.careRestoreTopic;
      try{await api.post(eventId?`/api/care-history/events/${eventId}/restore`:`/api/care-topics/${topicId}/restore`,{expected_version:Number(button.dataset.version)});await showTrash();await loadCareHistory();toast('已恢复')}catch(error){toast(errorText(error))}return;
    }
    if(button.dataset.careEditEvent!==undefined){showEditor('event',care.currentEvent);return}
    if(button.dataset.careAddFact){showFactEditor(button.dataset.careAddFact);return}
    if(button.dataset.careRemoveFact){const [category,indexText]=button.dataset.careRemoveFact.split(':'),row=care.currentEvent;
      const kept=(category==='milestones'?row.milestones:row.facts).filter(item=>!item.id?.startsWith('document-'));
      kept.splice(Number(indexText),1);
      try{await api.patch(`/api/care-history/events/${row.id}`,{expected_version:row.version,[category]:kept});await openEvent(row.id,true);toast('事项已移除，来源资料仍保留')}catch(error){toast(errorText(error))}return}
    if(button.dataset.careEditTopic!==undefined){showEditor('topic',care.currentTopic);return}
    if(button.dataset.careTopicSort!==undefined){care.topicOrder=care.topicOrder==='asc'?'desc':'asc';const scroll=window.scrollY;await openTopic(care.currentTopic.id,true);window.scrollTo({top:scroll,behavior:'auto'});return}
    if(button.dataset.careRevisions){await showRevisions(button.dataset.careRevisions);return}
    if(button.dataset.careArchiveTopic!==undefined){try{const t=care.currentTopic;await api.patch(`/api/care-topics/${t.id}`,{expected_version:t.version,status:t.status==='archived'?'active':'archived'});await loadCareHistory();await openTopic(t.id,true)}catch(error){toast(errorText(error))}return}
    if(button.dataset.careTrashEvent!==undefined||button.dataset.careTrashTopic!==undefined){
      const isEvent=button.dataset.careTrashEvent!==undefined,row=isEvent?care.currentEvent:care.currentTopic;
      if(!confirm(isEvent?'移除这次诊疗事件？原始资料和统计仍会保留，可从事件回收站恢复。':'移除这个大事件容器？各次诊疗恢复独立展示，原始资料和统计保持原样，可从回收站恢复。'))return;
      try{await api.post(isEvent?`/api/care-history/events/${row.id}/trash`:`/api/care-topics/${row.id}/trash`,{expected_version:row.version});care.mode='list';await loadCareHistory();toast('已移入回收站')}catch(error){toast(errorText(error))}return;
    }
    if(button.dataset.careAccept){const id=button.dataset.careAccept,item=care.suggestionPage?.items.find(row=>row.id===id);
      try{await api.post(`/api/care-suggestions/${id}/accept`,suggestionPayload(item));await showSuggestions();await loadCareHistory();toast('建议已接受')}catch(error){toast(errorText(error))}return}
    if(button.id==='careAcceptSelected'){
      const selected=care.suggestionPage.items.filter(item=>care.selectedSuggestions.has(item.id));let accepted=0;
      for(const item of selected){
        const error=root.querySelector(`[data-care-suggestion-error="${item.id}"]`);
        try{await api.post(`/api/care-suggestions/${item.id}/accept`,suggestionPayload(item));
          care.selectedSuggestions.delete(item.id);care.suggestionPage.items=care.suggestionPage.items.filter(row=>row.id!==item.id);
          root.querySelector(`[data-care-suggestion-card="${item.id}"]`)?.remove();accepted++;
        }catch(failure){if(error)error.textContent=errorText(failure)}
      }
      paintSelectedSuggestions();await loadCareHistory();
      if(accepted)toast(`已接受 ${accepted} 项；失败项保留在当前页面，可修正后重试`);
      if(!care.suggestionPage.items.length)await showSuggestions();return;
    }
    if(button.dataset.careDismiss){try{await api.post(`/api/care-suggestions/${button.dataset.careDismiss}/dismiss`,{expected_version:Number(button.dataset.version)});await showSuggestions();await loadCareHistory();toast('已忽略')}catch(error){toast(errorText(error))}}
  });
  root.addEventListener('change',async event=>{
    const input=event.target;if(!input.dataset.careMembership)return;
    try{const topicId=input.dataset.careMembership,eventId=care.currentEvent.id;
      if(input.checked)await api.put(`/api/care-topics/${topicId}/events/${eventId}`,{});
      else await api.delete(`/api/care-topics/${topicId}/events/${eventId}`);
      await loadCareHistory();await openEvent(eventId,true);toast('所属主题已更新');
    }catch(error){input.checked=!input.checked;toast(errorText(error))}
  });
  root.addEventListener('change',event=>{
    const input=event.target,id=input.dataset.careSelectSuggestion;if(!id)return;
    if(input.checked)care.selectedSuggestions.add(id);else care.selectedSuggestions.delete(id);
    paintSelectedSuggestions();
  });
  for(const id of ['careHospital','careKind','careDateFrom','careDateTo','careTopicFilter'])$c(id).addEventListener('change',()=>{care.expanded.clear();loadCareHistory()});
  $c('careSearch').addEventListener('input',()=>{clearTimeout(care.searchTimer);care.searchTimer=setTimeout(()=>{care.expanded.clear();loadCareHistory()},260)});
  document.body.insertAdjacentHTML('beforeend',`<dialog id="careEditDialog" class="dialog care-edit-dialog"><div class="dialog-head"><div><span class="section-index">健康档案</span><h3 id="careEditTitle">诊疗事件</h3></div><button class="icon-btn" type="button" id="careEditClose" aria-label="关闭">×</button></div><form id="careEditForm"><div id="careTopicFields"><label>大事件名称<input id="careEditName" maxlength="300"></label><label>说明<textarea id="careEditNote" rows="3"></textarea></label></div><div id="careEventFields"><label>事件标题<input id="careEdit_title" maxlength="300"></label><div class="care-form-grid"><label>医院<input id="careEdit_hospital"></label><label>科室<input id="careEdit_department"></label><label>类型<select id="careEdit_event_kind"></select></label><label>日期含义<select id="careEdit_date_basis"></select></label><label>开始日期<input id="careEdit_date" type="date"></label><label>结束日期<input id="careEdit_date_end" type="date"></label></div><label>个人备注<textarea id="careEdit_user_note" rows="3"></textarea></label></div><div id="careEditSources"><span>关联已有资料（可选）</span><p id="careEditSelected" class="care-muted"></p><button type="button" class="btn small" id="careEditPick">搜索并选择资料</button><button type="button" class="btn small" id="careEditAsBig">改为大事件</button><select id="careEditDocuments" multiple hidden></select></div><p id="careEditError" class="form-error" role="alert"></p><div class="care-dialog-actions"><button class="btn" type="button" id="careEditCancel">取消</button><button class="btn primary" type="submit">保存</button></div></form></dialog><dialog id="careFactDialog" class="dialog care-edit-dialog"><div class="dialog-head"><h3 id="careFactTitle">添加来源事项</h3><button class="icon-btn" type="button" id="careFactClose" aria-label="关闭">×</button></div><form id="careFactForm"><label>原文或经核对的事项<textarea id="careFactText" rows="3" required></textarea></label><label>来源资料<select id="careFactDocument" required></select></label><div class="care-form-grid"><label>事项日期<input id="careFactDate" type="date"></label><label>日期含义<select id="careFactBasis"></select></label></div><p>仅记录原件可核对的事实；个人备注请在“编辑事件”中填写。</p><p id="careFactError" class="form-error" role="alert"></p><div class="care-dialog-actions"><button class="btn" type="button" id="careFactCancel">取消</button><button class="btn primary" type="submit">保存事项</button></div></form></dialog><dialog id="careRevisionDialog" class="dialog care-edit-dialog"><div class="dialog-head"><h3>修改记录</h3><button class="icon-btn" type="button" id="careRevisionClose" aria-label="关闭">×</button></div><div id="careRevisionList"></div></dialog>`);
  document.body.insertAdjacentHTML('beforeend',`<dialog id="careActionDialog" class="dialog care-edit-dialog"><header class="dialog-head"><h3>升级为大事件</h3><button class="icon-btn" type="button" data-close-care-action aria-label="关闭">×</button></header><form id="careActionForm"><p>原小事件将作为第一项诊疗保留；资料、指标和费用不会复制。</p><label>大事件名称<input id="careActionName" required maxlength="300"></label><p class="form-error" id="careActionError" role="alert"></p><div class="care-dialog-actions"><button class="btn" type="button" data-close-care-action>取消</button><button class="btn primary" type="submit" id="careActionConfirm">确认升级</button></div></form></dialog>`);
  document.querySelectorAll('[data-close-care-action]').forEach(button=>button.onclick=()=>$c('careActionDialog').close());
  $c('careActionForm').addEventListener('submit',async e=>{e.preventDefault();const row=care.currentEvent,button=$c('careActionConfirm'),split=$c('careActionDialog').dataset.action==='split';button.disabled=true;try{const result=await api.post(`/api/care-history/events/${row.id}/${split?'split-documents':'upgrade'}`,{expected_version:row.version,...(split?{title:$c('careActionName').value.trim(),document_ids:care.splitDocuments}:{name:$c('careActionName').value.trim()})});$c('careActionDialog').close();await loadCareHistory();if(split)await openEvent(result.event_id,true);else await openTopic(result.topic_id||result.id,true);toast(split?'资料已拆出，原始资料与统计保持原样':'已升级，原始资料与统计保持原样')}catch(error){$c('careActionError').textContent=errorText(error)}finally{button.disabled=false}});
  $c('careEditForm').addEventListener('submit',saveEditor);
  $c('careEditPick').onclick=async()=>{const docs=await chooseCareRecords({title:'选择已有资料',kind:'document',selected:care.editorDocuments,hint:'大事件可纳入不同医院的资料；已分组资料保留整次诊疗。'});if(!docs)return;care.editorDocuments=docs;$c('careEditDocuments').innerHTML=docs.map(doc=>`<option value="${doc.id}" selected>${text(doc.title)}</option>`).join('');$c('careEditSelected').textContent=docs.map(doc=>doc.title).join('、');if($c('careEditDialog').dataset.kind==='event')suggestEventTitleFromDocuments()};
  $c('careEditAsBig').onclick=()=>{const dialog=$c('careEditDialog');dialog.dataset.kind='topic';$c('careEditTitle').textContent='新建大事件';$c('careEditName').value=$c('careEdit_title').value;$c('careTopicFields').classList.remove('hidden');$c('careEventFields').classList.add('hidden');$c('careEditError').textContent='';$c('careEditName').focus()};
  $c('careEdit_title').addEventListener('input',()=>{$c('careEditDialog').dataset.autoTitle='false'});
  $c('careFactForm').addEventListener('submit',saveFact);
  for(const [id,dialog] of [['careEditClose','careEditDialog'],['careEditCancel','careEditDialog'],['careFactClose','careFactDialog'],['careFactCancel','careFactDialog'],['careRevisionClose','careRevisionDialog']])$c(id).onclick=()=>$c(dialog).close();
  renderHome=loadCareHistory;
  viewCopy.home=['健康档案','我的诊疗事件','按小事件与大事件整理已确认的诊疗过程'];
  const baseShowView=showView;
  showView=(name,options={})=>{if(name!=='home'&&name!=='detail'&&!options.restoreScroll)care.returnStack=[];
    if(name==='home'&&!options.restoreScroll&&care.mode==='detail'){care.mode='list';care.returnStack=[];panels()}
    baseShowView(name,options);if(name==='home'&&options.refresh!==false)loadCareHistory()};
  const baseResetAuth=resetAuth;
  resetAuth=()=>{care.request++;care.detailRequest++;window.cancelCarePicker?.();for(const id of ['careEditDialog','careActionDialog'])$c(id)?.close();care.editorDocuments=[];care.ownershipReviews=[];care.summary=null;care.topics=[];care.expanded.clear();care.currentEvent=null;care.currentTopic=null;care.returnStack=[];care.editorOriginal=null;care.suggestionPage=null;care.trashPage=null;care.selectedSuggestions.clear();care.organizedOwner=null;care.organizePromise=null;care.mode='list';baseResetAuth()};
  window.loadCareHistory=loadCareHistory;
  window.openCareEvent=id=>openEvent(id,true);
  window.openCareTopic=id=>openTopic(id,true);
})();
