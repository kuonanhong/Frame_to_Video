/* CPU WASM only. No WebGPU, remote model endpoint, or paid API. */
const MODEL_ROOT=new URL('../models/',import.meta.url);
const nativeFetch=globalThis.fetch.bind(globalThis);
let manifestPromise,pipe,ttsSession,ttsVoice,ttsConfig,phonemizer,ortModule,opencc;
let currentId;
const progress=(stage,loaded,total,extra={})=>postMessage({id:currentId,type:'progress',progress:{stage,loaded,total,...extra}});
async function manifest(){
 if(!manifestPromise)manifestPromise=nativeFetch(new URL('manifest.json',MODEL_ROOT)).then(r=>{if(!r.ok)throw new Error('Model manifest missing. Extract the full package including story/models.');return r.json();});
 return manifestPromise;
}
async function bytesFor(rel){
 const m=await manifest();const asset=m.assets.find(x=>x.path===rel&&!x.error);
 if(!asset)throw new Error(`Model asset missing: ${rel}. Run python3 tools/fetch-story-models.py.`);
 const output=new Uint8Array(asset.bytes);let offset=0;
 const pieces=asset.pieces||[{name:rel.split('/').pop(),bytes:asset.bytes,sha256:asset.sha256}];
 for(const part of pieces){
  const path=asset.pieces?rel.substring(0,rel.lastIndexOf('/')+1)+part.name:rel;
  const response=await nativeFetch(new URL(path,MODEL_ROOT));if(!response.ok)throw new Error(`Missing local model part: ${path} (${response.status})`);
  const bytes=new Uint8Array(await response.arrayBuffer());if(bytes.length!==part.bytes)throw new Error(`Model part size mismatch: ${path}`);
  if(globalThis.crypto?.subtle){const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');if(hash!==part.sha256)throw new Error(`Model part integrity check failed: ${path}`);}
  output.set(bytes,offset);offset+=bytes.length;progress('load-model',offset,asset.bytes,{file:rel});
 }
 return output;
}
/* Transformers 3's downloader calls fetch; only the split local model is intercepted.
   All other requests retain their local URL. Remote model loading is disabled below. */
globalThis.fetch=async(input,init)=>{
 const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
 if(url===new URL('smollm2/onnx/model_quantized.onnx',MODEL_ROOT).href){
  const bytes=await bytesFor('smollm2/onnx/model_quantized.onnx');
  return new Response(bytes,{status:200,headers:{'Content-Type':'application/octet-stream','Content-Length':String(bytes.length)}});
 }return nativeFetch(input,init);
};
async function getLLM(){
 if(ttsSession){await ttsSession.release();ttsSession=null;ttsVoice=null;}
 if(!pipe){
  const {env,pipeline}=await import('../vendor/transformers/dist/transformers.min.js');
  env.allowRemoteModels=false;env.allowLocalModels=true;env.localModelPath=MODEL_ROOT.href;
  env.useBrowserCache=false; /* Model parts are cached by site's local service worker; avoid a duplicate 137 MB browser cache. */
  env.backends.onnx.wasm.numThreads=1;env.backends.onnx.wasm.proxy=false;
  env.backends.onnx.wasm.wasmPaths=new URL('../vendor/transformers/dist/',import.meta.url).href;
  progress('init-narration',0,1);
  pipe=await pipeline('text-generation','smollm2',{device:'wasm',dtype:'q8',progress_callback:e=>progress(e.status||'model',e.loaded||0,e.total||0,{file:e.file})});
 }
 return pipe;
}
async function narrate({prompt,objects=[],language='en',maxTokens=96}){
 if(!String(language).toLowerCase().startsWith('en')){
  const e=new Error('The bundled SmolLM2 135M narration model is English-only. Write your own narration in another language, or request an English draft.');e.code='ENGLISH_MODEL_ONLY';throw e;
 }
 if(!String(prompt||'').trim()&&!objects.length)throw new Error('Enter a story idea or detected objects first.');
 const llm=await getLLM();
 const names=objects.slice(0,12).map(o=>typeof o==='string'?o:o.class||o.label||o.name||'').filter(Boolean).join(', ');
 const messages=[{role:'system',content:'You write short, gentle photo-story narration in English. Return only the narration. Use two short sentences. Follow the user idea. Do not add names, locations, dates or facts not supplied. Object detection labels are uncertain; use only relevant ones.'},{role:'user',content:`Story idea: ${String(prompt||'').slice(0,1200)}\nPossible objects: ${names||'not provided'}.\nWrite a brief voice-over for one photo scene.`}];
 progress('generate-narration',0,1);
 const results=await llm(messages,{max_new_tokens:Math.max(16,Math.min(160,Number(maxTokens)||96)),do_sample:false,repetition_penalty:1.12});
 const generated=results[0].generated_text;
 const text=Array.isArray(generated)?generated.at(-1)?.content:String(generated);
 if(!text?.trim())throw new Error('The small model returned an empty draft. Try a shorter English prompt.');
 const trimmed=text.trim(); const lastStop=Math.max(trimmed.lastIndexOf('.'),trimmed.lastIndexOf('!'),trimmed.lastIndexOf('?'));
 progress('generate-narration',1,1);return lastStop>=20&&!/[.!?][\"']?$/.test(trimmed)?trimmed.slice(0,lastStop+1):trimmed;
}
async function ort(){
 if(!ortModule){ortModule=await import('../vendor/onnxruntime-web/dist/ort.wasm.min.mjs');
  ortModule.env.wasm.numThreads=1;ortModule.env.wasm.proxy=false;ortModule.env.wasm.wasmPaths=new URL('../vendor/onnxruntime-web/dist/',import.meta.url).href;
 }return ortModule;
}
async function getTTS(voice){
 if(pipe){await pipe.dispose();pipe=null;}
 if(ttsSession&&ttsVoice===voice)return;
 if(ttsSession){await ttsSession.release();ttsSession=null;}
 const m=await manifest();if(!m.models.piper.voices.includes(voice))throw new Error('This voice model is not included in your package.');
 const response=await nativeFetch(new URL(`piper/${voice}.onnx.json`,MODEL_ROOT));if(!response.ok)throw new Error('Missing voice configuration.');ttsConfig=await response.json();
 const runtime=await ort();progress('init-voice',0,1);
 const weights=await bytesFor(`piper/${voice}.onnx`);
 ttsSession=await runtime.InferenceSession.create(weights,{executionProviders:['wasm'],graphOptimizationLevel:'all'});ttsVoice=voice;
 progress('init-voice',1,1);
}
async function phonemeIds(text,voice){
 if(!phonemizer){const {createPiperPhonemize}=await import('../vendor/piper-tts-web/dist/piper-o91UDS6e.js');phonemizer=createPiperPhonemize;}
 return new Promise(async(resolve,reject)=>{
  let done=false;
  try{
   const mod=await phonemizer({noInitialRun:true,print:data=>{try{const parsed=JSON.parse(data);if(parsed.phoneme_ids){done=true;resolve(parsed.phoneme_ids);}}catch{}},printErr:message=>console.warn(message),locateFile:name=>new URL('phonemizer/'+name,MODEL_ROOT).href});
   mod.callMain(['-l',voice,'--input',JSON.stringify([{text}]),'--espeak_data','/espeak-ng-data']);
   if(!done)reject(new Error('Phonemizer returned no phoneme IDs.'));
  }catch(e){reject(e);}
 });
}
function chunks(text){
 const units=String(text).trim().match(/[^.!?。！？\n]+[.!?。！？\n]*\s*/g)||[];
 const out=[];let current='';
 for(const unit of units){for(let i=0;i<unit.length;i+=140){const bit=unit.slice(i,i+140);if(current.length+bit.length>180){out.push(current);current='';}current+=bit;}}
 if(current.trim())out.push(current);return out;
}
async function speech({text,voice='zh_CN-huayan-medium',language,rate=1}){
 text=String(text||'').trim();if(!text)throw new Error('Enter narration text first.');if(text.length>3000)throw new Error('Use at most 3,000 characters per voice generation.');
 if(language&&!((voice.startsWith('zh_')&&String(language).startsWith('zh'))||(voice.startsWith('en_')&&String(language).startsWith('en'))))throw new Error('Select a voice matching the narration language. The bundled voices support Mandarin and English.');
 if(voice.startsWith('zh_')){if(!opencc){const {Converter}=await import('../vendor/opencc/dist/esm/full.js');opencc=Converter({from:'tw',to:'cn'});}text=opencc(text);}
 await getTTS(voice);const runtime=await ort();const parts=chunks(text);const pcms=[];let total=0;
 for(let i=0;i<parts.length;i++){
  progress('synthesize-speech',i,parts.length);
  const ids=await phonemeIds(parts[i],ttsConfig.espeak.voice);
  const feeds={input:new runtime.Tensor('int64',BigInt64Array.from(ids,BigInt),[1,ids.length]),input_lengths:new runtime.Tensor('int64',BigInt64Array.from([ids.length],BigInt),[1]),scales:new runtime.Tensor('float32',Float32Array.from([ttsConfig.inference.noise_scale,ttsConfig.inference.length_scale/Math.max(.6,Math.min(1.6,Number(rate)||1)),ttsConfig.inference.noise_w]),[3])};
  if(ttsConfig.num_speakers>1)feeds.sid=new runtime.Tensor('int64',BigInt64Array.from([0],BigInt),[1]);
  const results=await ttsSession.run(feeds);const data=results.output?.data||Object.values(results)[0].data;const pcm=new Float32Array(data);pcms.push(pcm);total+=pcm.length;
 }
 const gap=Math.round(ttsConfig.audio.sample_rate*.15);const audio=new Float32Array(total+Math.max(0,pcms.length-1)*gap);let at=0;
 pcms.forEach((pcm,i)=>{audio.set(pcm,at);at+=pcm.length+(i<pcms.length-1?gap:0);});
 progress('synthesize-speech',parts.length,parts.length);return {audio,sampleRate:ttsConfig.audio.sample_rate};
}
onmessage=async({data})=>{
 currentId=data.id;
 try{const result=await(data.kind==='narration'?narrate(data.payload):speech(data.payload));postMessage({id:data.id,type:'result',result},result?.audio?[result.audio.buffer]:[]);}
 catch(e){postMessage({id:data.id,type:'error',message:e.message||String(e),code:e.code||'CPU_MODEL_ERROR'});}
};
