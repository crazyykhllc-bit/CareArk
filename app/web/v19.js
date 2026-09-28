(() => {
  const esc = escapeHtml;
  const validViews = new Set(['overview','home','upload','archive','drugs','costs','admin']);
  const legacyViews = {metrics:'overview',ogtt:'overview',pending:'upload'};
  const requestedHash = location.hash;
  const baseShowView = showView;
  const baseOpenDocument = openDocument;
  const baseReturnFromDetail = returnFromDetail;
  const baseEnterApp = enterApp;
  viewCopy['metric-detail']=['健康指标','指标详情','完整趋势、历史结果与资料来源'];
  viewCopy['medication-detail']=['药品资料','药品详情','药品信息、包装原图与来源记录'];

  function pushRoute(hash, replace=false) {
    if (location.hash === hash) return;
    history[replace ? 'replaceState' : 'pushState']({}, '', hash);
  }

  showView = (name, options={}) => {
    name=legacyViews[name]||name;
    if(name==='archive'&&!state.routeApplying&&!options.restoreScroll){state.archiveCollection=null;$('archiveSearch').value=''}
    baseShowView(name, options);
    if(name==='archive'&&!state.archiveTrashMode)renderArchive();
    if(name==='metric-detail')document.querySelector('[data-view="overview"]')?.classList.add('active');
    if(name==='medication-detail')document.querySelector('[data-view="drugs"]')?.classList.add('active');
    if (!state.routeBooting && !state.routeApplying && name !== 'detail' && name !== 'metric-detail' && name !== 'medication-detail') pushRoute(`#${name}`);
  };
  openDocument = async id => {
    const fromMetric=state.currentView==='metric-detail';
    const fromMedication=state.currentView==='medication-detail';
    state.routeOpening = true;
    try { await baseOpenDocument(id); }
    finally { state.routeOpening = false; }
    if(fromMetric&&state.currentDocument?.id===id){state.detailReturnView='metric-detail';$('detailBack').textContent='← 返回指标详情';$('detailBack').setAttribute('aria-label','返回指标详情')}
    if(fromMedication&&state.currentDocument?.id===id){state.detailReturnView='medication-detail';$('detailBack').textContent='← 返回药品详情';$('detailBack').setAttribute('aria-label','返回药品详情')}
    if (!state.routeApplying && state.currentDocument?.id === id) {
      state.detailRoutePushed = true;
      pushRoute(`#document/${id}`);
    }
  };
  returnFromDetail = () => {
    if (state.detailRoutePushed && location.hash.startsWith('#document/')) {
      state.detailRoutePushed = false;
      history.back();
    } else baseReturnFromDetail();
  };
  enterApp = async () => {
    state.routeBooting = true;
    await baseEnterApp();
    state.routeBooting = false;
    await applyRoute(requestedHash || '#overview', true);
  };

  async function applyRoute(hash, initial=false) {
    if (!state.user) return;
    state.routeApplying = true;
    try {
      const match = hash.match(/^#document\/([0-9a-f-]+)$/i);
      if (match) {
        state.detailRoutePushed = !initial;
        await baseOpenDocument(match[1]);
        return;
      }
      const careEventMatch=hash.match(/^#care-event\/([0-9a-f-]+)$/i);
      if(careEventMatch){baseShowView('home',{refresh:false,restoreScroll:!initial});await window.openCareEvent?.(careEventMatch[1]);return}
      const careTopicMatch=hash.match(/^#care-topic\/([0-9a-f-]+)$/i);
      if(careTopicMatch){baseShowView('home',{refresh:false,restoreScroll:!initial});await window.openCareTopic?.(careTopicMatch[1]);return}
      const metricMatch=hash.match(/^#metric\/([0-9a-z-]+)$/i);
      if(metricMatch){await openMetricDetail(metricMatch[1],true);return}
      const medicationMatch=hash.match(/^#medication\/([0-9a-z-]+)$/i);
      if(medicationMatch){await openMedicationDetail(medicationMatch[1],true);return}
      const collectionMatch=hash.match(/^#archive\/(year|type)\/(.+)$/);
      if(collectionMatch){
        let value='';try{value=decodeURIComponent(collectionMatch[2])}catch(_error){}
        if(value&&(collectionMatch[1]!=='year'||/^\d{4}$/.test(value))&&value.length<=64){
          state.archiveCollection={kind:collectionMatch[1],value};$('archiveSearch').value='';
          state.archiveTrashMode=false;$('archiveTrashToggle').textContent='回收站';
          baseShowView('archive',{refresh:false,restoreScroll:!initial});renderArchive();return;
        }
      }
      const view = legacyViews[hash.replace(/^#/, '')]||hash.replace(/^#/, '');
      if(view==='archive'){state.archiveCollection=null;$('archiveSearch').value=''}
      baseShowView(validViews.has(view) ? view : 'overview', {
        restoreScroll: !initial,
        refresh: !(initial && view === 'overview'),
      });
      if(view==='archive'&&!state.archiveTrashMode)renderArchive();
    } finally { state.routeApplying = false; }
  }
  window.addEventListener('popstate', () => applyRoute(location.hash || '#overview'));

  function loading(target, message='正在读取…') { if ($(target)) $(target).innerHTML=`<div class="empty">${esc(message)}</div>`; }
  function sameOwner(ownerId) { return Boolean(ownerId && state.user?.id === ownerId); }

  function openArchiveCollection(kind,value){
    state.archiveCollection={kind,value};$('archiveSearch').value='';
    state.archiveTrashMode=false;$('archiveTrashToggle').textContent='回收站';
    baseShowView('archive');renderArchive();
    pushRoute(`#archive/${kind}/${encodeURIComponent(value)}`);
  }

  window.loadOverview = async function loadOverview() {
    if (!state.user) return;
    const owner=state.user.id;
    try {
      const [overview, costs] = await Promise.all([api.get('/api/overview'), api.get('/api/costs/summary')]);
      if(!sameOwner(owner))return;
      state.overview = overview; state.costSummary = costs;
      renderOverview(); renderDashboardMetricManager();
    } catch (error) { if(sameOwner(owner))toast(errorText(error)); }
  };

  function renderOverview() {
    if (!state.overview) return;
    const data=state.overview,documents=data.documents||{total:0,dated:0,undated:0};
    renderOverviewCosts(state.costSummary);
    $('overviewDocuments').textContent=documents.total;
    $('overviewDocumentFoot').textContent=`${documents.dated} 份有日期 · ${documents.undated} 份日期待确认`;
    $('overviewHospitals').textContent=data.hospitals??0;
    $('overviewLatest').textContent=data.latest_date||'—';
    const ownership=data.ownership||{},unconfirmed=ownership.unconfirmed_documents||0;
    $('overviewOwnership').classList.toggle('hidden',unconfirmed===0);
    $('ownershipSummary').textContent=`${unconfirmed} 份资料归属待确认 · ${ownership.unconfirmed_lab_results||0} 条检验结果尚未进入曲线`;
    const metrics=data.metrics||[];
    $('overviewMetrics').innerHTML=metrics.length?metrics.map(item=>`<article class="health-metric-row"><span class="metric-name"><strong>${esc(item.name)}</strong><small>${esc(item.group)}${item.unit?` · ${esc(item.unit)}`:''}</small></span><span class="metric-latest">${esc(item.latest_result||'暂无结果')}</span><span>${esc(item.latest_date||'—')}</span><span>${item.record_count||0} 次</span><span class="metric-spark">${item.record_type==='qualitative'?'<span class="spark-empty">文字结果</span>':overviewSparkline(item.trend_series,item.name)}</span><span class="metric-actions">${item.manual_entry_allowed?`<button class="btn tiny" type="button" data-metric-record="${item.id}">记录</button>`:''}<button class="btn tiny" type="button" data-metric-detail="${item.id}">详情</button><button class="btn tiny" type="button" data-dashboard-id="${item.id}" data-dashboard-next="false" aria-label="将 ${esc(item.name)} 移出首页">移出首页</button></span></article>`).join(''):'<div class="empty compact-empty">首页暂无显示中的指标。确认资料后会自动加入，或使用“添加 / 管理指标”选择。</div>';
    const years=new Map();(data.months||[]).forEach(item=>{const year=item.month.slice(0,4);years.set(year,(years.get(year)||0)+item.count)});const maxYear=Math.max(1,...years.values());
    $('overviewActivity').innerHTML=years.size?[...years.entries()].sort().map(([year,count])=>`<button type="button" data-archive-year="${esc(year)}" aria-label="查看 ${esc(year)} 年的全部 ${count} 份资料"><b>${count}</b><i style="height:${Math.max(12,Math.round(count/maxYear*74))}px"></i><span>${esc(year)}年</span></button>`).join(''):'<div class="empty compact-empty">暂无资料活动</div>';
    const maxType=Math.max(1,...(data.types||[]).map(item=>item.count));
    $('overviewTypes').innerHTML=(data.types||[]).length?data.types.map(item=>`<button type="button" class="type-summary" data-archive-type="${esc(item.type)}" aria-label="查看全部 ${esc(item.type)}，共 ${item.count} 份"><span>${esc(item.type)}</span><i><b style="width:${Math.round(item.count/maxType*100)}%"></b></i><strong>${item.count}</strong></button>`).join(''):'<div class="empty compact-empty">暂无资料</div>';
  }

  function renderDashboardMetricManager() {
    if (!$('dashboardMetricList')) return;
    const query=$('dashboardMetricSearch').value.trim().toLocaleLowerCase('zh-CN');
    const definitions=state.metrics||[];
    const summaries=new Map((state.overview?.metric_catalog||[]).map(item=>[item.id,item]));
    const visible=item=>summaries.get(item.id)?.dashboard_visible??item.dashboard_visible;
    const selected=definitions.filter(visible).length;
    $('dashboardMetricCount').textContent=`已显示 ${selected} 项 · 默认最多 10 项，手动添加不受此限制`;
    const rows=definitions.filter(item=>`${item.name} ${item.group} ${(item.aliases||[]).join(' ')}`.toLocaleLowerCase('zh-CN').includes(query))
      .sort((a,b)=>Number(Boolean(visible(b)))-Number(Boolean(visible(a)))||
        (summaries.get(b.id)?.latest_date||'').localeCompare(summaries.get(a.id)?.latest_date||'')||
        (a.sort_order||0)-(b.sort_order||0));
    $('dashboardMetricList').innerHTML=rows.length?rows.map(item=>{
      const summary=summaries.get(item.id);
      return `<article class="dashboard-metric-item"><div><strong>${esc(item.name)}</strong><small>${esc(item.group)}${item.unit?` · ${esc(item.unit)}`:''} · ${summary?.record_count||0} 条记录</small><span>${esc(summary?.latest_result||'暂无结果')}</span></div><div class="dashboard-metric-actions"><button class="btn small" type="button" data-metric-detail="${item.id}">查看历史</button><button class="btn small ${visible(item)?'':'primary'}" type="button" data-dashboard-id="${item.id}" data-dashboard-next="${visible(item)?'false':'true'}">${visible(item)?'移出首页':'添加到首页'}</button></div></article>`;
    }).join(''):'<div class="empty compact-empty">没有符合搜索的指标</div>';
  }

  async function setDashboardVisibility(id,visible) {
    const metric=(state.metrics||[]).find(item=>item.id===id);
    if(!metric)return;
    try {
      await api.patch(`/api/metrics/${id}`,{expected_version:Number(metric.version),dashboard_visible:visible});
      await Promise.all([loadMetrics(),loadOverview()]);
      toast(visible?'已添加到首页':'已移出首页，历史结果仍保留');
    } catch(error) { toast(errorText(error)); }
  }

  function renderOverviewCosts(costs) {
    const totals=costs?.totals_by_currency||[],receipts=costs?.receipts||{total:0,known_amount:0,unknown_amount:0};
    const price=(currency,total)=>`${currency==='CNY'?'¥':`${esc(currency)} `}${esc(total)}`;
    const known=totals.filter(item=>item.known_count);
    const headline=known.length?known.map(item=>price(item.currency,item.total)).join(' / '):receipts.total?'金额待确认':'¥0.00';
    $('overviewCostTotal').textContent=headline;
    $('overviewCostFoot').textContent=`${receipts.known_amount||0} 张金额已知 · ${receipts.unknown_amount||0} 张未知`;
    $('overviewExpenseTotal').textContent=headline;
    $('overviewExpenseNote').textContent=`仅统计 ${receipts.known_amount||0} 张有明确金额的归档票据；${receipts.unknown_amount||0} 张金额待确认`;
    const payments=new Map((costs?.payments_by_currency||[]).map(item=>[item.currency,item]));
    $('overviewCosts').innerHTML=totals.length?totals.map(item=>{
      const split=payments.get(item.currency)||{};
      const part=(label,total,count)=>`<div class="overview-payment"><span>${label}</span><strong>${count?price(item.currency,total):'未提供'}</strong><small>${count?`${count} 张票据有明确记录`:'原件未明确记录'}</small></div>`;
      return `<div class="overview-currency"><div class="overview-currency-total"><span>${esc(item.currency)} · ${item.known_count} 张金额已知，${item.unknown_count} 张未知</span><strong>${item.known_count?price(item.currency,item.total):'金额待确认'}</strong></div><div class="overview-payment-grid">${part('医保支付',split.insurance_total,split.insurance_count)}${part('个人支付',split.personal_total,split.personal_count)}</div></div>`;
    }).join(''):'<div class="empty compact-empty">暂无可汇总票据</div>';
    $('overviewExpenseYears').innerHTML=totals.map(item=>{
      const entries=(costs?.years||[]).map(year=>({year:year.year,...((year.totals||[]).find(value=>value.currency===item.currency)||{})}))
        .filter(value=>/^\d{4}$/.test(value.year)&&value.known_count>0).sort((a,b)=>a.year.localeCompare(b.year));
      if(!entries.length)return '';
      const max=Math.max(...entries.map(value=>Number(value.total)),1);
      return `<div class="overview-year-series">${totals.length>1?`<h4>${esc(item.currency)}</h4>`:''}<div class="overview-year-bars">${entries.map(value=>`<div class="overview-year-bar" title="${esc(value.year)}年 · ${price(item.currency,value.total)} · ${value.known_count} 张票据"><strong>${price(item.currency,value.total)}</strong><i style="height:${Math.max(10,Math.round(Number(value.total)/max*100))}px"></i><span>${esc(value.year)}年</span><small>${value.known_count} 张</small></div>`).join('')}</div></div>`;
    }).join('')||'<div class="empty compact-empty">暂无有明确金额和日期的票据</div>';
  }

  const ownershipDialog=$('ownershipDialog');
  async function openOwnershipReview(){
    $('ownershipError').textContent='';$('ownershipSelectAll').checked=false;
    $('ownershipList').innerHTML='<div class="empty compact-empty">正在读取已归档资料…</div>';
    ownershipDialog.showModal();
    try{
      const owner=state.user?.id,documents=[];
      let cursor=0;
      do{
        const page=await api.get(`/api/documents?limit=100&cursor=${cursor}`);
        if(!sameOwner(owner))return;
        documents.push(...page.items);
        cursor=page.next_cursor;
      }while(cursor!==null&&cursor!==undefined);
      state.ownershipCandidates=documents.filter(item=>item.patient_scope==='unconfirmed');
      $('ownershipList').innerHTML=state.ownershipCandidates.length?state.ownershipCandidates.map(item=>`<label class="ownership-item"><input type="checkbox" data-ownership-id="${item.id}" data-version="${item.version}"><span><strong>${esc(item.title)}</strong><small>${esc([item.primary_date||'日期待确认',item.hospital||'医院待确认',item.document_type].join(' · '))}</small></span></label>`).join(''):'<div class="empty compact-empty">没有归属待确认的资料</div>';
    }catch(error){$('ownershipError').textContent=errorText(error)}
  }
  async function confirmOwnership(){
    const selected=[...document.querySelectorAll('#ownershipList [data-ownership-id]:checked')];
    if(!selected.length){$('ownershipError').textContent='请先选择属于本人的资料';return}
    const button=$('confirmOwnership');button.disabled=true;
    let completed=0;
    try{
      for(const item of selected){
        $('ownershipError').textContent=`正在确认 ${completed+1} / ${selected.length} 份资料…`;
        await api.patch(`/api/documents/${item.dataset.ownershipId}`,{expected_version:Number(item.dataset.version),patient_scope:'self'});
        completed++;
      }
      ownershipDialog.close();
      await Promise.all([loadDocuments(),loadMetrics(),loadOverview()]);
      toast(`${completed} 份本人资料已纳入健康指标`);
    }catch(error){$('ownershipError').textContent=`已确认 ${completed} 份；${errorText(error)}。请刷新后继续核对。`;await Promise.all([loadDocuments(),loadOverview()])}
    finally{button.disabled=false}
  }

  function overviewSparkline(series,label) {
    const usable=(series||[]).filter(item=>item.points?.length);
    if(!usable.length)return '<span class="spark-empty">—</span>';
    const values=usable.flatMap(item=>item.points.flatMap(point=>[Number(point.y),point.y2===undefined?null:Number(point.y2)])).filter(Number.isFinite);
    if(!values.length)return '<span class="spark-empty">—</span>';
    const min=Math.min(...values),max=Math.max(...values),range=max-min||1;
    const lines=[];
    usable.slice(0,2).forEach((item,index)=>{const points=item.points;if(points.length===1){lines.push(`<circle class="spark-single-point spark-${index+1}" cx="${usable.length===1?50:30+index*40}" cy="18" r="4.5"><title>${esc(label)}：${esc(points[0].y)} ${esc(item.unit||'')}</title></circle>`);return}const numericX=points.every(point=>Number.isFinite(Number(point.x)));const xs=numericX?points.map(point=>Number(point.x)):points.map((_point,i)=>i);const minX=Math.min(...xs),maxX=Math.max(...xs),xRange=maxX-minX||1;const coords=points.map((point,i)=>`${4+(xs[i]-minX)*92/xRange},${31-(Number(point.y)-min)*25/range}`).join(' ');lines.push(`<polyline class="spark-line spark-${index+1}" points="${coords}"></polyline>`)});
    return `<svg viewBox="0 0 100 36" role="img" aria-label="${esc(label)}${usable.length===1&&usable[0].points.length===1?'单次记录':'趋势'}">${lines.join('')}</svg>`;
  }

  window.loadMetrics = async function loadMetrics() {
    if (!state.user) return;
    const owner=state.user.id;
    try {
      const [catalog, entries]=await Promise.all([api.get('/api/metrics'),api.get('/api/metric-entries?limit=200')]);
      if(!sameOwner(owner))return;
      state.metrics=catalog.items; state.metricEntries=entries.items;
      renderMetricCatalog(); renderOverview(); renderDashboardMetricManager();
    } catch(error){if(sameOwner(owner))toast(errorText(error));}
  };

  function renderMetricCatalog() {
    const current=$('metricEntryMetric').value;
    $('metricCatalog').innerHTML=state.metrics.length?state.metrics.map(item=>`<article class="metric-item ${item.followed?'followed':''}"><button type="button" class="metric-open" data-metric-id="${item.id}"><span><strong>${esc(item.name)}</strong><small>${esc(item.group)} · ${esc(item.unit||'无固定单位')}</small></span><b>历史 →</b></button><button type="button" class="follow-btn" data-follow-id="${item.id}" data-version="${item.version}">${item.followed?'取消关注':'关注'}</button></article>`).join(''):'<div class="empty">暂无指标目录</div>';
    const usable=state.metrics.filter(item=>item.record_type!=='group');
    $('metricEntryMetric').innerHTML=usable.map(item=>`<option value="${item.id}">${esc(item.name)}</option>`).join('');
    if(usable.some(x=>x.id===current))$('metricEntryMetric').value=current;
    syncMetricForm();
  }

  function selectedMetric(){return state.metrics.find(item=>item.id===$('metricEntryMetric').value);}
  function syncMetricForm(){const metric=selectedMetric();if(!metric)return;$('metricEntryUnit').value=metric.unit||'';const pair=metric.record_type==='pair',qualitative=metric.record_type==='qualitative';document.querySelector('#metricEntryForm .pair-fields').classList.toggle('hidden',!pair);$('metricEntryText').closest('label').classList.toggle('hidden',!qualitative);$('metricEntryValue1').closest('label').classList.toggle('hidden',qualitative);if(!pair)$('metricEntryValue2').value='';if(qualitative)$('metricEntryValue1').value='';else $('metricEntryText').value='';}
  function parseRawEntry(){const metric=selectedMetric(),raw=$('metricEntryRaw').value.trim();if(!metric)return;if(metric.record_type==='pair'){const parts=raw.split(/[\/／]/).map(x=>x.trim());if(parts.length===2&&parts.every(x=>/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(x))){$('metricEntryValue1').value=parts[0];$('metricEntryValue2').value=parts[1];}}else if(metric.record_type==='numeric'&&/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(raw))$('metricEntryValue1').value=raw;else if(metric.record_type==='qualitative')$('metricEntryText').value=raw;}

  async function saveMetricEntry(event){event.preventDefault();const metric=selectedMetric();if(!metric)return;const payload={metric_id:metric.id,record_date:$('metricEntryDate').value,raw_value:$('metricEntryRaw').value.trim(),unit:$('metricEntryUnit').value.trim()||null,condition:$('metricEntryCondition').value.trim()||null,review_status:'confirmed',idempotency_key:state.metricEntryKey||(state.metricEntryKey=crypto.randomUUID())};if($('metricEntryValue1').value.trim())payload.value1=$('metricEntryValue1').value.trim();if($('metricEntryValue2').value.trim())payload.value2=$('metricEntryValue2').value.trim();if($('metricEntryText').value.trim())payload.text_value=$('metricEntryText').value.trim();try{await api.post('/api/metric-entries',payload);state.metricEntryKey=null;$('metricEntryForm').reset();$('metricEntryDate').value=today();$('metricEntryError').textContent='';await loadMetrics();toast('日常记录已保存')}catch(error){$('metricEntryError').textContent=errorText(error)}}

  async function toggleFollow(id,version){const metric=state.metrics.find(x=>x.id===id)||(state.overview?.metrics||[]).find(x=>x.id===id);if(!metric)return;try{await api.patch(`/api/metrics/${id}`,{expected_version:Number(version),followed:!metric.followed});await Promise.all([loadMetrics(),loadOverview()])}catch(error){toast(errorText(error))}}
  function trendSvg(items,label){const rows=items.filter(x=>x.record_date&&Number.isFinite(Number(x.value1))).sort((a,b)=>a.record_date.localeCompare(b.record_date));if(rows.length<2)return'';const values=rows.flatMap(x=>[Number(x.value1),x.value2===null?null:Number(x.value2)]).filter(Number.isFinite),min=Math.min(...values),max=Math.max(...values),range=max-min||1;const points=key=>rows.map((x,i)=>`${24+i*(552/Math.max(rows.length-1,1))},${126-(Number(x[key])-min)*92/range}`).join(' ');return `<figure class="trend-chart"><figcaption>${esc(label)} · ${rows.length} 个可比较日期</figcaption><svg viewBox="0 0 600 150" role="img" aria-label="${esc(label)}趋势"><line x1="24" y1="126" x2="576" y2="126"></line><polyline class="line-one" points="${points('value1')}"></polyline>${rows.some(x=>x.value2!==null)?`<polyline class="line-two" points="${points('value2')}"></polyline>`:''}</svg></figure>`}
  async function loadMetricResults(id){const owner=state.user?.id,metric=state.metrics.find(x=>x.id===id);if(!owner||!metric)return;state.selectedMetricId=id;$('metricHistoryTitle').textContent=`${metric.name} · 历史来源`;loading('metricHistory');try{const result=await api.get(`/api/metrics/${id}/results`);if(!sameOwner(owner))return;const groupNames=[...new Set(result.items.map(x=>x.comparison_group))];const charts=groupNames.map(group=>trendSvg(result.items.filter(x=>x.comparison_group===group),`${metric.name} · ${group.replace('unit:','')}`)).join('');$('metricHistory').innerHTML=result.items.length?`<div class="history-note">${groupNames.length>1?'检测到不同单位，以下结果不会跨单位连线。':'原值与来源均保留。'} 排除 ${Object.values(result.excluded).reduce((a,b)=>a+b,0)} 条不满足条件的结果。</div>${charts}${result.items.map(item=>`<article class="history-row"><span><strong>${esc(item.raw_value)} ${esc(item.unit||'')}</strong><small>${esc(item.record_date||'日期待确认')} · ${item.source_type==='manual'?'日常记录':'检验报告'}${item.condition?` · ${esc(item.condition)}`:''}</small></span>${item.source_type==='lab_report'?`<button class="btn small" data-document="${item.source_id}">查看原件</button>`:''}</article>`).join('')}`:'<div class="empty">暂无可用结果</div>'}catch(error){if(sameOwner(owner))$('metricHistory').innerHTML=`<div class="empty">${esc(errorText(error))}</div>`}}
  function metricChart(rows,metric,axis,label){
    const points=rows.filter(item=>Number.isFinite(Number(item.value1))&&(axis==='minutes'?Number.isFinite(Number(item.timepoint_minutes)):Boolean(item.record_date)))
      .sort((a,b)=>axis==='minutes'?Number(a.timepoint_minutes)-Number(b.timepoint_minutes):a.record_date.localeCompare(b.record_date));
    if(!points.length)return '';
    const allValues=points.flatMap(item=>[Number(item.value1),item.value2===null||item.value2===undefined?null:Number(item.value2)]).filter(Number.isFinite);
    const low=Math.min(...allValues),high=Math.max(...allValues),span=high-low;
    const padding=span?span*.15:Math.max(Math.abs(low)*.1,.1),scaleLow=low-padding,scaleHigh=high+padding;
    const xValues=points.map(item=>axis==='minutes'?Number(item.timepoint_minutes):Date.parse(`${item.record_date}T00:00:00`));
    const minX=Math.min(...xValues),maxX=Math.max(...xValues),xSpan=maxX-minX;
    const xAt=index=>xSpan?80+(xValues[index]-minX)*645/xSpan:402;
    const yAt=value=>220-(Number(value)-scaleLow)*175/(scaleHigh-scaleLow);
    const precision=Math.min(4,Math.max(0,Math.ceil(-Math.log10((scaleHigh-scaleLow)/2))+1));
    const formatTick=value=>Number(value.toFixed(precision)).toString();
    const yTicks=(span?[low,(low+high)/2,high]:[scaleLow,low,scaleHigh]).map(value=>`<g><line class="metric-grid" x1="80" y1="${yAt(value)}" x2="725" y2="${yAt(value)}"></line><text class="metric-y-tick" x="68" y="${yAt(value)+4}" text-anchor="end">${formatTick(value)}</text></g>`).join('');
    const distinct=[...new Map(xValues.map((value,index)=>[value,index])).values()];
    const selected=[];
    distinct.forEach((index,position)=>{
      const last=distinct[distinct.length-1],previous=selected[selected.length-1];
      if(position===0||position===distinct.length-1||(!selected.length||xAt(index)-xAt(previous)>=110)&&xAt(last)-xAt(index)>=90)selected.push(index);
    });
    const xTicks=selected.map(index=>`<g><line class="metric-x-mark" x1="${xAt(index)}" y1="232" x2="${xAt(index)}" y2="237"></line><text class="metric-x-tick" x="${xAt(index)}" y="256" text-anchor="middle">${esc(axis==='minutes'?`${points[index].timepoint_minutes} min`:xSpan<180*86400000?points[index].record_date:points[index].record_date.slice(0,7))}</text></g>`).join('');
    const series=(key,css,component)=>{const matching=points.map((item,index)=>({item,index})).filter(({item})=>item[key]!==null&&item[key]!==undefined&&Number.isFinite(Number(item[key])));if(!matching.length)return '';const coords=matching.map(({item,index})=>`${xAt(index)},${yAt(item[key])}`).join(' ');return `${matching.length>1?`<polyline class="${css}" points="${coords}"></polyline>`:''}${matching.map(({item,index})=>{const date=axis==='minutes'?`${item.record_date||''} · ${item.timepoint_minutes} min`:item.record_date;const value=key==='value2'?item.value2:item.value1;const description=`${date} · ${component?`${component} `:''}${value} ${item.unit||''}`;return `<g data-chart-point data-chart-date="${esc(date)}" data-chart-value="${esc(value)}" data-chart-unit="${esc(item.unit||'')}" data-chart-component="${esc(component||'')}" data-chart-condition="${esc(item.condition||'')}" data-chart-source="${esc(item.source_type==='manual'?'日常记录':'检验报告')}" tabindex="0" aria-label="${esc(description)}"><circle class="${css}-point" cx="${xAt(index)}" cy="${yAt(value)}" r="7"></circle></g>`}).join('')}`};
    const pair=points.some(item=>item.value2!==null&&item.value2!==undefined);
    return `<figure class="metric-chart"><figcaption>${esc(label)}${pair?`<span class="metric-chart-legend"><i></i>${esc(metric.component_labels?.[0]||'数值 1')}<i class="second"></i>${esc(metric.component_labels?.[1]||'数值 2')}</span>`:''}</figcaption><svg viewBox="0 0 780 280" role="img" aria-label="${esc(metric.name)}趋势图"><line class="metric-axis" x1="80" y1="35" x2="80" y2="232"></line><line class="metric-axis" x1="80" y1="232" x2="725" y2="232"></line>${yTicks}${series('value1','metric-line-primary',pair?metric.component_labels?.[0]||'数值 1':'')}${pair?series('value2','metric-line-secondary',metric.component_labels?.[1]||'数值 2'):''}${xTicks}</svg><div class="metric-chart-tooltip hidden" role="tooltip"></div></figure>`;
  }
  function showMetricPoint(point){
    const figure=point.closest('.metric-chart'),tooltip=figure?.querySelector('.metric-chart-tooltip');
    if(!tooltip)return;
    const {chartDate,chartValue,chartUnit,chartComponent,chartCondition,chartSource}=point.dataset;
    tooltip.textContent=`${chartDate} · ${chartComponent?`${chartComponent} `:''}${chartValue}${chartUnit?` ${chartUnit}`:''}${chartCondition?` · ${chartCondition}`:''} · ${chartSource}`;
    tooltip.classList.remove('hidden');
    const figureRect=figure.getBoundingClientRect(),pointRect=point.getBoundingClientRect();
    tooltip.style.left=`${Math.max(8,Math.min(pointRect.left+pointRect.width/2-figureRect.left-tooltip.offsetWidth/2,figureRect.width-tooltip.offsetWidth-8))}px`;
    tooltip.style.top=`${pointRect.top-figureRect.top>tooltip.offsetHeight+14?pointRect.top-figureRect.top-tooltip.offsetHeight-8:pointRect.bottom-figureRect.top+8}px`;
  }
  function hideMetricPoints(){document.querySelectorAll('#metricDetailTrend .metric-chart-tooltip').forEach(tooltip=>tooltip.classList.add('hidden'))}
  function metricSeriesName(metric,item){
    if(metric.key!=='blood_lipids')return metric.name;
    return ({total_cholesterol:'总胆固醇（TC）',triglycerides:'甘油三酯（TG）',hdl_c:'高密度脂蛋白胆固醇（HDL-C）',ldl_c:'低密度脂蛋白胆固醇（LDL-C）'})[item?.series_key]||metric.name;
  }
  function renderMetricDetail(){
    const metric=state.metricDetailMetric,result=state.metricDetailResult;
    if(!metric||!result)return;
    const items=result.items||[],latest=items[0],isDynamic=metric.key.startsWith('ogtt_');
    $('metricDetailTitle').textContent=metric.name;
    $('metricDetailGroup').textContent=`${metric.group||'健康指标'}${metric.unit?` · ${metric.unit}`:''}${metric.dashboard_visible?' · 首页显示':''}`;
    $('metricDetailRecord').classList.toggle('hidden',metric.manual_entry_allowed===false||metric.record_type==='group');
    $('metricDetailSummary').innerHTML=[
      ['最新结果',metric.latest_result||[latest?.raw_value,latest?.unit].filter(Boolean).join(' ')||'暂无结果'],
      ['最近日期',metric.latest_date||latest?.record_date||'日期待确认'],
      ['历史记录',`${metric.record_count??items.length} 次`],
      ['数据来源',`报告 ${items.filter(x=>x.source_type==='lab_report').length} · 手动 ${items.filter(x=>x.source_type==='manual').length}`],
    ].map(([label,value])=>`<div class="metric-summary-stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
    const current=state.metricDetailPeriod||'all';
    document.querySelectorAll('#metricDetailPeriods [data-period]').forEach(button=>button.classList.toggle('active',button.dataset.period===current));
    $('metricDetailPeriods').classList.toggle('hidden',isDynamic||metric.record_type==='qualitative');
    let chartItems=items;
    if(!isDynamic&&current!=='all'){
      const cutoff=new Date(),months=current==='3m'?3:12;
      cutoff.setMonth(cutoff.getMonth()-months);
      chartItems=items.filter(item=>item.record_date&&new Date(`${item.record_date}T00:00:00`)>=cutoff);
    }
    if(isDynamic){
      const sessions=new Map();
      chartItems.filter(item=>item.test_session_id&&item.timepoint_minutes!==null).forEach(item=>{
        if(!sessions.has(item.test_session_id))sessions.set(item.test_session_id,[]);
        sessions.get(item.test_session_id).push(item);
      });
      const newest=[...sessions.values()].sort((a,b)=>(b[0]?.record_date||'').localeCompare(a[0]?.record_date||''))[0]||[];
      chartItems=newest;
    }
    const groups=new Map();
    chartItems.forEach(item=>{const key=item.comparison_group||'单位待确认';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item)});
    const charts=metric.record_type==='qualitative'?[]:[...groups.entries()].map(([key,rows])=>metricChart(rows,metric,isDynamic?'minutes':'dates',`${metricSeriesName(metric,rows[0])} · ${rows[0]?.unit||'单位待确认'}`)).filter(Boolean);
    $('metricDetailTrend').innerHTML=metric.record_type==='qualitative'?'<div class="empty compact-empty">该项目是文字结果，不绘制数值曲线。下方按报告列出完整历史。</div>':charts.join('')||'<div class="empty compact-empty">该时间范围内暂无可绘制的数值结果</div>';
    const excluded=Object.values(result.excluded||{}).reduce((sum,count)=>sum+count,0);
    $('metricDetailCompare').innerHTML=metric.record_type==='qualitative'?`<p>阴性、阳性等结果按报告原文保留，不换算为数值，也不画曲线。</p><div class="metric-compare-rule">同一天的不同报告分别列出，查看来源可核对原件。</div>${excluded?`<p>另有 ${excluded} 条结果未纳入历史。</p>`:''}`:`<p>${groups.size>1?'结果按原始单位及项目分别绘制，不跨组连线。':'同组数值按照记录日期连接，保留每条结果的原始单位与来源。'}</p><div class="metric-compare-rule">带“&lt;”或“&gt;”的结果、阴性或阳性等文字结果不作为精确数值绘图；不同单位不会自动换算。</div><p>每次报告保留自己的参考范围，不统一阈值覆盖历史报告。</p>${excluded?`<p>另有 ${excluded} 条结果因资料归属或核对条件未纳入曲线。</p>`:''}`;
    $('metricDetailHistory').innerHTML=items.length?items.map(item=>`<tr><td>${esc(item.record_date||'日期待确认')}${item.timepoint_minutes!==null&&item.timepoint_minutes!==undefined?`<small>${item.timepoint_minutes} min</small>`:''}</td><td><strong>${esc(item.raw_value||'未提供')}</strong></td><td>${esc(item.unit||'—')}</td><td>${esc(item.reference_range||'未提供')}</td><td>${esc(item.flag||'原报告未标记')}</td><td>${item.source_type==='manual'?'手动记录':'检验报告'}</td><td>已确认</td><td class="metric-history-actions">${item.source_type==='lab_report'?`<button class="btn small" type="button" data-document="${item.source_id}">查看并修正来源</button>`:`<button class="btn small" type="button" data-edit-entry="${item.source_id}">编辑</button><button class="btn small" type="button" data-trash-entry="${item.source_id}">移入回收站</button>`}</td></tr>`).join(''):'<tr><td colspan="8" class="empty">暂无历史结果</td></tr>';
  }
  async function openMetricDetail(id,fromRoute=false){
    const owner=state.user?.id,metric=state.metrics.find(x=>x.id===id)||(state.overview?.metrics||[]).find(x=>x.id===id);
    if(!owner||!metric)return;
    state.metricDetailId=id;state.metricDetailMetric=metric;state.metricDetailPeriod='all';
    $('metricDetailTrend').innerHTML='<div class="empty compact-empty">正在读取指标历史…</div>';
    $('metricDetailHistory').innerHTML='';
    showView('metric-detail',{refresh:false});
    if(!fromRoute&&!state.routeApplying){state.metricDetailPushed=true;pushRoute(`#metric/${id}`)}
    try{const result=await api.get(`/api/metrics/${id}/results`);if(!sameOwner(owner)||state.metricDetailId!==id)return;state.metricDetailResult=result;renderMetricDetail()}
    catch(error){if(sameOwner(owner))$('metricDetailTrend').innerHTML=`<div class="empty compact-empty">${esc(errorText(error))}</div>`}
  }
  window.openMetricDetail=openMetricDetail;
  function returnFromMetricDetail(){
    if(state.metricDetailPushed&&location.hash.startsWith('#metric/')){state.metricDetailPushed=false;history.back()}
    else showView('overview',{refresh:false,restoreScroll:true});
  }
  const metricRecordDialog=$('metricRecordDialog');
  function overviewMetric(id){return state.metrics.find(x=>x.id===id)||(state.overview?.metrics||[]).find(x=>x.id===id)}
  function openMetricRecord(id){const metric=overviewMetric(id);if(!metric)return;$('quickMetricForm').reset();$('quickMetricId').value=id;$('quickMetricTitle').textContent=`记录 ${metric.name}`;$('quickMetricDate').value=today();$('quickMetricUnit').value=metric.unit||'';$('quickMetricError').textContent='';$('quickMetricRaw').placeholder=metric.record_type==='pair'?'例如 120/80':metric.record_type==='qualitative'?'例如 阴性':'例如 5.6';$('quickMetricValueLabel').textContent=metric.record_type==='pair'?'数值 1':'数值';$('quickMetricNumbers').classList.toggle('hidden',metric.record_type==='qualitative');$('quickMetricNumbers').classList.toggle('single-value',metric.record_type!=='pair');document.querySelector('[data-quick-number]').classList.toggle('hidden',metric.record_type==='qualitative');document.querySelector('[data-quick-pair]').classList.toggle('hidden',metric.record_type!=='pair');document.querySelector('[data-quick-text]').classList.toggle('hidden',metric.record_type!=='qualitative');metricRecordDialog.showModal();$('quickMetricRaw').focus()}
  function parseQuickMetric(){const metric=overviewMetric($('quickMetricId').value),raw=$('quickMetricRaw').value.trim();if(!metric)return;if(metric.record_type==='pair'){const parts=raw.split(/[\/／]/).map(x=>x.trim());if(parts.length===2&&parts.every(x=>/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(x))){$('quickMetricValue1').value=parts[0];$('quickMetricValue2').value=parts[1]}}else if(metric.record_type==='numeric'&&/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(raw))$('quickMetricValue1').value=raw;else if(metric.record_type==='qualitative')$('quickMetricText').value=raw}
  async function saveQuickMetric(event){event.preventDefault();const metric=overviewMetric($('quickMetricId').value);if(!metric)return;const payload={metric_id:metric.id,record_date:$('quickMetricDate').value,raw_value:$('quickMetricRaw').value.trim(),unit:$('quickMetricUnit').value.trim()||null,condition:$('quickMetricCondition').value.trim()||null,review_status:'confirmed',idempotency_key:crypto.randomUUID()};if($('quickMetricValue1').value.trim())payload.value1=$('quickMetricValue1').value.trim();if($('quickMetricValue2').value.trim())payload.value2=$('quickMetricValue2').value.trim();if($('quickMetricText').value.trim())payload.text_value=$('quickMetricText').value.trim();try{await api.post('/api/metric-entries',payload);metricRecordDialog.close();await Promise.all([loadMetrics(),loadOverview()]);toast('日常记录已保存')}catch(error){$('quickMetricError').textContent=errorText(error)}}
  async function saveCustomMetric(event){event.preventDefault();const type=$('customMetricType').value,payload={name:$('customMetricName').value.trim(),group:$('customMetricGroup').value.trim(),record_type:type,unit:$('customMetricUnit').value.trim()||null,aliases:[],followed:true,component_labels:type==='pair'?[$('customMetricLabel1').value.trim(),$('customMetricLabel2').value.trim()]:[]};try{await api.post('/api/metrics',payload);$('customMetricForm').reset();$('customMetricPair').classList.add('hidden');$('customMetricError').textContent='';await loadMetrics();toast('自定义指标已添加')}catch(error){$('customMetricError').textContent=errorText(error)}}

  window.loadCosts = async function loadCosts(){if(!state.user)return;const owner=state.user.id;loading('costReceipts');try{const year=$('costYear').value,unknown=$('costKnown').value;const query=new URLSearchParams({limit:'100'});if(year)query.set('year',year);if(unknown)query.set('unknown_amount',unknown);if($('costStatus').value==='all')query.set('include_excluded','true');const summaryPromise=api.get('/api/costs/summary'),items=[];let cursor=0;do{query.set('cursor',String(cursor));const page=await api.get(`/api/costs/receipts?${query}`);if(!sameOwner(owner))return;items.push(...page.items);cursor=page.next_cursor??null}while(cursor!==null);const summary=await summaryPromise;if(!sameOwner(owner))return;state.costSummary=summary;state.receipts=items;renderCostSummary(summary);renderCostReceipts(items);renderOverviewCosts(summary);renderOverview()}catch(error){if(sameOwner(owner))toast(errorText(error))}};
  function renderCostSummary(data){$('costSummary').innerHTML=`<article class="stat"><div class="stat-label">有效票据</div><div class="stat-value">${data.receipts.total}</div><div class="stat-foot">另排除 ${data.excluded_count} 张重复或作废票据</div></article><article class="stat"><div class="stat-label">金额已知</div><div class="stat-value">${data.receipts.known_amount}</div><div class="stat-foot">参与费用汇总</div></article><article class="stat"><div class="stat-label">金额未知</div><div class="stat-value">${data.receipts.unknown_amount}</div><div class="stat-foot">等待核对原件</div></article>`;const years=data.years.map(x=>x.year).filter(x=>x!=='undated');const current=$('costYear').value;$('costYear').innerHTML='<option value="">全部年份</option>'+years.map(x=>`<option>${esc(x)}</option>`).join('');if(years.includes(current))$('costYear').value=current;}
  function renderCostReceipts(items){const active=items.filter(x=>x.status==='active'&&x.id);$('costReceipts').innerHTML=items.length?items.map(item=>`<article class="receipt-card"><div><span class="pill">${esc(item.currency)} · ${item.status==='active'?'参与统计':item.status==='duplicate'?'重复票据':'已作废'}</span><h4>${esc(item.title)}</h4><p>${esc([item.primary_date||'日期待确认',item.hospital||'医院待确认'].join(' · '))}</p></div><strong>${item.amount===null?'金额待确认':`${esc(item.amount)} ${esc(item.currency)}`}</strong><button class="btn small" data-document="${item.document_id}">查看原件</button><button class="btn small" data-edit-document-id="${item.document_id}">编辑费用</button>${item.id&&item.status==='active'&&active.some(x=>x.id!==item.id)?`<label class="receipt-dedupe">重复于<select data-duplicate-target="${item.id}">${active.filter(x=>x.id!==item.id).map(x=>`<option value="${x.id}">${esc(x.title)}</option>`).join('')}</select><button class="btn small" data-receipt-duplicate="${item.id}" data-version="${item.version}">标为重复</button></label>`:item.id&&item.status!=='active'?`<button class="btn small" data-receipt-restore="${item.id}" data-version="${item.version}">恢复参与统计</button>`:''}</article>`).join(''):'<div class="empty">暂无符合条件的票据</div>'}
  async function updateReceiptStatus(id,version,status,target=null){try{await api.patch(`/api/costs/receipts/${id}`,{expected_version:Number(version),status,duplicate_of_id:target});await loadCosts();toast(status==='active'?'票据已恢复统计':'票据已标记为重复')}catch(error){toast(errorText(error))}}

  window.loadOgtt = async function loadOgtt(){if(!state.user)return;const owner=state.user.id;try{const [sessions,candidates]=await Promise.all([api.get('/api/test-sessions'),api.get('/api/test-sessions/candidates')]);if(!sameOwner(owner))return;state.testSessions=sessions.items;renderOgtt(sessions.items,candidates.items)}catch(error){if(sameOwner(owner))toast(errorText(error))}};
  function ogttChart(points,label){const rows=points.filter(x=>x.value!==null&&Number.isFinite(Number(x.value))&&Number.isFinite(Number(x.timepoint_minutes))).sort((a,b)=>a.timepoint_minutes-b.timepoint_minutes);if(rows.length<2)return'';const xs=rows.map(x=>Number(x.timepoint_minutes)),ys=rows.map(x=>Number(x.value)),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys),rx=maxX-minX||1,ry=maxY-minY||1,coords=rows.map(x=>`${24+(Number(x.timepoint_minutes)-minX)*552/rx},${126-(Number(x.value)-minY)*92/ry}`).join(' ');return `<figure class="trend-chart"><figcaption>${esc(label)} · 按实际分钟坐标</figcaption><svg viewBox="0 0 600 150" role="img" aria-label="${esc(label)}时点曲线"><line x1="24" y1="126" x2="576" y2="126"></line><polyline class="line-one" points="${coords}"></polyline></svg></figure>`}
  function ogttCharts(points){const groups=new Map();points.forEach(point=>{const key=`${point.analyte_key||point.name}|${(point.unit||'').trim().toLowerCase()}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(point)});return [...groups.values()].map(rows=>ogttChart(rows,`${rows[0].name||rows[0].analyte_key||'未命名项目'} · ${rows[0].unit||'单位待确认'}`)).join('')}
  function renderOgtt(sessions,candidates){$('ogttSessions').innerHTML=sessions.length?sessions.map(session=>`<article class="session-card"><div class="session-head"><span><strong>${esc(session.name)}</strong><small>${esc(session.session_date||'日期待确认')} · ${esc(session.hospital||'医院待确认')}</small></span><b>${session.points.length} 个点</b></div>${ogttCharts(session.points)}<div class="ogtt-points">${session.points.map(point=>`<button type="button" ${point.document_id?`data-document="${point.document_id}"`:''} ${point.source_unit_id?`data-source-unit="${point.source_unit_id}"`:''}><strong>${point.timepoint_minutes??'?'} min</strong><span>${esc(point.name)}：${esc(point.raw_value||'未提供')} ${esc(point.unit||'')}</span></button>`).join('')||'<div class="empty compact-empty">尚未关联检验点</div>'}</div></article>`).join(''):'<div class="empty">尚未建立试验；同日资料会保持分开，直到你明确分组。</div>';$('ogttCandidates').innerHTML=candidates.length?candidates.map(item=>`<label><input type="checkbox" name="ogttLab" value="${item.id}"><span><strong>${esc(item.name)} · ${item.timepoint_minutes} min · ${esc(item.raw_value||'未提供')} ${esc(item.unit||'')}</strong><small>${esc(item.observed_date||'日期待确认')} · ${esc(item.hospital||'医院待确认')} · ${esc(item.document_title)}</small></span></label>`).join(''):'<div class="empty compact-empty">没有待分组的时点结果</div>'}
  async function saveOgtt(event){event.preventDefault();const ids=[...document.querySelectorAll('[name="ogttLab"]:checked')].map(x=>x.value);if(!ids.length){$('ogttError').textContent='请至少选择一个检验点';return}try{await api.post('/api/test-sessions',{name:$('ogttName').value.trim(),session_date:$('ogttDate').value||null,hospital:$('ogttHospital').value.trim()||null,lab_result_ids:ids});$('ogttForm').reset();$('ogttError').textContent='';await loadOgtt();toast('试验分组已保存')}catch(error){$('ogttError').textContent=errorText(error)}}

  const baseDetail=renderDocumentDetail;
  renderDocumentDetail=()=>{baseDetail();const doc=state.currentDocument;if(!doc)return;const details=doc.type_specific_data||{},extra=[];if(details.exam){extra.push(['检查名称',details.exam.exam_name],['影像所见',(details.exam.findings||[]).join('\n')],['检查意见',(details.exam.impression||[]).join('\n')])}if(doc.receipt){extra.push(['票据编号',doc.receipt.receipt_number],['费用总额',doc.receipt.total_amount===null?null:`${doc.receipt.total_amount} ${doc.receipt.currency}`],['医保支付',doc.receipt.insurance_amount],['个人支付',doc.receipt.personal_amount],['支付方式',doc.receipt.payment_method])}extra.push(['资料归属',({self:'当前档案成员',other:'其他人',unconfirmed:'未确认'})[doc.patient_scope]||'未确认']);$('fieldGrid').insertAdjacentHTML('beforeend',extra.map(item=>`<div class="field wide"><label>${esc(item[0])}</label><div>${item[1]!==null&&item[1]!==undefined&&item[1]!==''?esc(item[1]):'<span class="null-value">未提供</span>'}</div></div>`).join(''));};

  let medicationImages=[];
  function renderMedicationPreview(index){
    const item=medicationImages[index];
    $('medPhotoLarge').innerHTML=item?attachmentPreview(item):'<div class="empty compact-empty">暂无可预览原图</div>';
    document.querySelectorAll('#medPhotoThumbs button').forEach((button,i)=>button.classList.toggle('active',i===index));
  }
  async function openMedicationDetail(id,fromRoute=false){
    const owner=state.user?.id;if(!owner)return;
    state.medicationDetailId=id;
    $('medDetailBody').innerHTML='<div class="empty">正在读取药品来源…</div>';
    showView('medication-detail',{refresh:false});
    if(!fromRoute&&!state.routeApplying){state.medicationDetailPushed=true;pushRoute(`#medication/${id}`)}
    try{
      const med=await api.get(`/api/medications/${id}`);
      if(!sameOwner(owner)||state.medicationDetailId!==id)return;
      state.currentMedication=med;
      const docIds=[...new Set([...(med.packages||[]).map(x=>x.document_id),...(med.sources||[]).map(x=>x.document_id)].filter(Boolean))];
      const docs=(await Promise.allSettled(docIds.map(documentId=>api.get(`/api/documents/${documentId}`))))
        .filter(item=>item.status==='fulfilled').map(item=>item.value);
      if(!sameOwner(owner)||state.medicationDetailId!==id)return;
      medicationImages=[...new Map(docs.flatMap(doc=>(doc.attachments||[]).map(att=>[att.id||att.content_url,{...att,document_id:doc.id}]))).values()];
      $('medDetailTitle').textContent=med.name;
      $('medDetailMeta').textContent=[med.generic_name,med.brand_name,med.strength,med.status].filter(Boolean).join(' · ');
      const field=(label,value)=>`<div class="field"><label>${label}</label><div>${value?esc(value):'<span class="null-value">未提供</span>'}</div></div>`;
      const fields=[['通用名',med.generic_name],['商品名',med.brand_name],['规格',med.strength],['剂型',med.dosage_form],['厂家',med.manufacturer],['批准文号',med.approval_number],['给药途径',med.route],['用药状态',med.status],['每次用量',med.dose_each_time],['频次',med.frequency],['时间',med.timing],['计划结束',med.planned_end_date]];
      $('medDetailBody').innerHTML=`<section class="card drug-detail-card"><div class="pane-title"><h4>基本信息与用法用量</h4><span class="pill green">忠实归档</span></div><div class="field-grid">${fields.map(([label,value])=>field(label,value)).join('')}</div><details class="med-original-notes"><summary>查看原始说明内容</summary><div>${docs.map(doc=>`<article><strong>${esc(doc.title||'原始资料')}</strong><pre>${esc(doc.parsed_content||'暂无完整说明原文')}</pre></article>`).join('')||'<p>暂无原始说明内容</p>'}</div></details></section><section class="card drug-detail-card"><div class="pane-title"><h4>包装原图与来源记录</h4><span class="pill">${medicationImages.length} 张原图</span></div><div id="medPhotoLarge" class="med-photo-large"></div><div id="medPhotoThumbs" class="med-photo-thumbs">${medicationImages.map((att,index)=>`<button type="button" data-med-preview-index="${index}" aria-label="查看 ${esc(att.filename)}">${(att.mime_type||'').startsWith('image/')?`<img src="${esc(att.content_url)}" alt="">`:'<span class="file-glyph">▤</span>'}<small>${esc(att.filename)}</small></button>`).join('')}</div><div class="med-detail-section"><h5>包装记录</h5>${(med.packages||[]).map(item=>`<button class="med-record" type="button" data-document="${esc(item.document_id)}"><strong>${esc(item.batch_number||'批号待确认')}</strong><span>有效期 ${esc(item.expiry_date||'待确认')} · ${esc(item.quantity_raw||'数量待确认')}</span><b>查看来源 →</b></button>`).join('')||'<div class="empty compact-empty">暂无包装记录</div>'}</div><div class="med-detail-section"><h5>处方与资料来源</h5>${docs.map(doc=>`<button class="med-record" type="button" data-document="${esc(doc.id)}"><strong>${esc(doc.title||'原始资料')}</strong><span>${esc(doc.primary_date||'日期待确认')}</span><b>查看原件 →</b></button>`).join('')||'<div class="empty compact-empty">暂无来源资料</div>'}</div><div class="med-detail-section"><h5>用药状态历史</h5>${(med.events||[]).map(event=>`<div class="med-record static"><strong>${esc(event.event_date)} · ${esc(event.from_status)} → ${esc(event.to_status)}</strong><span>${esc([event.dose_each_time,event.frequency,event.timing,event.note].filter(Boolean).join(' · ')||'无补充说明')}</span></div>`).join('')||'<div class="empty compact-empty">暂无用户状态事件</div>'}</div></section>`;
      renderMedicationPreview(0);
    }catch(error){if(sameOwner(owner)&&state.medicationDetailId===id)$('medDetailBody').innerHTML=`<div class="empty">${esc(errorText(error))}</div>`}
  }
  window.openMedicationDetail=openMedicationDetail;
  function returnFromMedicationDetail(){
    if(state.medicationDetailPushed&&location.hash.startsWith('#medication/')){state.medicationDetailPushed=false;history.back()}
    else showView('drugs',{refresh:false,restoreScroll:true});
  }

  $('metricEntryDate').value=today();
  document.addEventListener('click',event=>{
    const year=event.target.closest('[data-archive-year]');
    if(year){openArchiveCollection('year',year.dataset.archiveYear);return}
    const type=event.target.closest('[data-archive-type]');
    if(type){openArchiveCollection('type',type.dataset.archiveType);return}
    if(event.target.closest('#archiveCollectionClear'))showView('archive',{refresh:false});
  });
  $('quickMetricRaw').addEventListener('input',parseQuickMetric);
  $('quickMetricForm').addEventListener('submit',saveQuickMetric);
  $('metricEntryForm').addEventListener('submit',saveMetricEntry);
  $('customMetricForm').addEventListener('submit',saveCustomMetric);
  $('customMetricType').addEventListener('change',()=>{$('customMetricPair').classList.toggle('hidden',$('customMetricType').value!=='pair')});
  $('metricEntryMetric').addEventListener('change',syncMetricForm);
  $('metricEntryRaw').addEventListener('input',parseRawEntry);
  $('refreshMetrics').addEventListener('click',loadMetrics);
  $('refreshCosts').addEventListener('click',loadCosts);
  $('costYear').addEventListener('change',loadCosts);
  $('costKnown').addEventListener('change',loadCosts);
  $('costStatus').addEventListener('change',loadCosts);
  $('refreshOgtt').addEventListener('click',loadOgtt);
  $('ogttForm').addEventListener('submit',saveOgtt);
  $('reviewOwnership').addEventListener('click',openOwnershipReview);
  $('closeOwnership').addEventListener('click',()=>ownershipDialog.close());
  $('cancelOwnership').addEventListener('click',()=>ownershipDialog.close());
  $('ownershipSelectAll').addEventListener('change',event=>document.querySelectorAll('#ownershipList [data-ownership-id]').forEach(input=>{input.checked=event.target.checked}));
  $('confirmOwnership').addEventListener('click',confirmOwnership);
  $('metricDetailBack').addEventListener('click',returnFromMetricDetail);
  $('manageOverviewMetrics').addEventListener('click',()=>{renderDashboardMetricManager();$('dashboardMetricDialog').showModal();$('dashboardMetricSearch').focus()});
  $('closeDashboardMetrics').addEventListener('click',()=>$('dashboardMetricDialog').close());
  $('dashboardMetricSearch').addEventListener('input',renderDashboardMetricManager);
  $('metricDetailRecord').addEventListener('click',()=>openMetricRecord(state.metricDetailId));
  $('metricDetailPeriods').addEventListener('click',event=>{const button=event.target.closest('[data-period]');if(!button)return;state.metricDetailPeriod=button.dataset.period;renderMetricDetail()});
  $('metricDetailTrend').addEventListener('pointermove',event=>{const point=event.target.closest?.('[data-chart-point]');if(point)showMetricPoint(point);else hideMetricPoints()});
  $('metricDetailTrend').addEventListener('pointerleave',hideMetricPoints);
  $('metricDetailTrend').addEventListener('focusin',event=>{const point=event.target.closest?.('[data-chart-point]');if(point)showMetricPoint(point)});
  $('metricDetailTrend').addEventListener('focusout',hideMetricPoints);
  document.body.addEventListener('click',event=>{
    const follow=event.target.closest('[data-follow-id]');
    if(follow)toggleFollow(follow.dataset.followId,follow.dataset.version);
    const dashboard=event.target.closest('[data-dashboard-id]');
    if(dashboard)setDashboardVisibility(dashboard.dataset.dashboardId,dashboard.dataset.dashboardNext==='true');
    const detailMetric=event.target.closest('[data-metric-detail]');
    if(detailMetric){if($('dashboardMetricDialog').open)$('dashboardMetricDialog').close();openMetricDetail(detailMetric.dataset.metricDetail)}
    const recordMetric=event.target.closest('[data-metric-record]');
    if(recordMetric)openMetricRecord(recordMetric.dataset.metricRecord);
    const metric=event.target.closest('[data-metric-id]');
    if(metric){state.pendingMetricId=metric.dataset.metricId;requestAnimationFrame(()=>loadMetricResults(metric.dataset.metricId))}
    const med=event.target.closest('[data-med-detail]');
    if(med)openMedicationDetail(med.dataset.medDetail);
    const preview=event.target.closest('[data-med-preview-index]');
    if(preview)renderMedicationPreview(Number(preview.dataset.medPreviewIndex));
    if(event.target.closest('[data-close-metric-record]'))metricRecordDialog.close();
    const duplicate=event.target.closest('[data-receipt-duplicate]');
    if(duplicate){const select=document.querySelector(`[data-duplicate-target="${duplicate.dataset.receiptDuplicate}"]`);updateReceiptStatus(duplicate.dataset.receiptDuplicate,duplicate.dataset.version,'duplicate',select?.value||null)}
    const restore=event.target.closest('[data-receipt-restore]');
    if(restore)updateReceiptStatus(restore.dataset.receiptRestore,restore.dataset.version,'active');
  });
  $('medDetailBack').addEventListener('click',returnFromMedicationDetail);
})();
