(() => {
  const esc=escapeHtml;
  state.encounters=[];
  state.archiveExpandedMonths=new Set();
  state.archiveCollection=null;
  loadDocuments=async()=>{try{const owner=state.user?.id;const visits=await api.get('/api/encounters');const docs=[];let cursor=0;do{const page=await api.get(`/api/documents?limit=100&cursor=${cursor}`);docs.push(...page.items);cursor=page.next_cursor??null}while(cursor!==null);if(owner!==state.user?.id)return;state.encounters=visits.items;state.documents=docs;renderHome();if(state.archiveTrashMode&&window.loadTrashDocuments)await window.loadTrashDocuments();else renderArchive()}catch(error){if(error.status===401)return resetAuth();toast(errorText(error))}};
  function archiveDateLabel(date){if(!date)return '日期待确认';const parts=date.split('-');return parts.length===3?`${parts[0]}年${Number(parts[1])}月${Number(parts[2])}日`:date}
  function archiveDateGroups(docs){
    const grouped=new Map();
    for(const doc of docs){const date=doc.primary_date||'';if(!grouped.has(date))grouped.set(date,[]);grouped.get(date).push(doc)}
    return [...grouped].map(([date,items])=>`<section class="archive-date-group"><div class="archive-date-heading"><strong>${esc(archiveDateLabel(date))}</strong><span>${items.length} 份资料</span></div><div class="archive-date-items">${items.map(documentCard).join('')}</div></section>`).join('');
  }
  renderArchive=()=>{
    if(state.archiveTrashMode)return;
    const collection=state.archiveCollection;
    const collectionLabel=collection?.kind==='year'?`${collection.value}年全部资料`:collection?.kind==='type'?`${collection.value} · 全部资料`:'';
    $('archiveCollection').classList.toggle('hidden',!collection);
    $('archiveCollectionLabel').textContent=collectionLabel;
    const query=$('archiveSearch').value.trim().toLocaleLowerCase();
    const docs=state.documents.filter(doc=>(!collection||(collection.kind==='year'?doc.primary_date?.slice(0,4)===collection.value:doc.document_type===collection.value))&&
      (!query||[doc.title,doc.hospital,doc.department,doc.document_type,doc.primary_date,...(doc.key_information||[])].filter(Boolean).join(' ').toLocaleLowerCase().includes(query)))
      .sort((a,b)=>(b.primary_date||'').localeCompare(a.primary_date||'')||(b.created_at||'').localeCompare(a.created_at||'')||String(b.id).localeCompare(String(a.id)));
    $('archiveStatus').textContent=collection?`${collectionLabel} · ${docs.length} 份${query?'符合搜索':''}资料，全部展开`:query?`找到 ${docs.length} 份资料，搜索结果全部展开`:`共 ${docs.length} 份资料 · 最近 ${Math.min(10,docs.length)} 份展开，较早资料按月份收起`;
    if(!docs.length){$('archiveList').innerHTML=`<div class="empty">${query?'没有符合搜索条件的资料':collection?'这个合集暂无资料':'暂无已归档资料'}</div>`;return}
    if(query||collection){$('archiveList').innerHTML=archiveDateGroups(docs);return}
    const recent=docs.slice(0,10),older=docs.slice(10),months=new Map();
    for(const doc of older){const month=doc.primary_date?.slice(0,7)||'';if(!months.has(month))months.set(month,[]);months.get(month).push(doc)}
    $('archiveList').innerHTML=`<div class="archive-recent">${archiveDateGroups(recent)}</div>${[...months].map(([month,items])=>{
      const dates=new Set(items.map(item=>item.primary_date||''));
      const label=month?`${month.slice(0,4)}年${Number(month.slice(5))}月`:'日期待确认';
      return `<details class="archive-month" data-archive-month="${esc(month)}" ${state.archiveExpandedMonths.has(month)?'open':''}><summary><span class="archive-month-icon" aria-hidden="true"></span><strong>${esc(label)}</strong><span class="archive-month-count">${dates.size} 个日期 · ${items.length} 份资料</span></summary><div class="archive-month-body">${archiveDateGroups(items)}</div></details>`;
    }).join('')}`;
  };
  $('archiveList').addEventListener('toggle',event=>{const month=event.target.closest('details[data-archive-month]');if(!month||event.target!==month)return;const key=month.dataset.archiveMonth;if(month.open)state.archiveExpandedMonths.add(key);else state.archiveExpandedMonths.delete(key)},true);
  const oldDetail=renderDocumentDetail;
  renderDocumentDetail=()=>{
    oldDetail();const doc=state.currentDocument;if(!doc)return;
    $('documentVisitLink')?.remove();
    const visits=state.encounters||[];
    const linked=visits.filter(v=>(v.related_document_ids||[]).includes(doc.id));
    const sameHospital=visits.filter(v=>v.id===doc.encounter_id||!hospitalKey(doc.hospital)||!hospitalKey(v.hospital)||hospitalKey(doc.hospital)===hospitalKey(v.hospital));
    const available=visits.filter(v=>v.id!==doc.encounter_id&&!linked.some(item=>item.id===v.id));
    const label=v=>esc([v.date,v.hospital,v.title].filter(Boolean).join(' · '));
    const box=document.createElement('div');box.id='documentVisitLink';box.className='document-visit-links';
    box.innerHTML=`<div class="document-visit-link"><label>同一次就诊（同院）<select id="documentVisitSelect"><option value="">独立资料</option>${sameHospital.map(v=>`<option value="${v.id}" ${v.id===doc.encounter_id?'selected':''}>${label(v)}</option>`).join('')}</select></label><button type="button" class="btn small" id="saveDocumentVisit">保存就诊</button></div><div class="document-visit-link"><label>相关诊疗（可跨医院）<select id="relatedVisitSelect"><option value="">选择相关就诊或手术</option>${available.map(v=>`<option value="${v.id}">${label(v)}</option>`).join('')}</select></label><button type="button" class="btn small" id="addRelatedVisit">添加关联</button></div>${linked.length?`<div class="related-visit-list">${linked.map(v=>`<span>${label(v)} <button type="button" data-unlink-visit="${v.id}" aria-label="取消与${label(v)}的相关诊疗关联">×</button></span>`).join('')}</div>`:''}<p class="document-visit-hint">相关诊疗只建立联系，不改变这份资料的医院、日期或所属就诊。</p>`;
    $('detailMeta').after(box);
    $('saveDocumentVisit').onclick=async()=>{try{const result=await api.patch(`/api/documents/${doc.id}/encounter`,{expected_version:doc.version,encounter_id:$('documentVisitSelect').value||null});doc.version=result.version;doc.encounter_id=result.encounter_id;await loadDocuments();toast('就诊关联已保存')}catch(error){toast(errorText(error))}};
    $('addRelatedVisit').onclick=async()=>{const id=$('relatedVisitSelect').value;if(!id)return toast('请选择相关就诊');try{await api.put(`/api/documents/${doc.id}/related-encounters/${id}`,{});await loadDocuments();renderDocumentDetail();toast('相关诊疗已关联')}catch(error){toast(errorText(error))}};
    box.querySelectorAll('[data-unlink-visit]').forEach(button=>button.onclick=async()=>{try{await api.delete(`/api/documents/${doc.id}/related-encounters/${button.dataset.unlinkVisit}`);await loadDocuments();renderDocumentDetail();toast('相关诊疗关联已取消')}catch(error){toast(errorText(error))}});
  };
})();
