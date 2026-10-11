import {advancedText} from './advanced-i18n.mjs';

export const EXPERTS = Object.freeze([
 {id:'qwen-text',name:'Qwen2.5 · 0.5B',kind:'text'},
 {id:'liveportrait',name:'LivePortrait',kind:'video'},
 {id:'controlnet-canny',name:'ControlNet · Canny',kind:'image'},
 {id:'multidiffusion',name:'MultiDiffusion · Panorama',kind:'image'},
 {id:'flux-klein',name:'FLUX.2 · klein 4B',kind:'image'},
 {id:'ltx-video',name:'LTX-Video',kind:'video'},
 {id:'cogvideox',name:'CogVideoX · I2V',kind:'video'}
]);
export function isLocalExpertHost(location) {
 return location.protocol==='http:' && ['127.0.0.1','localhost','[::1]'].includes(location.hostname);
}
export function outputURL(value,base,job) {
 const url=new URL(value,base), origin=new URL(base).origin;
 if(url.origin!==origin || !url.pathname.startsWith('/api/experts/jobs/'+encodeURIComponent(job)+'/')) throw new Error('Invalid expert output URL');
 return url.href;
}
function delay(ms,signal){return new Promise((resolve,reject)=>{let timer;const stop=()=>{clearTimeout(timer);signal.removeEventListener('abort',stop);reject(new DOMException('Cancelled','AbortError'))};timer=setTimeout(()=>{signal.removeEventListener('abort',stop);resolve()},ms);signal.addEventListener('abort',stop,{once:true});if(signal.aborted)stop()})}

