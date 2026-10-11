import { Client, handle_file } from '@gradio/client';

export const MODELS = [
 { id:'ltx-cloud', name:'LTX Video · Distilled', mode:'cloud', workflows:['image-video','video-video'], space:'Lightricks/ltx-video-distilled', url:'https://huggingface.co/spaces/Lightricks/ltx-video-distilled', note:'Lightricks · ZeroGPU', aspect:true },
 { id:'wan-cloud', name:'Wan 2.2 · Lightning', mode:'cloud', workflows:['image-video'], space:'zerogpu-aoti/wan2-2-fp8da-aoti-faster', url:'https://huggingface.co/spaces/zerogpu-aoti/wan2-2-fp8da-aoti-faster', note:'zerogpu-aoti · community ZeroGPU', aspect:false },
 { id:'flux-cloud', name:'FLUX.1 · schnell', mode:'cloud', workflows:['text-image'], space:'black-forest-labs/FLUX.1-schnell', url:'https://huggingface.co/spaces/black-forest-labs/FLUX.1-schnell', note:'Black Forest Labs · ZeroGPU', aspect:true },
 { id:'ltx-2b', name:'LTX Video · 2B', mode:'local', workflows:['image-video','video-video'], url:'https://huggingface.co/Lightricks/LTX-Video-0.9.5', note:'2B · CUDA GPU · Open RAIL-M', aspect:true },
 { id:'wan-5b', name:'Wan 2.2 · 5B', mode:'local', workflows:['image-video'], url:'https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers', note:'5B · CUDA GPU · Apache 2.0', aspect:true },
 { id:'sd-turbo', name:'SD-Turbo · 1 step', mode:'local', workflows:['text-image'], url:'https://huggingface.co/stabilityai/sd-turbo', note:'Powered by Stability AI · Community License · 512 × 512', aspect:false }
];
export function dimensions(aspect,image=false) {
 return image ? ({'16:9':[768,448],'9:16':[448,768],'1:1':[512,512]}[aspect]) : ({'16:9':[704,416],'9:16':[416,704],'1:1':[512,512]}[aspect]);
}
export function cloudRequest(model,options) {
 const { workflow,prompt,file,duration,aspect,seed,random }=options;
 const [width,height]=dimensions(aspect,workflow==='text-image');
 if(model.id==='flux-cloud')return {endpoint:'/infer',payload:{prompt,seed,randomize_seed:random,width,height,num_inference_steps:4}};
 if(model.id==='wan-cloud')return {endpoint:'/generate_video',payload:{input_image:handle_file(file),prompt,steps:6,negative_prompt:'blurry, distorted, jittery, low quality, text, watermark',duration_seconds:duration,guidance_scale:1,guidance_scale_2:1,seed,randomize_seed:random}};
 return {endpoint:workflow==='video-video'?'/video_to_video':'/image_to_video',payload:{prompt,negative_prompt:'worst quality, inconsistent motion, blurry, jittery, distorted',input_image_filepath:workflow==='image-video'?handle_file(file):null,input_video_filepath:workflow==='video-video'?{video:handle_file(file),subtitles:null}:null,height_ui:height,width_ui:width,mode:workflow==='video-video'?'video-to-video':'image-to-video',duration_ui:duration,ui_frames_to_use:Math.floor((duration*24-1)/8)*8+1,seed_ui:seed,randomize_seed:random,ui_guidance_scale:1,improve_texture_flag:true}};
}
export function extractMedia(data,type) {
 const first=data?.[0];const media=first?.video||first;
 const url=typeof media==='string'?media:media?.url;
 if(!url||!/^https?:|^data:|^blob:/.test(url))throw Error('The model did not return a downloadable media URL.');
 return {url,type,seed:data?.[1],name:media?.orig_name || (type==='image'?'frame-result.png':'frame-result.mp4')};
}
export async function generateCloud(model,options,onEvent,signal,onCancelReady,hfToken='',connect=Client.connect) {
 const client=await connect(model.space,{events:['status','data'],...(hfToken?{hf_token:hfToken}:{}),status_callback:s=>onEvent({state:'connecting',detail:s.message||s.status})});
 if(signal.aborted)throw new DOMException('Cancelled','AbortError');
 const request=cloudRequest(model,options);const job=client.submit(request.endpoint,request.payload);
 onCancelReady(()=>job.cancel());let result;
 for await(const event of job){
  if(signal.aborted)throw new DOMException('Cancelled','AbortError');
  if(event.type==='status'){
   if(event.stage==='error'||event.success===false)throw Error(event.message||'Provider rejected this request.');
   const p=event.progress_data?.find(x=>typeof x.progress==='number');
   onEvent({state:event.stage==='generating'?'generating':event.stage==='complete'?'generating':'queued',detail:event.message||'',position:event.position,progress:p?Math.round(p.progress*100):null});
  }else if(event.type==='data')result=extractMedia(event.data,options.workflow==='text-image'?'image':'video');
 }
 if(!result)throw Error('No generation result received.');return result;
}
const headers=key=>key?{Authorization:'Bearer '+key}:{};
async function checked(response){if(!response.ok){let body;try{body=await response.json()}catch{}throw Error(typeof body?.detail==='string'?body.detail:JSON.stringify(body?.detail||response.statusText));}return response;}
export async function health(endpoint,key,signal){return (await checked(await fetch(endpoint+'/api/health',{headers:headers(key),signal}))).json();}
export async function generateLocal(model,options,onEvent,signal,onCancelReady,endpoint,key){
 const form=new FormData();for(const field of ['workflow','prompt','duration','aspect','seed','strength'])form.append(field,String(options[field]));form.append('model',model.id);if(options.file)form.append('file',options.file);
 const job=await (await checked(await fetch(endpoint+'/api/jobs',{method:'POST',headers:headers(key),body:form,signal}))).json();
 onCancelReady(()=>fetch(endpoint+'/api/jobs/'+encodeURIComponent(job.id),{method:'DELETE',headers:headers(key)}));
 while(!signal.aborted){
  const state=await(await checked(await fetch(endpoint+'/api/jobs/'+encodeURIComponent(job.id),{headers:headers(key),signal}))).json();
  if(state.status==='failed')throw Error(state.error||'Backend inference failed.');
  if(state.status==='cancelled')throw new DOMException('Cancelled','AbortError');
  if(state.status==='complete'||state.status==='succeeded'){
   const fileUrl=state.url||state.output_url||'/api/files/'+encodeURIComponent(job.id);
   const full=fileUrl.startsWith('http')?fileUrl:endpoint+fileUrl;
   const blob=await(await checked(await fetch(full,{headers:headers(key),signal}))).blob();
   return {url:URL.createObjectURL(blob),blob,type:options.workflow==='text-image'?'image':'video',seed:state.seed??options.seed,name:options.workflow==='text-image'?'frame-result.png':'frame-result.mp4'};
  }
  onEvent({state:state.status==='running'||state.status==='generating'?'generating':'queued',progress:state.progress,detail:state.message||''});
  await new Promise((resolve,reject)=>{const timer=setTimeout(done,1500);function done(){signal.removeEventListener('abort',abort);resolve()}function abort(){clearTimeout(timer);reject(new DOMException('Cancelled','AbortError'))}signal.addEventListener('abort',abort,{once:true})});
 }throw new DOMException('Cancelled','AbortError');
}
