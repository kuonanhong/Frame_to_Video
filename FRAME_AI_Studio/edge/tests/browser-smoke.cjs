/* Real browser end-to-end test. No API/model responses are mocked. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
let playwright;
try { playwright = require('playwright'); }
catch { playwright = require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core'); }
const ROOT = path.resolve(__dirname, '../..');
const OUTPUT = path.join(ROOT, 'qa-output');
const browserPath = process.env.FRAME_BROWSER_PATH || '/workspace/scratch/a8695db12b98/qa/bin/chromium';
const mime = {'.html':'text/html', '.js':'text/javascript', '.mjs':'text/javascript', '.json':'application/json', '.css':'text/css', '.webp':'image/webp', '.png':'image/png', '.jpg':'image/jpeg', '.svg':'image/svg+xml', '.wasm':'application/wasm', '.md':'text/plain'};
const summary = { executedAt: new Date().toISOString(), environment: 'Linux x86_64, Chromium (GPU disabled)', tests: [], limitations: ['No iPhone/Safari or Android hardware tested', 'No generated video AI inference', 'No concurrent-user load test'] };
const pass = (name, evidence) => summary.tests.push({name, passed:true, ...(evidence ? {evidence}: {})});
let server, browser;
async function canvasHash(page,id) {
  return page.evaluate(id=>{
    const c=document.getElementById(id); const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
    let hash=2166136261; for(let i=0;i<d.length;i+=131) hash=Math.imul(hash^d[i],16777619);
    return hash>>>0;
  },id);
}
async function run() {
  fs.mkdirSync(OUTPUT,{recursive:true});
  server = http.createServer((request,response) => {
    let target = path.resolve(ROOT,'.'+decodeURIComponent(new URL(request.url,'http://localhost').pathname));
    if(target!==ROOT && !target.startsWith(ROOT+path.sep)){response.writeHead(403);response.end();return;}
    try {
      if(fs.statSync(target).isDirectory())target=path.join(target,'index.html');
      response.setHeader('Content-Type',mime[path.extname(target)]||'application/octet-stream');
      response.end(fs.readFileSync(target));
    }catch{response.writeHead(404);response.end('not found');}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const BASE=`http://127.0.0.1:${server.address().port}`;
  browser = await playwright.chromium.launch({executablePath:fs.existsSync(browserPath)?browserPath:undefined,headless:true,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
  const page = await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true});
  const errors=[], requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>requests.push({url:r.url(),method:r.method()}));
  await page.addInitScript(()=>{
    const diag={created:0,terminated:0,workers:[],urls:new Set(),streams:[]};
    window.__qa=diag;
    const W=Worker;
    window.Worker=class extends W {
      constructor(...args){super(...args);diag.created++;diag.workers.push(this);this.__qaAlive=true;}
      terminate(){if(this.__qaAlive){this.__qaAlive=false;diag.terminated++;}super.terminate();}
    };
    const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);
    URL.createObjectURL=x=>{const url=create(x);diag.urls.add(url);return url;};
    URL.revokeObjectURL=url=>{diag.urls.delete(url);return revoke(url);};
    const capture=HTMLCanvasElement.prototype.captureStream;
    if(capture)HTMLCanvasElement.prototype.captureStream=function(...args){const stream=capture.apply(this,args);diag.streams.push(stream);return stream;};
  });
  await page.goto(BASE+'/edge/',{waitUntil:'networkidle'});
  await page.locator('#language option').first().waitFor({state:'attached'});
  const languageCodes=await page.locator('#language option').evaluateAll(items=>items.map(x=>x.value));
  assert.equal(languageCodes.length,22);
  for(const code of languageCodes){await page.selectOption('#language',code);assert.equal(await page.locator('html').getAttribute('lang'),code);assert.ok((await page.locator('h1').textContent()).trim());}
  await page.selectOption('#language','en');
  pass('22 language interfaces switch and set lang',languageCodes);
  await page.click('#demo');
  await page.waitForFunction(()=>document.getElementById('fileName').textContent.length>0);
  assert.ok(await page.locator('#sourceCanvas').evaluate(c=>c.width>0&&c.height>0));
  pass('demo image loads and source canvas renders');

  // Actual UI inference with bundled model. Empty results on this coast photo
  // are valid; a separate optional official fixture checks a positive detection.
  await page.click('#detect');
  await page.waitForFunction(()=>!document.getElementById('cancel').hidden);
  await page.waitForFunction(()=>document.getElementById('cancel').hidden,null,{timeout:60000});
  pass('real bundled CPU detection completes on coast demo',await page.locator('#statusDetail').textContent());

  if(process.env.FRAME_QA_FIXTURE){
    await page.setInputFiles('#imageFile',process.env.FRAME_QA_FIXTURE);
    await page.waitForFunction(()=>document.getElementById('fileName').textContent.includes('cat'));
    await page.click('#detect');
    await page.waitForFunction(()=>!document.getElementById('cancel').hidden);
    await page.waitForFunction(()=>document.getElementById('cancel').hidden,null,{timeout:60000});
    assert.match(await page.locator('#objectList').textContent(),/cat/i);
    pass('official development cat fixture produces real object detection');
    await page.click('#demo');
  }

  await page.selectOption('#regionType','water');
  await page.click('#manual');
  const box=await page.locator('#overlayCanvas').boundingBox();
  await page.mouse.move(box.x+box.width*.1,box.y+box.height*.55);
  await page.mouse.down();
  await page.mouse.move(box.x+box.width*.9,box.y+box.height*.88,{steps:12});
  await page.mouse.up();
  assert.ok(await page.locator('#objectList li').count()>0);
  await page.fill('#prompt','zoom in, water ripples, snow');
  await page.click('#applyPrompt');
  assert.ok((await page.locator('#planSummary').textContent()).length>5);
  const planned=await page.evaluate(()=>FRAME_CPU_DIAGNOSTICS());
  assert.ok(planned.rules.includes('water'));
  assert.ok(planned.effectCount>=2);
  pass('manual water region and supported prompt planning');

  await page.selectOption('#duration','2');await page.selectOption('#fps','12');
  await page.click('#preview');
  await page.waitForFunction(()=>!document.getElementById('outputCanvas').hidden);
  const first=await canvasHash(page,'outputCanvas');
  await page.waitForTimeout(650);
  const second=await canvasHash(page,'outputCanvas');
  assert.notEqual(first,second);
  pass('actual motion frames change over time',{first,second});
  await page.click('#stop');
  await page.waitForFunction(()=>document.getElementById('stop').hidden);
  const stoppedPreview=await page.evaluate(()=>FRAME_CPU_DIAGNOSTICS());
  assert.equal(stoppedPreview.motionWorker,false);
  assert.equal(stoppedPreview.pendingFrames,0);
  pass('stopping preview terminates renderer and clears pending frame');

  await page.click('#export');
  assert.equal(await page.locator('#export').isDisabled(),true);
  await page.waitForFunction(()=>!document.getElementById('download').hidden,null,{timeout:30000});
  const video=await page.locator('#resultVideo').evaluate(async el=>{
    if(el.readyState<1)await new Promise((resolve,reject)=>{el.addEventListener('loadedmetadata',resolve,{once:true});el.addEventListener('error',reject,{once:true});});
    await el.play();await new Promise(resolve=>setTimeout(resolve,500));
    const result={width:el.videoWidth,height:el.videoHeight,duration:Number.isFinite(el.duration)?el.duration:String(el.duration),currentTime:el.currentTime,readyState:el.readyState};el.pause();return result;
  });
  assert.ok(video.width>0 && video.height>0 && video.currentTime>0);
  const [download]=await Promise.all([page.waitForEvent('download'),page.click('#download')]);
  const outputPath=path.join(OUTPUT,'browser-export.'+(download.suggestedFilename().endsWith('.mp4')?'mp4':'webm'));
  await download.saveAs(outputPath);
  assert.ok(fs.statSync(outputPath).size>1000);
  pass('MediaRecorder video export loads and actually plays',{...video,bytes:fs.statSync(outputPath).size});
  assert.equal(await page.evaluate(()=>window.__qa.streams.flatMap(s=>s.getTracks()).filter(t=>t.readyState==='live').length),0);
  pass('capture stream tracks stop after export');
  await page.screenshot({path:path.join(OUTPUT,'cpu-desktop.png'),fullPage:true});

  await page.click('#export');
  await page.waitForFunction(()=>!document.getElementById('stop').hidden);
  await page.waitForTimeout(250);
  await page.click('#stop');
  await page.waitForFunction(()=>document.getElementById('stop').hidden);
  await page.waitForTimeout(100);
  assert.equal(await page.locator('#download').isHidden(),true);
  assert.equal(await page.evaluate(()=>window.__qa.streams.flatMap(s=>s.getTracks()).filter(t=>t.readyState==='live').length),0);
  const cancelledHash=await canvasHash(page,'outputCanvas');
  await page.waitForTimeout(200);
  assert.equal(await canvasHash(page,'outputCanvas'),cancelledHash);
  pass('cancel export stops capture tracks and prevents stale-frame painting');

  // Cancellation must stop detector CPU work, not merely hide progress.
  const before=await page.evaluate(()=>window.__qa.terminated);
  await page.click('#detect');
  await page.waitForFunction(()=>!document.getElementById('cancel').hidden);
  await page.click('#cancel');
  await page.waitForFunction(()=>document.getElementById('cancel').hidden);
  assert.ok(await page.evaluate(x=>window.__qa.terminated>x,before));
  pass('cancel detection terminates its CPU worker');
  const created=await page.evaluate(()=>window.__qa.created);
  await page.evaluate(()=>{document.getElementById('detect').click();document.getElementById('detect').click();});
  await page.waitForFunction(()=>!document.getElementById('cancel').hidden);
  assert.ok(await page.evaluate(x=>window.__qa.created-x<=1,created));
  await page.click('#cancel');
  await page.waitForFunction(()=>document.getElementById('cancel').hidden);
  pass('duplicate detect clicks do not create concurrent detector workers');
  await page.click('#reset');
  assert.equal(await page.locator('#download').isHidden(),true);
  assert.equal(await page.evaluate(()=>window.__qa.urls.size),0);
  pass('reset revokes generated object URLs');

  const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  mobile.on('pageerror',e=>errors.push(e.message));
  await mobile.goto(BASE+'/edge/',{waitUntil:'networkidle'});
  for(const code of languageCodes){await mobile.selectOption('#language',code);assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),code+' mobile overflow');}
  await mobile.selectOption('#language','ar');
  assert.equal(await mobile.locator('html').getAttribute('dir'),'rtl');
  assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await mobile.click('#demo');
  await mobile.waitForFunction(()=>document.getElementById('fileName').textContent.length>0);
  await mobile.waitForFunction(()=>!document.getElementById('detect').disabled);
  await mobile.screenshot({path:path.join(OUTPUT,'cpu-mobile-arabic.png'),fullPage:true});
  pass('390px mobile Arabic RTL layout has no horizontal overflow');

  for(const code of ['zh-Hant','ar','ja']){
    await mobile.goto(BASE+'/edge/l/'+code+'/',{waitUntil:'networkidle'});
    await mobile.waitForFunction(()=>!document.getElementById('detect').disabled);
    assert.equal(await mobile.locator('html').getAttribute('lang'),code);
    assert.ok(await mobile.evaluate(()=>FRAME_CPU_DIAGNOSTICS().motionWorker));
  }
  pass('localized URL pages load scripts, source image and renderer from correct base paths');

  await page.selectOption('#language','en');
  const portrait=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=400;c.height=800;const ctx=c.getContext('2d');ctx.fillStyle='#d58a4b';ctx.fillRect(0,0,400,800);ctx.fillStyle='#315989';ctx.fillRect(60,200,180,350);return c.toDataURL('image/png').split(',')[1];});
  await page.setInputFiles('#imageFile',{name:'portrait.png',mimeType:'image/png',buffer:Buffer.from(portrait,'base64')});
  await page.waitForFunction(()=>document.getElementById('fileName').textContent==='portrait.png'&&!document.getElementById('detect').disabled);
  const portraitRatio=await page.locator('#sourceCanvas').evaluate(c=>{const r=c.getBoundingClientRect();return{css:r.width/r.height,pixels:c.width/c.height};});
  assert.ok(Math.abs(portraitRatio.css-portraitRatio.pixels)<.01);
  pass('portrait photo canvas display retains intrinsic aspect for manual region mapping',portraitRatio);

  const standalone=await browser.newPage({viewport:{width:1280,height:1000}});
  const standaloneErrors=[],standaloneRequests=[];
  standalone.on('pageerror',e=>standaloneErrors.push(e.message));
  standalone.on('request',r=>standaloneRequests.push({url:r.url(),method:r.method()}));
  await standalone.goto('file://'+path.join(ROOT,'FRAME_CPU_Studio.html'),{waitUntil:'networkidle'});
  await standalone.waitForFunction(()=>!document.getElementById('detect').disabled);
  await standalone.selectOption('#language','en');
  assert.equal(await standalone.evaluate(()=>FRAME_CPU_DIAGNOSTICS().modelEmbedded),true);
  if(process.env.FRAME_QA_FIXTURE){await standalone.setInputFiles('#imageFile',process.env.FRAME_QA_FIXTURE);await standalone.waitForFunction(()=>document.getElementById('fileName').textContent.includes('cat')&&!document.getElementById('detect').disabled);}
  await standalone.click('#detect');
  await standalone.waitForFunction(()=>!document.getElementById('cancel').hidden);
  await standalone.waitForFunction(()=>document.getElementById('cancel').hidden,null,{timeout:60000});
  const singleDiag=await standalone.evaluate(()=>({diagnostics:FRAME_CPU_DIAGNOSTICS(),status:document.getElementById('statusText').textContent,detail:document.getElementById('statusDetail').textContent}));
  fs.writeFileSync(path.join(OUTPUT,'standalone-state.json'),JSON.stringify({state:singleDiag,errors:standaloneErrors,requests:standaloneRequests},null,2));
  if(singleDiag.diagnostics.backend!=='cpu')console.error('Standalone detection failure:',JSON.stringify(singleDiag),standaloneErrors);
  assert.equal(await standalone.evaluate(()=>FRAME_CPU_DIAGNOSTICS().backend),'cpu');
  if(process.env.FRAME_QA_FIXTURE)assert.match(await standalone.locator('#objectList').textContent(),/cat/i);
  await standalone.click('[data-preset="zoom"]');
  await standalone.selectOption('#duration','2');await standalone.selectOption('#fps','12');
  await standalone.click('#export');
  await standalone.waitForFunction(()=>!document.getElementById('download').hidden,null,{timeout:30000});
  const singleVideo=await standalone.locator('#resultVideo').evaluate(async el=>{if(el.readyState<1)await new Promise(resolve=>el.addEventListener('loadedmetadata',resolve,{once:true}));await el.play();await new Promise(resolve=>setTimeout(resolve,350));return{width:el.videoWidth,height:el.videoHeight,currentTime:el.currentTime,duration:el.duration};});
  assert.ok(singleVideo.width>0&&singleVideo.currentTime>0);
  assert.deepEqual(standaloneErrors,[]);
  assert.deepEqual(standaloneRequests.filter(r=>r.method!=='GET'||!['file:','blob:','data:'].some(x=>r.url.startsWith(x))),[]);
  pass('single HTML file:// performs real embedded CPU inference and video export without network',singleVideo);
  await standalone.close();

  assert.deepEqual(errors,[]);
  assert.deepEqual(requests.filter(r=>r.method!=='GET'),[]);
  assert.deepEqual(requests.filter(r=>!r.url.startsWith(BASE+'/')&&!r.url.startsWith('blob:')&&!r.url.startsWith('data:')),[]);
  pass('no page errors; only same-origin GETs, no picture upload request');
  summary.requests=requests;
  fs.writeFileSync(path.join(OUTPUT,'browser-results.json'),JSON.stringify(summary,null,2));
  console.log(JSON.stringify(summary,null,2));
}
run().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)server.close();});
