import test from 'node:test';
import assert from 'node:assert/strict';
import {sanitizeVisual,normalizedRect,compileVisualPrompt,removeNegatedClauses,visualAssetCharacters,isPanoramaSource,getVisualSource,invalidateVisual} from '../visual-render.mjs';

test('semantic human actions are not misreported as generated animation',()=>{
 const result=compileVisualPrompt('沈浸讀書後大笑');
 assert.equal(result.matched,false);assert.equal(result.unsupported,true);assert.equal(result.effect,'none');
 assert.equal(compileVisualPrompt('woman laughing with a new hairstyle').unsupported,true);
});
test('supported recipes remain separate from unsupported clauses',()=>{
 const result=compileVisualPrompt('water ripples and zoom in');
 assert.equal(result.effect,'water');assert.equal(result.camera,'zoom-in');assert.equal(result.matched,true);
 assert.equal(compileVisualPrompt('laugh while it rains').unsupported,true);
});
test('explicit negative clauses never activate their named effects',()=>{
 for(const text of ['不要下雪','no snow','without rain','do not add snow','don’t add rain','avoid rain','kein Schnee']){
  assert.equal(compileVisualPrompt(text).effect,'none',text);
 }
 assert.equal(compileVisualPrompt('不要下雪，水面波紋').effect,'water');
 assert.equal(compileVisualPrompt('no snow; water ripples').effect,'water');
 assert.equal(compileVisualPrompt('without rain but snow').effect,'snow');
 assert.equal(removeNegatedClauses('rain, no snow').trim(),'rain');
});
test('untrusted project visual state is whitelisted and clamped',()=>{
 const value=sanitizeVisual({prompt:'x'.repeat(4000),effect:'eval',strength:999,region:{x:3,y:-8,width:99,height:Infinity},yaw:900,layers:[{kind:'image',src:'https://example.org/track.png'},{kind:'image',src:'data:image/svg+xml;base64,PHN2Zz4='},{kind:'plant',x:-2,y:9,scale:30,color:'url(https://evil)',rotation:Infinity,opacity:3}]});
 assert.equal(value.prompt.length,1200);assert.equal(value.effect,'none');assert.equal(value.strength,1);assert.equal(value.yaw,180);assert.equal(value.layers.length,1);assert.equal(value.layers[0].x,0);assert.equal(value.layers[0].y,1);assert.equal(value.layers[0].scale,1.5);assert.equal(value.layers[0].color,'#79cdbc');
 assert.equal(Object.getPrototypeOf(value),Object.prototype);
});
test('PNG payload and per-scene layer budgets are enforced',()=>{
 const src='data:image/png;base64,'+'A'.repeat(1400000);
 const v=sanitizeVisual({layers:Array.from({length:12},(_,i)=>({id:String(i),kind:'image',src}))});
 assert.equal(v.layers.length,2);assert.equal(visualAssetCharacters([{visual:v}]),src.length*2);
 assert.equal(sanitizeVisual({layers:Array.from({length:12},()=>({kind:'plant'}))}).layers.length,8);
});
test('regions stay within source coordinates and cloning isolates state',()=>{
 const rect=normalizedRect({x:.8,y:.7,width:.9,height:.9});assert.ok(rect.x+rect.width<=1);assert.ok(rect.y+rect.height<=1);
 const original=sanitizeVisual({layers:[{id:'a',kind:'sofa',x:.4}]}),clone=sanitizeVisual(original);clone.layers[0].x=.9;clone.region.x=.3;
 assert.equal(original.layers[0].x,.4);assert.equal(original.region.x,0);
});
test('panorama eligibility is only a dimensions check, never scene reconstruction',()=>{
 assert.equal(isPanoramaSource({mediaType:'image',image:{naturalWidth:2000,naturalHeight:1000}}),true);
 assert.equal(isPanoramaSource({mediaType:'image',image:{naturalWidth:1920,naturalHeight:1080}}),false);
 assert.equal(isPanoramaSource({mediaType:'video',video:{videoWidth:2000,videoHeight:1000}}),false);
});
test('CPU pixel rendering reuses bounded buffers and invalidates edited frames',()=>{
 const saved=globalThis.document;let allocations=0;
 globalThis.document={createElement(name){assert.equal(name,'canvas');let last=null;const c={width:0,height:0,getContext(){return{drawImage(){},getImageData(x,y,w,h){allocations++;const data=new Uint8ClampedArray(w*h*4);for(let i=0;i<data.length;i+=4){data[i]=i%251;data[i+1]=80;data[i+2]=190;data[i+3]=255;}return{width:w,height:h,data}},createImageData(w,h){allocations++;return{width:w,height:h,data:new Uint8ClampedArray(w*h*4)}},putImageData(frame){last=frame}}},get last(){return last}};return c;}};
 try{
  const scene={mediaType:'image',image:{naturalWidth:1600,naturalHeight:900},duration:5,visual:sanitizeVisual({effect:'water'})};
  const a=getVisualSource(scene,.25),before=allocations;assert.equal(a.width,640);assert.equal(a.height,360);
  const b=getVisualSource(scene,.26);assert.equal(a,b);assert.equal(allocations,before);
  scene.visual.strength=.3;invalidateVisual(scene);getVisualSource(scene,.26);assert.equal(allocations,before);
  scene.visual.effect='none';assert.equal(getVisualSource(scene,.3),scene.image);
 }finally{globalThis.document=saved;}
});