export function mountAdvancedUI({container,getScene,addGenerated,applyNarration,task,status,t,getLanguage,isBusy}) {
 const x=k=>advancedText(k,getLanguage());
 container.innerHTML=`<details><summary data-adv="title"></summary><p class="hint" data-adv="local"></p>
 <p><a href="advanced_service/README.html" target="_blank" rel="noopener" data-core="expertGuide"></a> · <a href="MODEL_REALITY_GUIDE.html" target="_blank" rel="noopener" data-core="modelsInfo"></a></p>
 <button id="advancedCheck" data-core="expertCheck"></button><p id="advancedState" class="hint" role="status"></p>
 <label for="advancedModel" data-core="expertModel"></label><select id="advancedModel"></select><p id="advancedNote" class="hint"></p>
 <label for="advancedPrompt" data-core="expertPrompt"></label><textarea id="advancedPrompt" maxlength="1000"></textarea>
 <div id="advancedDrivingBox" hidden><label for="advancedDriving" data-adv="driving"></label><input id="advancedDriving" type="file" accept="video/mp4,video/webm,video/quicktime"><p class="hint" data-adv="portrait"></p></div>
 <div class="field-row"><div><label for="advancedSteps" data-core="expertSteps"></label><input id="advancedSteps" type="number" min="1" max="50" value="20"></div><div><label for="advancedSeed" data-core="expertSeed"></label><input id="advancedSeed" type="number" min="0" max="2147483647" value="42"></div></div>
 <p class="hint" data-adv="slow"></p><button id="advancedRun" class="primary" data-core="expertRun"></button>
 <div id="advancedTextResult" hidden><label for="advancedDraft" data-adv="draft"></label><textarea id="advancedDraft" maxlength="1600"></textarea><button id="advancedApply" data-adv="apply"></button></div>
 </details>`;
 const $=id=>container.querySelector('#'+id), local=isLocalExpertHost(location);
 let entries=new Map(), currentJob=null, checked=false;
 const selected=()=>entries.get($('advancedModel').value),selectedSpec=()=>EXPERTS.find(e=>e.id===$('advancedModel').value);
 $('advancedModel').replaceChildren(...EXPERTS.map(e=>new Option(e.name,e.id)));
 function translate(){container.querySelectorAll('[data-adv]').forEach(e=>e.textContent=x(e.dataset.adv));container.querySelectorAll('[data-core]').forEach(e=>e.textContent=t(e.dataset.core));}
 async function json(url,options){const response=await fetch(new URL(url,document.baseURI),options);let value;try{value=await response.json()}catch{throw new Error(t('expertUnavailable'))}if(!response.ok)throw new Error(value.error||`HTTP ${response.status}`);return value}
 function defaults(){const d=selected()?.defaults||{};$('advancedSteps').value=String(d.steps||20);refresh()}
 $('advancedModel').onchange=defaults;
 $('advancedCheck').onclick=async()=>{if(!local||isBusy())return;$('advancedCheck').disabled=true;try{const data=await json('api/experts/status');entries=new Map((data.experts||[]).map(e=>[e.id,e]));checked=true;$('advancedState').textContent=(data.experts||[]).map(e=>`${e.id}: ${t(e.available?'expertReady':'expertMissing')}`).join('\n');defaults()}catch(e){checked=false;$('advancedState').textContent=t('expertUnavailable')}finally{refresh()}};
 $('advancedApply').onclick=()=>{if(isBusy())return;const value=$('advancedDraft').value.trim();if(!getScene()){status(t('noScene'));return}if(value)applyNarration(value.slice(0,1600));};
 $('advancedRun').onclick=()=>task(t('expertRun'),async signal=>{
  const spec=selectedSpec(),cap=selected(),scene=getScene(),prompt=$('advancedPrompt').value.trim();
  if(!cap?.available)throw new Error(t('expertUnavailable'));
  if(spec.id!=='liveportrait'&&!prompt)throw new Error(t('expertPrompt'));
  if(cap.requires_image&&!scene?.image)throw new Error(t('expertNeedImage'));
  const driving=$('advancedDriving').files[0];
  if(cap.requires_driving&&!driving)throw new Error(x('driving'));
  if(driving&&driving.size>50*1024*1024)throw new Error(x('driving')+' ≤ 50 MiB');
  const form=new FormData();form.set('expert',spec.id);form.set('prompt',prompt);form.set('seed',$('advancedSeed').value);
  if(spec.id!=='qwen-text'&&spec.id!=='liveportrait')form.set('steps',$('advancedSteps').value);
  if(cap.requires_image&&scene?.image){const canvas=document.createElement('canvas'),scale=Math.min(1,1024/Math.max(scene.image.naturalWidth,scene.image.naturalHeight));canvas.width=Math.max(1,Math.round(scene.image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(scene.image.naturalHeight*scale));canvas.getContext('2d').drawImage(scene.image,0,0,canvas.width,canvas.height);const image=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!image)throw new Error('Image conversion failed');form.set('image',image,'scene.png')}
  if(cap.requires_driving)form.set('driving',driving,driving.name);
  form.set('max_tokens','256');
  const cancel=()=>{if(currentJob)fetch(new URL(`api/experts/jobs/${encodeURIComponent(currentJob)}/cancel`,document.baseURI),{method:'POST'}).catch(()=>{})};
  signal.addEventListener('abort',cancel,{once:true});
  try{
   if(signal.aborted)throw new DOMException('Cancelled','AbortError');
   // Await creation even when cancelled so the server job can be explicitly stopped.
   let job=await json('api/experts/jobs',{method:'POST',body:form});currentJob=job.id;
   if(signal.aborted){cancel();throw new DOMException('Cancelled','AbortError')}
   while(!['completed','failed','cancelled'].includes(job.status)){status(`${spec.name} · ${t('expertBusy')} ${job.phase||''}`,Math.min(.95,(job.progress||5)/100));await delay(1000,signal);job=await json(`api/experts/jobs/${encodeURIComponent(currentJob)}`,{signal})}
   if(job.status==='failed')throw new Error(job.error||'Expert inference failed');
   if(job.status==='cancelled')throw new DOMException('Cancelled','AbortError');
   if(spec.kind==='text'){
    let value=job.result_text;
    if(typeof value!=='string'){const out=(job.outputs||[]).find(o=>o.kind==='text');if(!out)throw new Error('Missing generated text');const response=await fetch(outputURL(out.url,document.baseURI,currentJob),{signal});if(!response.ok)throw new Error('Text download failed');value=await response.text()}
    $('advancedDraft').value=value.slice(0,1600);$('advancedTextResult').hidden=false;status(x('draft'),1);
   }else{
    const out=(job.outputs||[]).find(o=>o.kind===spec.kind);if(!out)throw new Error('Missing generated media');
    const response=await fetch(outputURL(out.url,document.baseURI,currentJob),{signal});if(!response.ok)throw new Error('Media download failed');
    const blob=await response.blob();await addGenerated(blob,out.name||`${spec.id}.${spec.kind==='video'?'mp4':'png'}`,spec.kind);status(t('expertDone'),1);
   }
  }finally{signal.removeEventListener('abort',cancel);currentJob=null;refresh()}
 });
 function refresh(){translate();const spec=selectedSpec(),cap=selected(),busy=isBusy();$('advancedDrivingBox').hidden=spec.id!=='liveportrait';$('advancedPrompt').disabled=busy||spec.id==='liveportrait';$('advancedSteps').disabled=busy||['qwen-text','liveportrait'].includes(spec.id);$('advancedCheck').disabled=!local||busy;$('advancedModel').disabled=busy;$('advancedDriving').disabled=busy;$('advancedRun').disabled=!local||busy||!checked||!cap?.available||!!(cap?.requires_image&&!getScene()?.image);$('advancedApply').disabled=busy||!getScene();$('advancedNote').textContent=x(spec.kind)+(cap?.blocked_reason?'\n'+cap.blocked_reason:'')+(cap?.cpu_note?'\n'+cap.cpu_note:'');if(!local)$('advancedState').textContent=t('expertLocalOnly')}
 refresh();return{refresh};
}
