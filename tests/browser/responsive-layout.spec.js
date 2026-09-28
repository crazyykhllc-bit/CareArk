const {test,expect}=require('@playwright/test');
const path=require('path');
const fs=require('fs');

test.beforeEach(async({page})=>{
  page.__errors=[];page.on('pageerror',error=>page.__errors.push(error.message));
  await page.route('https://archive.test/**',route=>{
    const p=new URL(route.request().url()).pathname;
    if(p.startsWith('/api/'))return route.fulfill({json:p==='/api/system/status'?{model:{configured:true,fallback_configured:true,fallback2_configured:true}}:p==='/api/auth/me'?{id:'u1',email:'tester@example.test',role:'admin'}:{items:[]}});
    const file=path.join(__dirname,'../../app/web',p==='/'?'index.html':path.basename(p));
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
});
test.afterEach(async({page})=>expect(page.__errors).toEqual([]));

// Browser zoom reduces the CSS viewport: 1920 / 2 = 960, 1920 / 3 = 640.
// This matrix tests that layout effect; deviceScaleFactor alone would not test it.
for(const [width,height] of [[1920,1080],[1536,864],[1280,720],[1097,617],[960,540],[768,432],[640,360],[320,640],[390,844]]){
  test(`navigation and upload reflow at CSS viewport ${width} x ${height}`,async({page})=>{
    await page.setViewportSize({width,height});
    await page.goto('https://archive.test/#upload');
    await expect(page.locator('#uploadIntent')).toBeVisible();
    const layout=await page.evaluate(()=>{
      const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
      const sidebar=document.querySelector('.sidebar'),main=document.querySelector('main');
      return {sidebar:rect(sidebar),main:rect(main),nav:[...document.querySelectorAll('.sidebar .nav-btn')].map(el=>({rect:rect(el),nowrap:getComputedStyle(el).whiteSpace,overflow:el.scrollWidth>el.clientWidth+1})),overflow:document.documentElement.scrollWidth>innerWidth+1,status:getComputedStyle(document.querySelector('.system-state')).display};
    });
    expect(layout.overflow).toBe(false);
    expect(layout.sidebar.width).toBeGreaterThan(0);
    expect(layout.sidebar.right<=layout.main.x+1 || layout.sidebar.bottom<=layout.main.y+1).toBe(true);
    for(const nav of layout.nav){expect(nav.nowrap).toBe('nowrap');expect(nav.overflow).toBe(false);expect(nav.rect.height).toBeGreaterThanOrEqual(44)}
    expect(layout.status).not.toBe('none');
    for(const choice of await page.locator('[data-upload-intent]').all()){
      const bounds=await choice.boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(width+1);
    }
    await expect(page.locator('#uploadForm')).not.toBeVisible();
    if([1920,960,640,390].includes(width))await page.screenshot({path:`test-results/upload-entry-${width}.png`,fullPage:true});
    await page.locator('[data-upload-intent="small"]').click();
    await expect(page.locator('#uploadForm')).toBeVisible();
    const overflow=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().width && el.getBoundingClientRect().right>innerWidth+1).map(el=>({tag:el.tagName,id:el.id,class:el.className,right:el.getBoundingClientRect().right})).slice(0,12));
    expect(overflow).toEqual([]);
    await page.locator('.sidebar [data-view="archive"]').click();
    await expect(page.locator('#view-archive')).toBeVisible();
    await page.locator('.sidebar [data-view="upload"]').click();
    await expect(page.locator('#uploadForm')).toBeVisible();
    await expect(page.locator('#logoutBtn')).toBeVisible();
    if([1920,960,640,390].includes(width))await page.screenshot({path:`test-results/upload-responsive-${width}.png`,fullPage:true});
  });
}

for(const width of [320,960]){
  test(`all primary pages remain within the viewport at ${width}`,async({page})=>{
    await page.setViewportSize({width,height:720});
    await page.goto('https://archive.test/#upload');
    for(const view of ['overview','home','upload','drugs','costs','archive']){
      await page.locator(`.sidebar [data-view="${view}"]`).click();
      await expect(page.locator(`#view-${view}`)).toBeVisible();
      const overflow=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().width && el.getBoundingClientRect().right>innerWidth+1).map(el=>({id:el.id,class:el.className,right:el.getBoundingClientRect().right})).slice(0,8));
      expect(overflow,view).toEqual([]);
    }
  });
}
