const {test,expect}=require('@playwright/test');
const path=require('path');
const fs=require('fs');

test.beforeEach(async({page})=>{
  page.__posts=[];const errors=[];page.on('pageerror',e=>errors.push(e.message));page.__errors=errors;
  await page.route('https://archive.test/**',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname;
    if(p.startsWith('/api/')){
      if(p==='/api/overview'&&page.__overviewGate)await page.__overviewGate;
      if(request.method()==='POST'||request.method()==='PATCH')page.__posts.push({path:p,body:request.postDataJSON()});
      const data=p==='/api/system/status'?{model:{configured:true}}:
        p==='/api/auth/me'?{id:'u1',email:'tester@example.test',role:'admin'}:
        p==='/api/overview'?{documents:{total:106,dated:105,undated:1},hospitals:3,latest_date:'2026-09-10',types:[{type:'检验报告',count:15}],months:[{month:'2026-09',count:6}],metrics:[{id:'m1',key:'fasting_glucose',name:'空腹血糖',group:'血糖',record_type:'numeric',unit:'mmol/L',followed:true,version:1,latest_result:'4.9 mmol/L',latest_date:'2026-09-10',record_count:2,trend_axis:'dates',trend_series:[{key:'unit:mmol/l',unit:'mmol/L',points:[{x:'2026-08-01',y:'5.2'},{x:'2026-09-10',y:'4.9'}]}],manual_entry_allowed:true,excluded:{}}],ownership:page.__ownership||{unconfirmed_documents:0,unconfirmed_lab_results:0},pending_test_group_count:0}:
        p==='/api/costs/summary'?{receipts:{total:2,known_amount:1,unknown_amount:1},totals_by_currency:[{currency:'CNY',total:'0.00',known_count:1,unknown_count:1}],years:[{year:'2026',totals:[]}],undated:{known_count:0,unknown_count:0},excluded_count:1}:
        p==='/api/costs/receipts'?(url.searchParams.get('cursor')==='100'?{items:[{document_id:'d2',title:'第二页票据',primary_date:null,hospital:null,amount:null,currency:'CNY'}],next_cursor:null,total:101}:{items:[{document_id:'d1',title:'合成票据',primary_date:'2026-01-01',hospital:'合成医院',amount:'0.00',currency:'CNY'}],next_cursor:100,total:101}):
        p==='/api/metrics'?{items:[{id:'m1',key:'fasting_glucose',name:'空腹血糖',group:'血糖',record_type:'numeric',unit:'mmol/L',aliases:[],component_labels:[],followed:true,sort_order:10,preset:true,version:1}]}:
        p==='/api/metric-entries'?{items:[],next_cursor:null}:
        p==='/api/metrics/m1/results'?{metric:{id:'m1',key:'fasting_glucose',name:'空腹血糖',group:'血糖',record_type:'numeric',unit:'mmol/L'},items:[{id:'r1',source_type:'lab_report',source_id:'d1',record_date:'2026-09-10',raw_value:'4.9',value1:'4.9',value2:null,unit:'mmol/L',comparison_group:'unit:mmol/l',condition:'空腹',reference_range:'3.9–6.1',flag:null,timepoint_minutes:null},{id:'r2',source_type:'lab_report',source_id:'d2',record_date:'2026-08-01',raw_value:'5.2',value1:'5.2',value2:null,unit:'mmol/L',comparison_group:'unit:mmol/l',condition:'空腹',reference_range:'3.9–6.1',flag:null,timepoint_minutes:null}],excluded:{}}:
        p==='/api/test-sessions'?{items:[{id:'s1',name:'混合检验项试验',session_date:'2026-09-11',hospital:'合成医院',version:1,points:[{lab_result_id:'g0',document_id:'d1',analyte_key:'glucose',name:'葡萄糖',timepoint_minutes:0,raw_value:'5.1',value:'5.1',unit:'mmol/L'},{lab_result_id:'g120',document_id:'d1',analyte_key:'glucose',name:'葡萄糖',timepoint_minutes:120,raw_value:'7.2',value:'7.2',unit:'mmol/L'},{lab_result_id:'i0',document_id:'d1',analyte_key:'insulin',name:'胰岛素',timepoint_minutes:0,raw_value:'8',value:'8',unit:'mIU/L'},{lab_result_id:'i120',document_id:'d1',analyte_key:'insulin',name:'胰岛素',timepoint_minutes:120,raw_value:'22',value:'22',unit:'mIU/L'}]}]}:
        p==='/api/test-sessions/candidates'?{items:[{id:'l1',document_id:'d1',document_title:'合成 OGTT',name:'葡萄糖',raw_value:'5.1',unit:'mmol/L',timepoint_minutes:0,observed_date:'2026-09-11',hospital:'合成医院'}]}:
        p==='/api/documents/d1'||p==='/api/documents/d2'?{id:p.slice(-2),document_type:'检验报告',title:'合成血糖报告',primary_date:'2026-09-10',primary_date_raw:null,hospital:'合成医院',department:'检验科',doctor:null,amount:null,key_information:[],parsed_content:null,encounter_id:null,version:1,patient_scope:'self',type_specific_data:{},lab_results:[],attachments:[],extraction_metadata:{},receipt:null}:
        p==='/api/documents'?{items:page.__docs||[],next_cursor:null}:
        p==='/api/drafts'||p==='/api/medications'||p==='/api/encounters'||p==='/api/batches'?{items:[]}:
        request.method()==='POST'?{id:'created'}:{items:[]};
      return route.fulfill({json:data});
    }
    const file=path.join(__dirname,'../../app/web',url.pathname==='/'?'index.html':path.basename(url.pathname));
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('https://archive.test/');
});

test('overview header and summary appear while the archive is still loading',async({page})=>{
  let releaseDocuments;
  const documentsGate=new Promise(resolve=>{releaseDocuments=resolve});
  await page.route('https://archive.test/api/documents?*',async route=>{
    await documentsGate;
    await route.fulfill({json:{items:[],next_cursor:null}});
  });
  try{
    await page.reload();
    await expect(page.locator('#pageTitle')).toHaveText('数据概览');
    await expect(page.locator('#overviewDocuments')).toHaveText('106');
  }finally{
    releaseDocuments();
  }
});

test('overview year and type open complete archive collections and keep the filter after viewing a document',async({page})=>{
  page.__docs=[
    {id:'d1',title:'甲检查',document_type:'检查报告',primary_date:'2022-03-04',key_information:[]},
    {id:'d2',title:'乙检验',document_type:'检验报告',primary_date:'2022-11-08',key_information:[]},
    {id:'d3',title:'丙检查',document_type:'检查报告',primary_date:'2023-02-01',key_information:[]},
    {id:'d4',title:'待定票据',document_type:'医疗发票 / 收费单',primary_date:null,key_information:[]},
  ];
  await page.route('https://archive.test/api/overview',route=>route.fulfill({json:{
    documents:{total:4,dated:3,undated:1},hospitals:1,latest_date:'2023-02-01',
    months:[{month:'2022-03',count:1},{month:'2022-11',count:1},{month:'2023-02',count:1}],
    types:[{type:'检查报告',count:2},{type:'检验报告',count:1},{type:'医疗发票 / 收费单',count:1}],
    metrics:[],ownership:{unconfirmed_documents:0,unconfirmed_lab_results:0},
  }}));
  await page.reload();

  await page.locator('[data-archive-year="2022"]').click();
  await expect(page).toHaveURL(/#archive\/year\/2022$/);
  await expect(page.locator('#archiveCollectionLabel')).toHaveText('2022年全部资料');
  await expect(page.locator('#archiveList [data-document]')).toHaveCount(2);
  await page.locator('#archiveList [data-document="d1"]').click();
  await expect(page.locator('#view-detail')).toBeVisible();
  await page.locator('#detailBack').click();
  await expect(page.locator('#archiveList [data-document]')).toHaveCount(2);
  await expect(page).toHaveURL(/#archive\/year\/2022$/);

  await page.locator('[data-view="overview"]').first().click();
  await page.locator('[data-archive-type="检查报告"]').click();
  await expect(page.locator('#archiveCollectionLabel')).toContainText('检查报告');
  await expect(page.locator('#archiveList [data-document]')).toHaveCount(2);
  await page.reload();
  await expect(page.locator('#archiveList [data-document]')).toHaveCount(2);
  await page.locator('#archiveCollectionClear').click();
  await expect(page).toHaveURL(/#archive$/);
  await expect(page.locator('#archiveList [data-document]')).toHaveCount(4);
  await page.locator('[data-view="overview"]').first().click();
  await page.locator('[data-archive-type="医疗发票 / 收费单"]').click();
  await expect(page.locator('#archiveList [data-document]')).toHaveCount(1);
  await expect(page.locator('#archiveList [data-document="d4"]')).toBeVisible();
});

test('archived reports with unconfirmed ownership can be explicitly selected for trends',async({page})=>{
  page.__ownership={unconfirmed_documents:2,unconfirmed_lab_results:2};
  page.__docs=[
    {id:'d1',title:'报告一',document_type:'检验报告',hospital:'医院甲',primary_date:'2026-09-10',patient_scope:'unconfirmed',version:1,key_information:[]},
    {id:'d2',title:'报告二',document_type:'检验报告',hospital:'医院乙',primary_date:'2026-09-11',patient_scope:'unconfirmed',version:1,key_information:[]},
  ];
  await page.reload();
  await expect(page.locator('#overviewOwnership')).toContainText('2 份');
  await page.locator('#reviewOwnership').click();
  await expect(page.locator('#ownershipDialog')).toBeVisible();
  await page.locator('#ownershipSelectAll').check();
  await page.locator('#confirmOwnership').click();
  await expect.poll(()=>page.__posts.filter(x=>x.path.startsWith('/api/documents/')&&x.body.patient_scope==='self').length).toBe(2);
});

test('one confirmed report result is visible as a point without inventing a line',async({page})=>{
  const metric={id:'m1',key:'fasting_glucose',name:'空腹血糖',group:'血糖',record_type:'numeric',unit:'mmol/L',followed:true,version:1,latest_result:'4.9 mmol/L',latest_date:'2026-09-10',record_count:1,trend_axis:'dates',trend_series:[{key:'unit:mmol/l',unit:'mmol/L',points:[{x:'2026-09-10',y:'4.9'}]}],manual_entry_allowed:true,excluded:{}};
  await page.route('https://archive.test/api/overview',route=>route.fulfill({json:{documents:{total:1,dated:1,undated:0},hospitals:1,latest_date:'2026-09-10',types:[],months:[],metrics:[metric],ownership:{unconfirmed_documents:0,unconfirmed_lab_results:0}}}));
  await page.route('https://archive.test/api/metrics/m1/results',route=>route.fulfill({json:{metric,items:[{id:'r1',source_type:'lab_report',source_id:'d1',record_date:'2026-09-10',raw_value:'4.9',value1:'4.9',value2:null,unit:'mmol/L',comparison_group:'unit:mmol/l',condition:'空腹',reference_range:'3.9–6.1',flag:null,timepoint_minutes:null}],excluded:{}}}));
  await page.reload();
  await expect(page.locator('#overviewMetrics .metric-spark svg circle')).toHaveCount(1);
  await expect(page.locator('#overviewMetrics .metric-spark svg circle')).toHaveCSS('stroke','rgb(49, 95, 235)');
  await expect(page.locator('#overviewMetrics .metric-spark polyline')).toHaveCount(0);
  await page.locator('#overviewMetrics [data-metric-detail="m1"]').click();
  await expect(page.locator('#metricDetailTrend svg circle')).toHaveCount(1);
  await expect(page.locator('#metricDetailTrend svg polyline')).toHaveCount(0);
  await expect(page.locator('#metricDetailTrend .metric-y-tick')).not.toHaveCount(0);
  await page.locator('#metricDetailTrend [data-chart-point]').hover();
  await expect(page.locator('#metricDetailTrend .metric-chart-tooltip')).toBeVisible();
  await expect(page.locator('#metricDetailTrend .metric-chart-tooltip')).toContainText('2026-09-10');
  await expect(page.locator('#metricDetailTrend .metric-chart-tooltip')).toContainText('4.9 mmol/L');
});

test('quick metric record dialog keeps labels, fields and action aligned',async({page})=>{
  await page.locator('[data-metric-record="m1"]').click();
  await expect(page.locator('#metricRecordDialog')).toBeVisible();
  await expect(page.locator('#quickMetricValueLabel')).toHaveText('数值');
  await expect(page.locator('#quickMetricRaw')).toHaveAttribute('placeholder','例如 5.6');
  const layout=await page.evaluate(()=>{
    const rect=element=>{const {left,right,bottom,width}=element.getBoundingClientRect();return {left,right,bottom,width}};
    const element=selector=>document.querySelector(selector);
    return {
      dialog:rect(element('#metricRecordDialog')),
      dateLabel:rect(element('#quickMetricDate').parentElement),
      raw:rect(element('#quickMetricRaw')),
      value:rect(element('#quickMetricValue1')),
      submit:rect(element('#quickMetricForm button[type="submit"]')),
    };
  });
  expect(layout.dateLabel.left-layout.dialog.left).toBeGreaterThanOrEqual(20);
  expect(layout.dialog.right-layout.submit.right).toBeGreaterThanOrEqual(20);
  expect(layout.value.width).toBeGreaterThanOrEqual(layout.raw.width*0.9);
  expect(layout.submit.bottom).toBeLessThanOrEqual(layout.dialog.bottom);
  await page.locator('[data-close-metric-record]').click();
  await page.evaluate(()=>{state.overview.metrics[0].record_type='pair';const metric=state.metrics.find(item=>item.id==='m1');if(metric)metric.record_type='pair'});
  await page.locator('[data-metric-record="m1"]').click();
  await expect(page.locator('#quickMetricValueLabel')).toHaveText('数值 1');
  await expect(page.locator('#quickMetricValue2')).toBeVisible();
  await expect(page.locator('#quickMetricRaw')).toHaveAttribute('placeholder','例如 120/80');
  await page.locator('[data-close-metric-record]').click();
  await page.evaluate(()=>{state.overview.metrics[0].record_type='qualitative';const metric=state.metrics.find(item=>item.id==='m1');if(metric)metric.record_type='qualitative'});
  await page.locator('[data-metric-record="m1"]').click();
  await expect(page.locator('#quickMetricNumbers')).toBeHidden();
  await expect(page.locator('#quickMetricText')).toBeVisible();
  await expect(page.locator('#quickMetricRaw')).toHaveAttribute('placeholder','例如 阴性');
});

test('overview keeps only the total and medical costs has the detailed breakdown',async({page})=>{
  await page.route('https://archive.test/api/costs/summary',route=>route.fulfill({json:{
    receipts:{total:3,known_amount:3,unknown_amount:0},
    totals_by_currency:[{currency:'CNY',total:'780.80',known_count:3,unknown_count:0}],
    payments_by_currency:[{currency:'CNY',insurance_total:'100.00',insurance_count:2,personal_total:'680.80',personal_count:3}],
    years:[{year:'2026',totals:[{currency:'CNY',total:'680.80',known_count:2,unknown_count:0}]},{year:'2025',totals:[{currency:'CNY',total:'100.00',known_count:1,unknown_count:0}]}],
    undated:{known_count:0,unknown_count:0},excluded_count:0,
  }}));
  await page.reload();
  await expect(page.locator('#overviewCostTotal')).toHaveText('¥780.80');
  await expect(page.locator('#view-overview .overview-expense-panel')).toHaveCount(0);
  await page.locator('.nav [data-view="costs"]').click();
  await expect(page.locator('#view-costs')).toBeVisible();
  await expect(page).toHaveURL(/#costs$/);
  await expect(page.locator('#overviewExpenseTotal')).toHaveText('¥780.80');
  await expect(page.locator('#overviewCosts')).toContainText('医保支付');
  await expect(page.locator('#overviewCosts')).toContainText('¥680.80');
  await expect(page.locator('#overviewExpenseYears .overview-year-bar')).toHaveCount(2);
  await expect(page.locator('#costSummary')).toContainText('金额已知');
  expect(page.__errors).toEqual([]);
  await expect(page.locator('#toast')).not.toContainText('Cannot set properties of null');
});

test('different currencies remain separate in the overview total',async({page})=>{
  await page.route('https://archive.test/api/costs/summary',route=>route.fulfill({json:{
    receipts:{total:3,known_amount:3,unknown_amount:0},
    totals_by_currency:[
      {currency:'CNY',total:'780.80',known_count:2,unknown_count:0},
      {currency:'USD',total:'10.00',known_count:1,unknown_count:0},
    ],
    payments_by_currency:[],years:[],undated:{known_count:0,unknown_count:0},excluded_count:0,
  }}));
  await page.reload();
  await expect(page.locator('#overviewCostTotal')).toHaveText('¥780.80 / USD 10.00');
});

test.afterEach(async({page})=>expect(page.__errors).toEqual([]));

test('overview shows direct trends and optional quick entry',async({page})=>{
  await expect(page.locator('#view-overview')).toBeVisible();
  await expect(page.locator('#overviewDocuments')).toHaveText('106');
  await expect(page.locator('#overviewCostTotal')).toHaveText('¥0.00');
  await expect(page.locator('.nav [data-view]')).toHaveCount(6);
  await expect(page.locator('.nav [data-view="costs"]')).toHaveCount(1);
  await expect(page.locator('.nav [data-view="metrics"],.nav [data-view="ogtt"]')).toHaveCount(0);
  await expect(page.locator('#overviewMetrics')).toContainText('空腹血糖');
  await expect(page.locator('#overviewMetrics .metric-spark svg')).toHaveCount(1);

  await page.locator('[data-metric-record="m1"]').click();
  await expect(page.locator('#metricRecordDialog')).toBeVisible();
  await page.locator('#quickMetricDate').fill('2026-09-12');
  await page.locator('#quickMetricRaw').fill('0');
  await page.locator('#quickMetricForm button[type="submit"]').click();
  await expect.poll(()=>page.__posts.some(x=>x.path==='/api/metric-entries'&&x.body.value1==='0')).toBeTruthy();

  await page.locator('#overviewMetrics [data-metric-detail="m1"]').click();
  await expect(page.locator('#view-metric-detail')).toBeVisible();
  await expect(page).toHaveURL(/#metric\/m1$/);
  await expect(page.locator('#metricDetailTrend svg')).toHaveCount(1);
  await expect(page.locator('.metric-line-primary')).toHaveCSS('stroke','rgb(49, 95, 235)');
  await expect(page.locator('#metricDetailTrend .metric-y-tick')).toHaveCount(3);
  await expect(page.locator('#metricDetailTrend .metric-x-tick')).toHaveCount(2);
  await page.locator('#metricDetailTrend [data-chart-point]').first().hover();
  await expect(page.locator('#metricDetailTrend .metric-chart-tooltip')).toBeVisible();
  await expect(page.locator('#metricDetailTrend .metric-chart-tooltip')).toContainText('2026-08-01');
  await expect(page.locator('#metricDetailTrend .metric-chart-tooltip')).toContainText('5.2 mmol/L');
  await page.locator('#metricDetailTrend [data-chart-point]').last().focus();
  await expect(page.locator('#metricDetailTrend .metric-chart-tooltip')).toBeVisible();
  await expect(page.locator('#metricDetailTrend .metric-chart-tooltip')).toContainText('2026-09-10');
  await expect(page.locator('#metricDetailHistory')).toContainText('3.9–6.1');
  await expect(page.locator('#metricDetailHistory')).toContainText('查看并修正来源');
  await page.locator('#metricDetailHistory [data-document="d1"]').click();
  await expect(page.locator('#view-detail')).toBeVisible();
  await page.locator('#detailBack').click();
  await expect(page.locator('#view-metric-detail')).toBeVisible();
  await page.locator('#metricDetailBack').click();
  await expect(page.locator('#view-overview')).toBeVisible();
});

test('overview metric manager searches, adds and removes text results without a curve',async({page})=>{
  const definitions=[
    {id:'m1',key:'fasting_glucose',name:'空腹血糖',group:'血糖',record_type:'numeric',unit:'mmol/L',aliases:[],dashboard_visible:true,version:1,sort_order:10},
    {id:'m2',key:'lab:screen',name:'结核分枝杆菌',group:'其他检验指标',record_type:'qualitative',unit:null,aliases:[],dashboard_visible:false,version:1,sort_order:1000},
  ];
  const summary=item=>({...item,latest_result:item.id==='m1'?'4.9 mmol/L':'阴性',latest_date:'2026-09-10',record_count:2,trend_series:item.id==='m1'?[{key:'unit:mmol/l',points:[{x:'2026-09-10',y:'4.9'}]}]:[],manual_entry_allowed:true});
  await page.route('https://archive.test/api/metrics',route=>route.fulfill({json:{items:definitions}}));
  await page.route('https://archive.test/api/overview',route=>route.fulfill({json:{documents:{total:2,dated:2,undated:0},hospitals:1,latest_date:'2026-09-10',types:[],months:[],metrics:definitions.filter(item=>item.dashboard_visible).map(summary),metric_catalog:definitions.map(summary),ownership:{unconfirmed_documents:0,unconfirmed_lab_results:0}}}));
  await page.route(/https:\/\/archive\.test\/api\/metrics\/m[12]$/,route=>{
    const id=route.request().url().split('/').pop(),metric=definitions.find(item=>item.id===id),body=route.request().postDataJSON();
    metric.dashboard_visible=body.dashboard_visible;metric.version++;
    return route.fulfill({json:metric});
  });
  await page.route('https://archive.test/api/metrics/m2/results',route=>route.fulfill({json:{items:[
    {id:'r1',source_type:'lab_report',source_id:'d1',record_date:'2026-09-10',raw_value:'阴性',value1:null,value2:null,unit:null,comparison_group:null},
    {id:'r2',source_type:'lab_report',source_id:'d2',record_date:'2026-09-10',raw_value:'阳性',value1:null,value2:null,unit:null,comparison_group:null},
  ],excluded:{}}}));
  await page.reload();
  await expect(page.locator('#overviewMetrics .health-metric-row')).toHaveCount(1);
  await page.locator('#manageOverviewMetrics').click();
  await page.locator('#dashboardMetricSearch').fill('结核');
  await expect(page.locator('#dashboardMetricList .dashboard-metric-item')).toHaveCount(1);
  await page.locator('#dashboardMetricList [data-metric-detail="m2"]').click();
  await expect(page.locator('#metricDetailTrend')).toContainText('不绘制数值曲线');
  await expect(page.locator('#metricDetailHistory tr')).toHaveCount(2);
  await page.locator('#metricDetailBack').click();
  await page.locator('#manageOverviewMetrics').click();
  await page.locator('#dashboardMetricList [data-dashboard-id="m2"]').click();
  await expect(page.locator('#overviewMetrics')).toContainText('结核分枝杆菌');
  await expect(page.locator('#overviewMetrics .metric-spark svg')).toHaveCount(1);
  await expect(page.locator('#overviewMetrics')).toContainText('文字结果');
  await page.locator('#closeDashboardMetrics').click();
  await page.locator('#overviewMetrics [data-dashboard-id="m1"]').click();
  await expect(page.locator('#overviewMetrics .health-metric-row')).toHaveCount(1);
  await expect(page.locator('#overviewMetrics')).not.toContainText('空腹血糖');
});

test('document correction, version history and recoverable removal are available from detail',async({page})=>{
  let doc={id:'d1',document_type:'检验报告',title:'原报告',primary_date:'2026-09-10',
    hospital:'医院甲',department:'检验科',doctor:null,amount:null,key_information:[],
    parsed_content:null,version:1,patient_scope:'self',type_specific_data:{},lab_results:[],attachments:[],receipt:null,deleted_at:null};
  page.__docs=[doc];
  await page.route('https://archive.test/api/documents/d1',async route=>{
    if(route.request().method()==='PATCH'){
      const payload=route.request().postDataJSON();
      doc={...doc,...payload,version:doc.version+1};
      return route.fulfill({json:doc});
    }
    return route.fulfill({json:doc});
  });
  await page.route('https://archive.test/api/documents/d1/trash',route=>{
    doc={...doc,deleted_at:'2026-09-24T12:00:00Z',version:doc.version+1};
    return route.fulfill({json:doc});
  });
  await page.route('https://archive.test/api/documents/d1/restore',route=>{
    doc={...doc,deleted_at:null,version:doc.version+1};
    return route.fulfill({json:doc});
  });
  await page.reload();
  await page.locator('[data-view="archive"]').first().click();
  await page.locator('#archiveList [data-document="d1"]').click();
  await page.locator('#documentEditBtn').click();
  await page.locator('#recordEditForm [name="title"]').fill('修正后的报告');
  await page.locator('#recordEditForm button[type="submit"]').click();
  await expect(page.locator('#detailTitle')).toHaveText('修正后的报告');
  page.on('dialog',dialog=>dialog.accept());
  await page.locator('#documentTrashBtn').click();
  await expect(page.locator('#documentRestoreBtn')).toBeVisible();
  await page.locator('#documentRestoreBtn').click();
  await expect(page.locator('#documentEditBtn')).toBeVisible();
  expect(page.__errors).toEqual([]);
});

test('manual metric entry can be corrected, moved to trash and restored',async({page})=>{
  let entry={id:'e1',metric_id:'m1',record_date:'2026-09-10',raw_value:'4.9',value1:'4.9',
    value2:null,text_value:null,unit:'mmol/L',condition:'空腹',version:1,voided:false};
  await page.route('https://archive.test/api/metric-entries?*',route=>{
    const onlyVoided=new URL(route.request().url()).searchParams.get('voided')==='true';
    return route.fulfill({json:{items:entry.voided===onlyVoided?[entry]:[],next_cursor:null}});
  });
  await page.route('https://archive.test/api/metric-entries/e1',route=>{
    const update=route.request().postDataJSON();
    entry={...entry,...update,version:entry.version+1};
    return route.fulfill({json:entry});
  });
  await page.route('https://archive.test/api/metrics/m1/results',route=>route.fulfill({json:{
    metric:{id:'m1',key:'fasting_glucose',name:'空腹血糖',group:'血糖',record_type:'numeric',unit:'mmol/L'},
    items:entry.voided?[]:[{...entry,source_type:'manual',source_id:'e1',comparison_group:'unit:mmol/l'}],excluded:{},
  }}));
  await page.reload();
  await page.locator('#overviewMetrics [data-metric-detail="m1"]').click();
  await page.locator('[data-edit-entry="e1"]').click();
  await page.locator('#recordEditForm [name="raw_value"]').fill('5.3');
  await page.locator('#recordEditForm [name="value1"]').fill('5.3');
  await page.locator('#recordEditForm button[type="submit"]').click();
  await expect(page.locator('#metricDetailHistory')).toContainText('5.3');
  page.on('dialog',dialog=>dialog.accept());
  await page.locator('[data-trash-entry="e1"]').click();
  await expect(page.locator('#metricDetailHistory')).toContainText('暂无历史结果');
  await page.locator('#metricEntryTrashBtn').click();
  await page.locator('[data-restore-entry="e1"]').click();
  await expect(page.locator('#metricDetailHistory')).toContainText('5.3');
  expect(page.__errors).toEqual([]);
});

test('dense dates keep readable axis ticks while every point remains inspectable',async({page})=>{
  const items=['2022-05-01','2022-05-15','2022-06-01','2023-07-01','2023-07-02','2024-07-01','2024-09-01','2025-03-01','2025-07-01','2026-07-01'].map((date,index)=>({id:`r${index}`,source_type:'lab_report',source_id:'d1',record_date:date,raw_value:String(4+index/10),value1:String(4+index/10),value2:null,unit:'mmol/L',comparison_group:'unit:mmol/l',condition:'空腹',timepoint_minutes:null}));
  await page.route('https://archive.test/api/metrics/m1/results',route=>route.fulfill({json:{metric:{id:'m1',name:'空腹血糖'},items,excluded:{}}}));
  await page.locator('#overviewMetrics [data-metric-detail="m1"]').click();
  await expect(page.locator('#metricDetailTrend [data-chart-point]')).toHaveCount(10);
  const ticks=page.locator('#metricDetailTrend .metric-x-tick');
  await expect(ticks).not.toHaveCount(10);
  expect(await ticks.count()).toBeLessThanOrEqual(6);
  const boxes=await ticks.evaluateAll(nodes=>nodes.map(node=>node.getBoundingClientRect().left));
  for(let index=1;index<boxes.length;index++)expect(boxes[index]-boxes[index-1]).toBeGreaterThan(65);
});

test('lipid component charts identify their distinct analytes',async({page})=>{
  const metric={id:'m1',key:'blood_lipids',name:'血脂',group:'血脂',record_type:'group',unit:'mmol/L',followed:true,version:1,latest_result:'4.6 mmol/L',latest_date:'2026-09-10',record_count:2,trend_axis:'dates',trend_series:[],manual_entry_allowed:false,excluded:{}};
  const series=[['total_cholesterol','总胆固醇'],['triglycerides','甘油三酯'],['hdl_c','高密度脂蛋白胆固醇'],['ldl_c','低密度脂蛋白胆固醇']];
  const items=series.flatMap(([key,name],index)=>['2025-09-10','2026-09-10'].map((date,offset)=>({id:`${key}-${offset}`,source_type:'lab_report',source_id:'d1',record_date:date,raw_value:String(index+1+offset/10),value1:String(index+1+offset/10),value2:null,unit:'mmol/L',comparison_group:`series:${key}|unit:mmol/l`,series_key:key,condition:null,timepoint_minutes:null})));
  await page.route('https://archive.test/api/overview',route=>route.fulfill({json:{documents:{total:2,dated:2,undated:0},hospitals:1,latest_date:'2026-09-10',types:[],months:[],metrics:[metric],ownership:{unconfirmed_documents:0,unconfirmed_lab_results:0}}}));
  await page.route('https://archive.test/api/metrics',route=>route.fulfill({json:{items:[metric]}}));
  await page.route('https://archive.test/api/metrics/m1/results',route=>route.fulfill({json:{metric,items,excluded:{}}}));
  await page.reload();
  await page.locator('#overviewMetrics [data-metric-detail="m1"]').click();
  await expect(page.locator('#metricDetailTrend .metric-chart')).toHaveCount(4);
  const captions=await page.locator('#metricDetailTrend figcaption').allTextContents();
  for(const [,name] of series)expect(captions.some(caption=>caption.includes(name))).toBeTruthy();
});

test('medication workspace matches the reference structure and records a selected package',async({page})=>{
  const active={id:'med-active',name:'甲药',generic_name:'甲通用名',brand_name:null,strength:'10 mg',dosage_form:'片剂',route:'口服',status:'正在服用',dose_each_time:'1片',frequency:'每日两次',timing:'饭后',version:1,packages:[{id:'pack-active',expiry_date:'2027-06-01',batch_number:'A1',quantity_raw:'30片'}],sources:[]};
  const reserve={...active,id:'med-reserve',name:'乙药',status:'备用药',dose_each_time:null,frequency:null,timing:null,packages:[{id:'pack-reserve',expiry_date:'2026-10-01',batch_number:'B1',quantity_raw:'20片'}]};
  await page.route('https://archive.test/api/medications',route=>route.fulfill({json:{items:[active,reserve]}}));
  await page.route('https://archive.test/api/medications/med-reserve',route=>route.fulfill({json:{...reserve,sources:[{document_id:'med-doc',instructions:'原包装说明'}],events:[]}}));
  await page.route('https://archive.test/api/documents/med-doc',route=>route.fulfill({json:{id:'med-doc',title:'乙药包装',parsed_content:'原包装内容',attachments:[{id:'photo-1',filename:'正面.png',mime_type:'image/png',content_url:'data:image/png;base64,iVBORw0KGgo='},{id:'photo-2',filename:'底部.png',mime_type:'image/png',content_url:'data:image/png;base64,iVBORw0KGgo='}]}}));
  await page.reload();
  await page.locator('[data-view="drugs"]').first().click();
  await expect(page.locator('#view-drugs .drug-notice')).toContainText('个人药品资料管理');
  await expect(page.locator('#activeDrugCount')).toHaveText('1');
  await expect(page.locator('#soonDrugCount')).toHaveText('1');
  await expect(page.locator('#todayDrugPlan')).toContainText('甲药');
  await expect(page.locator('#drugSections .drug-section')).toHaveCount(3);
  await expect(page.locator('#drugSections .drug-card')).toHaveCount(2);
  await page.locator('[data-med-detail="med-reserve"]').click();
  await expect(page.locator('#view-medication-detail')).toBeVisible();
  await expect(page).toHaveURL(/#medication\/med-reserve$/);
  await expect(page.locator('#medPhotoThumbs button')).toHaveCount(2);
  await page.locator('#medPhotoThumbs button').last().click();
  await expect(page.locator('#medPhotoLarge img')).toHaveAttribute('alt','底部.png');
  await page.locator('#medDetailBack').click();
  await expect(page.locator('#view-drugs')).toBeVisible();
  await page.locator('[data-med-action="start"][data-med-id="med-reserve"]').click();
  await expect(page.locator('#medTitle')).toHaveText('开始用药 · 乙药');
  await expect(page.locator('#medMessage')).toContainText('确认个人实际用量与频次');
  await expect(page.locator('#medDate')).toHaveAttribute('type','date');
  await expect(page.locator('#medFrequency')).toHaveValue('每日 1 次');
  await expect(page.locator('#medFrequency option')).toHaveCount(6);
  await expect(page.locator('#medPlannedEnd')).toHaveAttribute('type','date');
  await expect(page.locator('#medPackageLabel')).toBeHidden();
  await expect(page.locator('#medPackage')).toHaveValue('pack-reserve');
  await page.locator('#medDose').fill('1片');
  await page.locator('#medFrequency').selectOption('每日 2 次');
  await page.locator('#medPlannedEnd').fill('2026-11-01');
  await page.locator('#medForm button[type="submit"]').click();
  await expect.poll(()=>page.__posts.find(item=>item.path==='/api/medications/med-reserve/events')?.body).toMatchObject({package_id:'pack-reserve',frequency:'每日 2 次',planned_end_date:'2026-11-01'});
  await page.locator('[data-med-action="pause"][data-med-id="med-active"]').click();
  await expect(page.locator('#medDateLabel')).toHaveText('暂停日期 *');
  await expect(page.locator('#startFields')).toBeHidden();
  await expect(page.locator('#medBoundary')).toBeHidden();
  await page.locator('#medCancel').click();
  await expect(page.locator('#medDialog')).not.toBeVisible();
});

test('late overview response cannot overwrite a newly signed-in account',async({page})=>{
  await expect(page.locator('#overviewDocuments')).toHaveText('106');
  let release;
  page.__overviewGate=new Promise(resolve=>{release=resolve});
  await page.evaluate(()=>{
    state.user={id:'account-a',email:'a@example.test',role:'user'};
    void window.loadOverview();
    state.user={id:'account-b',email:'b@example.test',role:'user'};
    state.overview={documents:{total:222,dated:222,undated:0},hospitals:2,latest_date:'2026-09-12'};
    document.getElementById('overviewDocuments').textContent='222';
  });
  release();
  await page.waitForTimeout(150);
  await expect(page.locator('#overviewDocuments')).toHaveText('222');
});
