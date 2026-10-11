/* Classic-script boot contracts only: Happy DOM with stubbed canvas, no browser/media certification. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=fileURLToPath(new URL('../../',import.meta.url));
const {Window}=await import(process.env.FRAME_DOM_MODULE?pathToFileURL(process.env.FRAME_DOM_MODULE):'happy-dom');
const bundle=path.join(root,'story/app-v5.bundle.js');
let code,buildMode;
if(fs.existsSync(bundle)){
 code=fs.readFileSync(bundle,'utf8');buildMode='existing classic bundle';
}else{
 const {build}=await import(process.env.FRAME_ESBUILD?pathToFileURL(process.env.FRAME_ESBUILD):'esbuild');
 const result=await build({entryPoints:[path.join(root,'story/app.mjs')],write:false,bundle:true,format:'iife',platform:'browser',target:['es2020'],minify:true,logOverride:{'empty-import-meta':'silent'}});
 code=result.outputFiles[0].text;buildMode='source compiled in memory; final on-disk bundle still needs a build';
}
const html=fs.readFileSync(path.join(root,'index.html'),'utf8').replace(/<script[\s\S]*?<\/script>/g,'').replace(/<link[^>]+rel="stylesheet"[^>]*>/g,'');
const checks=[];
for(const url of ['file:///tmp/FRAME_AI_Studio/index.html','http://127.0.0.1:8787/','http://127.0.0.1:8787/story/index.html','https://kuonanhong.github.io/Frame_to_Video/FRAME_AI_Studio/']){
 const window=new Window({url,settings:{disableCSSFileLoading:true,disableJavaScriptFileLoading:true,enableJavaScriptEvaluation:true,suppressInsecureJavaScriptEnvironmentWarning:true}});
 const errors=[],requests=[];
 window.console.error=(...args)=>errors.push(args.map(String).join(' '));
 window.console.warn=(...args)=>errors.push(args.map(String).join(' '));
 window.HTMLCanvasElement.prototype.getContext=function(){
  return new Proxy({canvas:this,measureText:()=>({width:40}),createLinearGradient:()=>({addColorStop(){}}),createRadialGradient:()=>({addColorStop(){}}),getImageData:()=>({data:new Uint8ClampedArray(4),width:1,height:1})},{get:(object,key)=>key in object?object[key]:()=>{}});
 };
 window.HTMLCanvasElement.prototype.toDataURL=()=> 'data:image/png;base64,eA==';
 window.fetch=async(value,options)=>{requests.push({url:String(value),method:options?.method||'GET'});throw new Error('Network disabled in boot DOM contract')};
 window.Option=function(text,value){const option=window.document.createElement('option');option.textContent=text;option.value=value;return option};
 window.localStorage.setItem('frame-story-language','en');
 window.document.write(url.endsWith('/story/index.html')?html.replace('<head>','<head><base href="../">'):html);
 window.eval(code);
 // The bundled voice catalog initializes in a promise; no models are loaded.
 await new Promise(resolve=>setTimeout(resolve,10));
 const $=id=>window.document.getElementById(id);
 assert.equal(window.__FRAME_READY__,true,url);
 assert.ok(window.FRAME_STORY,url);
 assert.equal(window.FRAME_STORY.scenes.length,0,url);
 assert.equal($('advancedModel').options.length,7,url);
 assert.ok($('visualTools').children.length,url);
 assert.ok($('expertTools').children.length,url);
 assert.equal($('advancedRun').disabled,true,url);
 assert.equal($('advancedCheck').disabled,!url.startsWith('http://127.0.0.1'),url);
 assert.equal(requests.length,0,'Boot must not probe or install models: '+url);
 assert.equal(errors.length,0,errors.join('\n'));
 $('language').value='zh-Hant';$('language').onchange();
 assert.equal(window.document.documentElement.lang,'zh-Hant',url);
 assert.ok($('advancedRun').textContent.trim(),url);
 $('aspect').value='portrait';$('aspect').onchange();
 assert.ok(window.FRAME_STORY.settings.width<window.FRAME_STORY.settings.height,url);
 checks.push({url,passed:true,base:window.document.baseURI,expertOptions:7,noBootNetwork:true});
 await window.happyDOM.close();
}
const report={scope:'Happy DOM classic-script boot with canvas stub; no browser rendering, media export, operating-system, or model-inference certification',passed:true,buildMode,checks};
const reportPath=path.join(root,'qa/v5/boot-dom.json');fs.mkdirSync(path.dirname(reportPath),{recursive:true});fs.writeFileSync(reportPath,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
