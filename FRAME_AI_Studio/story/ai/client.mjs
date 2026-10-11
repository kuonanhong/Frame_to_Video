/* FRAME CPU neural inference. All model execution happens in this user's worker. */
const catalog = [
 {id:'zh_CN-huayan-medium',name:'華燕 · 中文',language:'zh',description:'Mandarin preset; neural Piper voice, not voice cloning.'},
 {id:'en_US-amy-low',name:'Amy · English (US)',language:'en',description:'Female English preset; Piper neural voice.'},
 {id:'en_GB-alan-low',name:'Alan · English (UK)',language:'en',description:'Male English preset; Piper neural voice.'},
];
export const voiceCatalog=()=>catalog.map(x=>({...x}));
export const supportedLanguages=()=>({narration:['en'],speech:['zh','en'],interface:'See story/i18n.mjs; UI language does not imply model language support.'});
let worker, sequence=0; const pending=new Map();
function getWorker(){
 if(!worker){
  worker=new Worker(new URL('story/ai/worker.mjs',document.baseURI),{type:'module'});
  worker.onmessage=({data})=>{
   const p=pending.get(data.id);if(!p)return;
   if(data.type==='progress'){p.onProgress?.(data.progress);return;}
   pending.delete(data.id);p.cleanup();
   if(data.type==='error'){const e=new Error(data.message);e.code=data.code;p.reject(e);}
   else p.resolve(data.result);
  };
  worker.onerror=event=>{for(const p of pending.values()){p.cleanup();p.reject(new Error(event.message||'CPU worker failed.'));}pending.clear();worker?.terminate();worker=null;};
 }return worker;
}
function run(kind,options={}){
 const {onProgress,signal,...payload}=options;
 if(signal?.aborted)return Promise.reject(new DOMException('Operation aborted','AbortError'));
 if(pending.size)return Promise.reject(new Error('CPU model is busy. Wait for the current operation or cancel it.'));
 return new Promise((resolve,reject)=>{
  const id=++sequence;const abort=()=>{
   /* Termination actually interrupts WASM; no background inference continues. */
   worker?.terminate();worker=null;
   for(const p of pending.values()){p.cleanup();p.reject(new DOMException('Operation aborted','AbortError'));}pending.clear();
  };
  signal?.addEventListener('abort',abort,{once:true});
  pending.set(id,{resolve,reject,onProgress,cleanup:()=>signal?.removeEventListener('abort',abort)});
  getWorker().postMessage({id,kind,payload});
 });
}
export async function generateNarration({prompt,objects=[],language='en',maxTokens=96,onProgress,signal}){
 return run('narration',{prompt,objects,language,maxTokens,onProgress,signal});
}
export async function synthesizeSpeech({text,voice='zh_CN-huayan-medium',language,rate=1,onProgress,signal}){
 return run('speech',{text,voice,language,rate,onProgress,signal});
}
export function releaseModels(){worker?.terminate();worker=null;for(const p of pending.values()){p.cleanup();p.reject(new DOMException('Models released','AbortError'));}pending.clear();}
