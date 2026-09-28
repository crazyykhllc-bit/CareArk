const {test,expect}=require('@playwright/test');
const path=require('path');
const fs=require('fs');

test('switching archive members changes all data and persists after refresh',async({page})=>{
  const self='00000000-0000-4000-8000-000000000001';
  const parent='00000000-0000-4000-8000-000000000002';
  let active=self,created=false,requestedName;
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('https://archive.test/**',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname;
    if(p.startsWith('/api/')){
      let data;
      if(p==='/api/system/status')data={model:{configured:true}};
      else if(p==='/api/auth/me')data={id:self,email:'tester@example.test',role:'admin'};
      else if(p==='/api/profiles'&&request.method()==='GET')data={items:[{id:self,name:'我',is_self:true},...(created?[{id:parent,name:requestedName,is_self:false}]:[])],active_id:active};
      else if(p==='/api/profiles'&&request.method()==='POST'){created=true;requestedName=JSON.parse(request.postData()).name;data={id:parent,name:requestedName,is_self:false}}
      else if(p==='/api/profiles/active'){active=JSON.parse(request.postData()).profile_id;data={active:{id:active,name:active===self?'我':requestedName}}}
      else if(p==='/api/overview')data={documents:{total:active===self?1:0,dated:0,undated:0},hospitals:0,types:[],months:[]};
      else if(p==='/api/documents')data={items:active===self?[{id:'00000000-0000-4000-8000-000000000003',document_type:'门诊病历',title:'自己的旧资料',primary_date:null,patient_scope:'self',version:1,type_specific_data:{}}]:[],next_cursor:null};
      else data={items:[]};
      return route.fulfill({json:data});
    }
    const file=path.join(__dirname,'../../app/web',p==='/'?'index.html':path.basename(p));
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });

  await page.goto('https://archive.test/#upload');
  await expect(page.locator('#profileSwitcher')).toHaveValue(self);
  await expect(page.locator('#uploadProfileName')).toHaveText('我');
  await page.locator('#profileSwitcher').selectOption('__add__');
  await expect(page.locator('#profileCreateDialog')).toBeVisible();
  await expect(page.locator('#profileCreateDialog')).toContainText('兄弟姐妹');
  await page.locator('#profileCreateName').fill('姐姐');
  await page.locator('#profileCreateForm [type="submit"]').click();
  expect(requestedName).toBe('姐姐');
  await expect(page.locator('#profileSwitcher')).toHaveValue(parent);
  await expect(page.locator('#uploadProfileName')).toHaveText('姐姐');
  await expect(page.locator('#overviewDocuments')).toContainText('0');
  await page.reload();
  await expect(page.locator('#profileSwitcher')).toHaveValue(parent);
  await page.locator('#profileSwitcher').selectOption(self);
  await expect(page.locator('#profileSwitcher')).toHaveValue(self);
  await expect(page.locator('#uploadProfileName')).toHaveText('我');
  await expect(page.locator('#overviewDocuments')).toContainText('1');
  expect(errors).toEqual([]);
});

for(const width of [320,640,1440]){
  test(`profile switcher stays in the viewport at ${width}px`,async({page})=>{
    await page.setViewportSize({width,height:720});
    await page.route('https://archive.test/**',route=>{
      const p=new URL(route.request().url()).pathname;
      if(p.startsWith('/api/'))return route.fulfill({json:p==='/api/system/status'?{model:{configured:true}}:p==='/api/auth/me'?{id:'self',email:'tester@example.test',role:'admin'}:p==='/api/profiles'?{items:[{id:'self',name:'我',is_self:true},{id:'parent',name:'妈妈',is_self:false}],active_id:'self'}:{items:[]}});
      const file=path.join(__dirname,'../../app/web',p==='/'?'index.html':path.basename(p));
      return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
    });
    await page.goto('https://archive.test/#upload');
    await expect(page.locator('#profileSwitcher')).toBeVisible();
    const rect=await page.locator('.profile-switcher').boundingBox();
    expect(rect.x).toBeGreaterThanOrEqual(0);
    expect(rect.x+rect.width).toBeLessThanOrEqual(width+1);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width+1);
  });
}
