const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.FRAME_BROWSER_PATH?{executablePath:process.env.FRAME_BROWSER_PATH}:{}),args:['--no-sandbox','--allow-file-access-from-files','--disable-dev-shm-usage','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('file://'+root+'/dist/index.html');await page.locator('#model option').first().waitFor({state:'attached'});
 await page.selectOption('#language','en');assert.equal(await page.locator('h1').textContent(),'AI Image & Video Studio');
 await page.click('#generate');assert.equal(await page.locator('#toast').textContent(),'Enter a scene description');
 await page.click('[data-preset="natural"]');await page.click('#generate');assert.equal(await page.locator('#toast').textContent(),'Select source media first');
 await page.click('#useDemo');await page.waitForFunction(()=>document.querySelector('#fileName').textContent.includes('coast'));
 await page.selectOption('#model','wan-cloud');assert.equal(await page.locator('#aspect').isDisabled(),true);
 await page.click('#setDefault');await page.click('[data-workflow="text-image"]');assert.equal(await page.locator('#sourceSection').isVisible(),false);assert.equal(await page.locator('#model').inputValue(),'flux-cloud');
 await page.click('[data-workflow="image-video"]');assert.equal(await page.locator('#model').inputValue(),'wan-cloud');
 await page.selectOption('#language','ar');assert.equal(await page.locator('html').getAttribute('dir'),'rtl');
 await page.selectOption('#language','en');await page.click('#localMode');await page.click('[data-workflow="text-image"]');
 await page.route('http://127.0.0.1:8000/**',async route=>{
  const url=route.request().url();const method=route.request().method();const base={status:200,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'},contentType:'application/json'};
  if(method==='OPTIONS')return route.fulfill({...base,body:'{}'});
  if(url.endsWith('/api/health'))return route.fulfill({...base,body:JSON.stringify({status:'ok',cuda:false})});
  if(url.endsWith('/api/jobs')&&method==='POST')return route.fulfill({...base,body:JSON.stringify({id:'contract-test'})});
  if(url.includes('/api/jobs/contract-test'))return route.fulfill({...base,body:JSON.stringify({status:'succeeded',seed:42,url:'/api/files/contract-test'})});
  if(url.includes('/api/files/contract-test'))return route.fulfill({...base,contentType:'image/webp',body:fs.readFileSync(root+'/dist/assets/demo-coast.webp')});
  return route.abort();
 });
 await page.click('#connection');await page.fill('#endpoint','http://127.0.0.1:8000');await page.click('#testConnection');await page.waitForFunction(()=>document.querySelector('#connectionMessage').textContent.includes('Connected'));await page.click('#saveConnection');
 await page.click('[data-preset="natural"]');await page.click('#generate');await page.waitForFunction(()=>!document.querySelector('#download').closest('[hidden]'));assert.equal(await page.locator('#resultTab').isDisabled(),false);assert.equal(await page.locator('#statusText').textContent(),'Complete');
 await page.click('#useResult');assert.equal(await page.locator('#sourceSection').isVisible(),true);assert.equal(await page.locator('#fileName').textContent(),'frame-generated.png');
 await page.selectOption('#language','en');await page.screenshot({path:process.env.FRAME_SCREENSHOT||'/tmp/frame-desktop.png',fullPage:true});
 const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});await mobile.goto('file://'+root+'/dist/index.html');await mobile.selectOption('#language','en');assert.equal(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await mobile.screenshot({path:'/tmp/frame-mobile.png',fullPage:true});
 for(const locale of ['ja','ar','zh-Hant']){await mobile.goto('file://'+root+'/dist/'+locale+'/index.html');await mobile.waitForFunction(()=>document.querySelector('#model').options.length>0);assert.equal(await mobile.locator('html').getAttribute('lang'),locale);assert.equal(await mobile.locator('#previewImage').evaluate(el=>el.complete&&el.naturalWidth>0),true);}
 await mobile.goto('file://'+root+'/FRAME_Standalone.html');await mobile.waitForFunction(()=>document.querySelector('#model').options.length>0);await mobile.click('#useDemo');await mobile.waitForFunction(()=>document.querySelector('#fileName').textContent.includes('coast'));assert.equal(await mobile.locator('#previewImage').evaluate(el=>el.naturalWidth>0),true);
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS: workflow validation, model defaults,22-locale asset,RTL,actual local API contract,result reuse,mobile,locale URLs,standalone. Mock media is test-only; no GPU inference claimed.');
})().catch(e=>{console.error(e);process.exit(1)});
