const {test,expect}=require('@playwright/test');
const path=require('path');
const fs=require('fs');

async function openAuth(page,{setupRequired=true,invite=false}={}){
  const submissions=[];
  await page.route('https://archive.test/**',async route=>{
    const request=route.request(),url=new URL(request.url()),pathname=url.pathname;
    if(pathname.startsWith('/api/')){
      if(request.method()==='POST'){
        submissions.push({pathname,body:JSON.parse(request.postData())});
        return route.fulfill({status:400,json:{detail:'测试请求已拦截'}});
      }
      if(pathname==='/api/system/status')return route.fulfill({json:{model:{configured:false}}});
      if(pathname==='/api/auth/me')return route.fulfill({status:401,json:{detail:'未登录'}});
      if(pathname==='/api/setup/status')return route.fulfill({json:{required:setupRequired}});
      return route.fulfill({json:{items:[]}});
    }
    const file=path.join(__dirname,'../../app/web',pathname==='/'?'index.html':path.basename(pathname));
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto(`https://archive.test/${invite?'?invite=sample-token':''}`);
  return submissions;
}

test('administrator setup compares both passwords before sending a request',async({page})=>{
  const submissions=await openAuth(page);
  await expect(page.locator('.auth-copy h1')).toHaveText('把散落的医疗资料，整理成清晰的个人健康档案。');
  await expect(page.locator('#authConfirmLabel')).toBeVisible();
  await page.locator('#authEmail').fill('owner@example.test');
  await page.locator('#authPassword').fill('Test-123');
  await page.locator('#authConfirmPassword').fill('Test-124');
  await page.locator('#authPasswordVisibility').click();
  await expect(page.locator('#authPassword')).toHaveAttribute('type','text');
  await expect(page.locator('#authConfirmPassword')).toHaveAttribute('type','text');
  await page.locator('#authSubmit').click();
  await expect(page.locator('#authError')).toContainText('密码不一致');
  expect(submissions).toHaveLength(0);
  await page.locator('#authConfirmPassword').fill('Test-123');
  await page.locator('#authSubmit').click();
  await expect.poll(()=>submissions.length).toBe(1);
  expect(submissions[0].pathname).toBe('/api/setup/admin');
  await page.locator('#authPasswordVisibility').click();
  await expect(page.locator('#authPassword')).toHaveAttribute('type','password');
  await expect(page.locator('#authConfirmPassword')).toHaveAttribute('type','password');
});

test('invited account registration also requires a match; login does not',async({page})=>{
  const submissions=await openAuth(page,{invite:true});
  await expect(page.locator('#authConfirmLabel')).toBeVisible();
  await expect(page.locator('#authEmail')).toHaveJSProperty('required',false);
  await page.locator('#authPassword').fill('Test-123');
  await page.locator('#authConfirmPassword').fill('Test-124');
  await page.locator('#authSubmit').click();
  expect(submissions).toHaveLength(0);
  await page.locator('#authConfirmPassword').fill('Test-123');
  await page.locator('#authSubmit').click();
  await expect.poll(()=>submissions.length).toBe(1);
  expect(submissions[0]).toEqual({pathname:'/api/auth/register/invitation',body:{token:'sample-token',password:'Test-123'}});
});

test('existing account login keeps a single password field',async({page})=>{
  await openAuth(page,{setupRequired:false});
  await expect(page.locator('#authConfirmLabel')).toBeHidden();
  await expect(page.locator('#authConfirmPassword')).toHaveJSProperty('required',false);
  await page.locator('#authPasswordVisibility').click();
  await expect(page.locator('#authPassword')).toHaveAttribute('type','text');
  await page.setViewportSize({width:760,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(760);
});
