const {test,expect}=require('@playwright/test');
const path=require('path');
const fs=require('fs');

test('cross-hospital care uses related link without changing the document visit',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const document={id:'d1',document_type:'挂号单 / 就诊单',title:'合成肿瘤医院门诊',primary_date:'2026-09-08',
    hospital:'合成肿瘤医院',department:null,doctor:null,amount:null,key_information:[],parsed_content:null,
    encounter_id:null,version:1,patient_scope:'self',type_specific_data:{}};
  const visit={id:'v1',title:'合成手术就诊',hospital:'合成肺科医院',date:'2026-08-13',related_document_ids:[]};
  await page.route('https://care.test/**',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname;
    if(p.startsWith('/api/')){
      if(p==='/api/documents/d1/related-encounters/v1'&&request.method()==='PUT'){
        visit.related_document_ids=['d1'];return route.fulfill({json:{document_id:'d1',encounter_id:'v1'}});
      }
      const result=p==='/api/system/status'?{model:{configured:true}}:
        p==='/api/auth/me'?{id:'u1',email:'tester@example.test',role:'admin'}:
        p==='/api/overview'?{documents:{total:1,dated:1},hospitals:1,latest_date:'2026-09-08',types:[],months:[]}:
        p==='/api/costs/summary'?{receipts:{total:0},totals_by_currency:[],years:[],undated:{},excluded_count:0}:
        p==='/api/metrics'||p==='/api/metric-entries'||p==='/api/drafts'||p==='/api/medications'||p==='/api/batches'||p==='/api/care-topics'?{items:[]}:
        p==='/api/care-history'?{summary:{event_count:1,hospital_count:1,latest_date:'2026-08-13',undated_count:0,pending_count:0},recent:[],older_months:[],hospitals:['合成肺科医院']}:
        p==='/api/encounters'?{items:[visit]}:
        p==='/api/documents'?{items:[document],next_cursor:null}:
        p==='/api/documents/d1'?{...document,lab_results:[],attachments:[],extraction_metadata:{},receipt:null}:{items:[]};
      return route.fulfill({json:result});
    }
    const file=path.join(__dirname,'../../app/web',p==='/'?'index.html':path.basename(p));
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('https://care.test/#document/d1');
  await expect(page.locator('#view-detail')).toBeVisible();
  await expect(page.locator('#documentVisitSelect option[value="v1"]')).toHaveCount(0);
  await page.locator('#relatedVisitSelect').selectOption('v1');
  await page.locator('#addRelatedVisit').click();
  await expect(page.locator('.related-visit-list')).toContainText('合成手术就诊');
  await expect(page.locator('#documentVisitSelect')).toHaveValue('');
  await expect(page.locator('.related-visit-list')).toContainText('合成手术就诊');
  expect(errors).toEqual([]);
});
