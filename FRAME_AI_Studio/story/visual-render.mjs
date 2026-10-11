/** Local pixel motion and vector compositing. No generative image/video model.
 * All scene state is plain JSON. Pixel buffers are reused and bounded.
 */
import { parsePrompt, renderFrame as renderPixels } from '../edge/motion-core.mjs';
const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
const number=(v,d=0)=>Number.isFinite(Number(v))?Number(v):d;
export const VISUAL_LIMITS=Object.freeze({layers:8,layerCharacters:1500000,totalCharacters:4000000,maxPNGBytes:2000000});
export const OVERLAY_KINDS=Object.freeze(['sofa','plant','lamp','bird','fish','image']);
export const EFFECTS=Object.freeze(['none','water','sway','rain','snow']);
const caches=new WeakMap(), imageCache=new Map();
function canvas(w,h){const c=document.createElement('canvas');c.width=w;c.height=h;return c;}
export function normalizedRect(rect={}){
 const x=clamp(number(rect.x),0,.99),y=clamp(number(rect.y),0,.99);
 return{x,y,width:clamp(number(rect.width,1),.01,1-x),height:clamp(number(rect.height,1),.01,1-y)};
}
export function sanitizeVisual(value={}){
 const v=value&&typeof value==='object'?value:{};let characters=0;
 const layers=(Array.isArray(v.layers)?v.layers:[]).slice(0,VISUAL_LIMITS.layers).flatMap((layer,index)=>{
  if(!layer||!OVERLAY_KINDS.includes(layer.kind))return[];
  const item={id:String(layer.id||`layer-${index}`).slice(0,80),kind:layer.kind,x:clamp(number(layer.x,.5),0,1),y:clamp(number(layer.y,.62),0,1),scale:clamp(number(layer.scale,.32),.05,1.5),rotation:clamp(number(layer.rotation),-180,180),opacity:clamp(number(layer.opacity,1),.05,1),color:/^#[0-9a-f]{6}$/i.test(layer.color||'')?layer.color:'#79cdbc',animate:!!layer.animate};
  if(item.kind==='image'){
   const src=String(layer.src||'');
   if(!/^data:image\/png;base64,[a-z0-9+/=\s]+$/i.test(src)||src.length>VISUAL_LIMITS.layerCharacters||characters+src.length>VISUAL_LIMITS.totalCharacters)return[];
   characters+=src.length;item.src=src;
  }
  return[item];
 });
 return{version:1,prompt:String(v.prompt||'').slice(0,1200),effect:EFFECTS.includes(v.effect)?v.effect:'none',strength:clamp(number(v.strength,.65),0,1),region:normalizedRect(v.region||{x:0,y:.5,width:1,height:.5}),panorama:!!v.panorama,yaw:clamp(number(v.yaw),-180,180),sweep:clamp(number(v.sweep),0,180),layers};
}
/** Conservative clause rules only, not full natural-language negation. A clause
 * containing an explicit negative instruction is skipped as a whole. */
export function removeNegatedClauses(prompt=''){
 return String(prompt).split(/[,，;；。.!！?？\n]|\bbut\b|但是|不過|不过/iu).filter(clause=>!/(?:不要|不必|不需|不用|不想|禁止|避免|沒有|没有|無需|无需)|\b(?:no|not|never|without|avoid|don['’]?t|doesn['’]?t|do\s+not|sin|ohne|kein(?:e|en|er)?|sans|pas)\b/iu.test(clause)).join(', ');
}
export function compileVisualPrompt(prompt='',objects=[]){
 const accepted=removeNegatedClauses(prompt);
 const plan=parsePrompt(accepted,objects,{maxRegions:1});
 const effect=plan.recognized.includes('water')?'water':plan.recognized.includes('sway')?'sway':plan.recognized.includes('rain')?'rain':plan.recognized.includes('snow')?'snow':'none';
 const camera=plan.recognized.includes('zoomIn')?'zoom-in':plan.recognized.includes('zoomOut')?'zoom-out':plan.recognized.includes('left')?'pan-left':plan.recognized.includes('right')?'pan-right':null;
 const action=/大笑|微笑|笑起|讀書|读书|跳舞|換髮|换发|換衣|换衣|化妝|化妆|laugh|smil|read(?:ing)?|danc|hair|make.?up|clothes|outfit|dress|360|全景/i.test(prompt);
 return{effect,camera,matched:effect!=='none'||!!camera,unsupported:action||plan.unhandled.length>0,recognized:plan.recognized};
}
export function invalidateVisual(scene){const c=caches.get(scene);if(c){c.lastEffectKey='';c.lastPanoramaKey='';}}
function sourceOf(scene){return scene?.mediaType==='video'?scene.video:scene?.image;}
export function sourceSize(source){return{width:source?.naturalWidth||source?.videoWidth||source?.width||0,height:source?.naturalHeight||source?.videoHeight||source?.height||0};}
export function isPanoramaSource(scene){const d=sourceSize(sourceOf(scene));return scene?.mediaType!=='video'&&d.width>0&&Math.abs(d.width/d.height-2)<.06;}
function getCache(scene){let cached=caches.get(scene);if(!cached){cached={};caches.set(scene,cached)}return cached;}
function boundedSize(width,height,maxWidth=640,maxHeight=360){const ratio=Math.min(1,maxWidth/width,maxHeight/height);return{width:Math.max(1,Math.round(width*ratio)),height:Math.max(1,Math.round(height*ratio))};}
function sourcePixels(scene,panorama=false){
 const source=sourceOf(scene),d=sourceSize(source),cached=getCache(scene),key=panorama?'panoramaPixels':'pixels';
 if(!d.width||!d.height)return null;
 if(cached[key]?.source!==source){const size=boundedSize(d.width,d.height,panorama?1024:640,panorama?512:360),c=canvas(size.width,size.height),ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(source,0,0,size.width,size.height);cached[key]={source,data:ctx.getImageData(0,0,size.width,size.height)};cached.lastEffectKey='';cached.lastPanoramaKey='';}
 return cached[key].data;
}
function panoramaSource(scene,progress,v){
 const cached=getCache(scene),pixels=sourcePixels(scene,true);if(!pixels)return sourceOf(scene);
 const tick=Math.round(progress*Math.max(.1,number(scene.duration,5))*12),frameKey=[tick,v.yaw,v.sweep].join('|');
 if(cached.lastPanoramaKey===frameKey)return cached.pano.c;
 if(!cached.pano){const width=384,height=216,c=canvas(width,height),ctx=c.getContext('2d'),frame=ctx.createImageData(width,height),rays=new Float32Array(width*height*3),fov=Math.tan(75*Math.PI/360);let i=0;
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){const rx=(2*(x+.5)/width-1)*fov,ry=(1-2*(y+.5)/height)*fov*height/width,n=Math.hypot(rx,ry,1);rays[i++]=rx/n;rays[i++]=ry/n;rays[i++]=1/n;}
  cached.pano={c,ctx,frame,rays};
 }
 const{c,ctx,frame,rays}=cached.pano,yaw=(v.yaw+(progress-.5)*v.sweep)*Math.PI/180,co=Math.cos(yaw),si=Math.sin(yaw),sw=pixels.width,sh=pixels.height;
 for(let i=0,j=0;i<frame.data.length;i+=4,j+=3){const xx=rays[j]*co+rays[j+2]*si,zz=rays[j+2]*co-rays[j]*si;const u=(Math.atan2(xx,zz)/(2*Math.PI)+.5+1)%1,vv=.5-Math.asin(rays[j+1])/Math.PI;const sx=Math.min(sw-1,Math.floor(u*sw)),sy=clamp(Math.floor(vv*sh),0,sh-1),at=(sy*sw+sx)*4;frame.data[i]=pixels.data[at];frame.data[i+1]=pixels.data[at+1];frame.data[i+2]=pixels.data[at+2];frame.data[i+3]=pixels.data[at+3];}
 ctx.putImageData(frame,0,0);cached.lastPanoramaKey=frameKey;return c;
}
/** Return the unchanged source or a cached CPU effect canvas before cover crop. */
export function getVisualSource(scene,progress=0){
 const source=sourceOf(scene);if(!scene||!source||scene.mediaType==='video')return source;
 const v=scene.visual;if(!v)return source;
 const p=clamp(number(progress),0,1);
 if(v.panorama&&isPanoramaSource(scene))return panoramaSource(scene,p,v);
 if(!EFFECTS.includes(v.effect)||v.effect==='none'||number(v.strength,.65)<=0)return source;
 const pixels=sourcePixels(scene);if(!pixels)return source;
 const cached=getCache(scene),width=pixels.width,height=pixels.height;
 if(!cached.effect||cached.effect.c.width!==width||cached.effect.c.height!==height){const c=canvas(width,height),ctx=c.getContext('2d'),frame=ctx.createImageData(width,height);cached.effect={c,ctx,frame};}
 const{c,ctx,frame}=cached.effect;
 const region={...normalizedRect(v.region),type:v.effect==='water'?'water':'tree',feather:.16};
 const strength=clamp(number(v.strength,.65),0,1);
 const tick=Math.round(p*Math.max(.1,number(scene.duration,5))*12),frameKey=[tick,v.effect,strength,region.x,region.y,region.width,region.height].join('|');
 if(cached.lastEffectKey===frameKey)return c;
 const effect=v.effect==='water'?{kind:'wave',region,amplitude:.004+.03*strength,cycles:2}:v.effect==='sway'?{kind:'sway',region,amplitude:.06*strength,cycles:1}:{kind:v.effect,count:Math.round(12+75*strength)};
 renderPixels(pixels,{camera:{zoomStart:1,zoomEnd:1},effects:[effect],seed:314159},p,1,{width,height,data:frame.data});
 ctx.putImageData(frame,0,0);cached.lastEffectKey=frameKey;return c;
}
function path(ctx,points,fill,stroke){ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();if(fill){ctx.fillStyle=fill;ctx.fill()}if(stroke){ctx.strokeStyle=stroke;ctx.stroke()}}
function ellipse(ctx,x,y,rx,ry,fill,rotation=0){ctx.beginPath();ctx.ellipse(x,y,rx,ry,rotation,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();}
function rounded(ctx,x,y,w,h,r,fill){ctx.fillStyle=fill;ctx.beginPath();if(ctx.roundRect)ctx.roundRect(x,y,w,h,r);else ctx.rect(x,y,w,h);ctx.fill();}
function shape(ctx,kind,color,phase){
 ctx.lineWidth=.025;ctx.lineJoin='round';ctx.lineCap='round';
 if(kind==='sofa'){
  ellipse(ctx,0,.45,.56,.07,'rgba(0,0,0,.22)');rounded(ctx,-.49,-.24,.98,.51,.08,color);rounded(ctx,-.45,.04,.9,.30,.04,'#255f5a');
  rounded(ctx,-.37,-.15,.35,.36,.06,color);rounded(ctx,.02,-.15,.35,.36,.06,color);
  rounded(ctx,-.56,-.03,.16,.4,.05,color);rounded(ctx,.4,-.03,.16,.4,.05,color);
  path(ctx,[[-.44,.35],[-.38,.35],[-.38,.46],[-.44,.46]],'#715349');path(ctx,[[.38,.35],[.44,.35],[.44,.46],[.38,.46]],'#715349');
 }else if(kind==='plant'){
  ellipse(ctx,0,.48,.25,.04,'rgba(0,0,0,.2)');ctx.strokeStyle='#387b55';ctx.beginPath();ctx.moveTo(0,.13);ctx.bezierCurveTo(-.09,-.1,.13,-.25,.03,-.52);ctx.stroke();
  [[-.14,-.05,-.7],[.13,-.2,.7],[-.13,-.3,-.7],[.13,-.4,.7],[0,-.55,0]].forEach(([x,y,r])=>ellipse(ctx,x,y,.09,.18,color,r));
  path(ctx,[[-.25,.09],[.25,.09],[.17,.47],[-.17,.47]],'#ca8975');rounded(ctx,-.28,.07,.56,.08,.025,'#e1a391');
 }else if(kind==='lamp'){
  ellipse(ctx,0,.45,.32,.055,'rgba(0,0,0,.22)');ctx.strokeStyle='#c6b5a0';ctx.lineWidth=.04;ctx.beginPath();ctx.moveTo(0,-.2);ctx.lineTo(0,.4);ctx.stroke();ellipse(ctx,0,.4,.22,.04,'#a28b77');
  const g=ctx.createRadialGradient(0,-.1,.05,0,-.1,.6);g.addColorStop(0,'rgba(255,221,140,.17)');g.addColorStop(1,'rgba(255,221,140,0)');ellipse(ctx,0,-.1,.6,.6,g);
  path(ctx,[[-.2,-.52],[.2,-.52],[.33,-.14],[-.33,-.14]],color);ellipse(ctx,0,-.14,.33,.045,'#fff0c0');
 }else if(kind==='bird'){
  ctx.strokeStyle=color;ctx.lineWidth=.08;const lift=.16+Math.sin(phase)*.15;ctx.beginPath();ctx.moveTo(-.49,-lift);ctx.quadraticCurveTo(-.27,-.27,0,.05);ctx.quadraticCurveTo(.27,-.27,.49,-lift);ctx.stroke();ellipse(ctx,0,.045,.055,.11,color);path(ctx,[[-.035,.12],[.035,.12],[0,.23]],color);
 }else if(kind==='fish'){
  path(ctx,[[-.25,0],[-.5,-.22],[-.5,.22]],color);ellipse(ctx,0,0,.32,.19,color);path(ctx,[[-.11,-.14],[.02,-.3],[.12,-.14]],color);ellipse(ctx,.20,-.04,.028,.028,'#142b31');ctx.strokeStyle='rgba(255,255,255,.45)';ctx.beginPath();ctx.arc(.05,0,.13,-1.2,1.2);ctx.stroke();
 }
}
function imageAsset(src){if(!src)return null;let entry=imageCache.get(src);if(!entry){const img=new Image();entry={img,ready:false,promise:null};entry.promise=new Promise((resolve,reject)=>{img.onload=()=>{entry.ready=true;resolve(img)};img.onerror=()=>{entry.error=true;reject(new Error('Overlay image could not be decoded.'))};img.src=src;});entry.promise.catch(()=>{});imageCache.set(src,entry)}return entry;}
export async function prepareVisualAssets(scenes=[]){
 const sources=new Set(scenes.flatMap(s=>(s.visual?.layers||[]).filter(l=>l.kind==='image').map(l=>l.src)));
 for(const [src]of imageCache)if(!sources.has(src))imageCache.delete(src);
 await Promise.all([...sources].map(src=>imageAsset(src)?.promise));
}
/** Draw overlays in output coordinates. The surrounding scene transform/alpha is retained. */
export function drawVisual(ctx,scene,progress,width,height){
 const layers=scene?.visual?.layers;if(!Array.isArray(layers)||!layers.length)return;
 const p=clamp(number(progress),0,1),unit=Math.min(width,height);
 for(const layer of layers.slice(0,VISUAL_LIMITS.layers)){
  if(!OVERLAY_KINDS.includes(layer.kind))continue;
  ctx.save();const animated=layer.animate&&(layer.kind==='bird'||layer.kind==='fish'||layer.kind==='plant');
  const dx=animated&&layer.kind!=='plant'?Math.sin(p*Math.PI*2)*width*.06:0,dy=animated&&layer.kind==='bird'?Math.sin(p*Math.PI*4)*height*.015:0;
  ctx.translate(layer.x*width+dx,layer.y*height+dy);ctx.rotate((layer.rotation+(animated&&layer.kind==='plant'?Math.sin(p*Math.PI*2)*3:0))*Math.PI/180);const scale=unit*layer.scale;ctx.scale(scale,scale);ctx.globalAlpha*=layer.opacity;
  if(layer.kind==='image'){
   const a=imageAsset(layer.src);if(a?.ready){const ratio=a.img.naturalWidth/a.img.naturalHeight,w=ratio>=1?1:ratio,h=ratio>=1?1/ratio:1;ctx.drawImage(a.img,-w/2,-h/2,w,h);}
  }else shape(ctx,layer.kind,layer.color,animated?p*Math.PI*8:0);
  ctx.restore();
 }
}
export function visualAssetCharacters(scenes=[]){return scenes.reduce((n,s)=>n+(s.visual?.layers||[]).reduce((k,l)=>k+(l.src?.length||0),0),0)}
