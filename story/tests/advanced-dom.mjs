/* DOM contract tests, not browser/OS certification. npm install --no-save happy-dom@20.0.2 */
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {mountAdvancedUI} from '../advanced-ui.mjs';
import {t} from '../i18n.mjs';
const {Window}=await import(process.env.FRAME_DOM_MODULE?pathToFileURL(process.env.FRAME_DOM_MODULE):'happy-dom');
const results=[];
async function setup(url){
 const window=new Window({url}), calls=[];let busy=false,scene={id:'scene-1'},added=[],applied=[];
 for(const key of ['document','location','FormData','File'])globalThis[key]=window[key];
 globalThis.Option=function(text,value){const e=document.createElement('option');e.textContent=text;e.value=value;return e;};
 document.body.innerHTML='<section id="tools"></section>';
 const container=document.querySelector('#tools');
 const status=[];
 const ui=mountAdvancedUI({container,getScene:()=>scene,addGenerated:async(...args)=>added.push(args),applyNarration:v=>applied.push(v),task:async(label,fn)=>{busy=true;try{await fn(new AbortController().signal)}finally{busy=false;ui.refresh()}},status:(...v)=>status.push(v),t:key=>t(key,'en'),getLanguage:()=> 'en',isBusy:()=>busy});
 return {window,ui,container,calls,added,applied,status,setScene:s=>{scene=s;ui.refresh()},$:id=>container.querySelector('#'+id)};
}
for(const url of ['file:///tmp/FRAME_AI_Studio/index.html','https://kuonanhong.github.io/Frame_to_Video/FRAME_AI_Studio/']){
 globalThis.fetch=()=>{throw new Error('Unexpected network request')};const ctx=await setup(url);
 assert(ctx.$('advancedRun').disabled);assert(ctx.$('advancedCheck').disabled);assert(ctx.$('advancedState').textContent.includes('local'));
 results.push({check:'No model probing on '+new URL(url).protocol,passed:true});await ctx.window.happyDOM.close();
}
const ctx=await setup('http://127.0.0.1:8787/');
const caps=[{id:'qwen-text',available:true,requires_image:false,defaults:{}},{id:'liveportrait',available:true,requires_image:true,requires_driving:true,defaults:{}},{id:'flux-klein',available:false,requires_image:true,blocked_reason:'Install this model first',defaults:{steps:4}}];
globalThis.fetch=async(url,options)=>{const path=new URL(url).pathname;ctx.calls.push({path,method:options?.method||'GET'});if(path==='/api/experts/status')return Response.json({experts:caps});if(path==='/api/experts/jobs')return Response.json({id:'abc',status:'completed',result_text:'An original short story.',outputs:[]});throw new Error('Unexpected route '+path)};
await ctx.$('advancedCheck').onclick();assert(!ctx.$('advancedRun').disabled);
ctx.$('advancedPrompt').value='Write one short sentence.';await ctx.$('advancedRun').onclick();
assert.equal(ctx.$('advancedDraft').value,'An original short story.');assert.equal(ctx.applied.length,0,'Generated text requires review');
ctx.$('advancedApply').onclick();assert.deepEqual(ctx.applied,['An original short story.']);results.push({check:'Qwen text result, review and apply',passed:true});
ctx.$('advancedModel').value='liveportrait';ctx.$('advancedModel').onchange();assert(ctx.$('advancedRun').disabled);assert(!ctx.$('advancedDrivingBox').hidden);assert(ctx.$('advancedPrompt').disabled);
ctx.setScene({id:'scene-1',image:{}});assert(!ctx.$('advancedRun').disabled);await assert.rejects(ctx.$('advancedRun').onclick(),/Driving video/);results.push({check:'Portrait requires source image and actual driving video',passed:true});
ctx.$('advancedModel').value='flux-klein';ctx.$('advancedModel').onchange();assert(ctx.$('advancedRun').disabled);assert(ctx.$('advancedNote').textContent.includes('Install this model'));results.push({check:'Uninstalled model remains blocked',passed:true});
await ctx.window.happyDOM.close();
console.log(JSON.stringify({scope:'Happy DOM contracts; no browser engine or real model inference',passed:true,checks:results},null,2));
