import {renderFrame} from './motion-core.mjs';
let source=null, pixels=null;
self.onmessage=({data:m})=>{
 try{
  if(m.type==='init'){source=m.source;pixels=null;self.postMessage({id:m.id,ok:true});return;}
  if(m.type==='frame'){
   if(!source)throw Error('No image loaded');
   if(m.buffer instanceof ArrayBuffer&&m.buffer.byteLength===m.width*m.height*4)pixels=new Uint8ClampedArray(m.buffer);
   if(!pixels||pixels.length!==m.width*m.height*4)pixels=new Uint8ClampedArray(m.width*m.height*4);
   const began=performance.now();
   const frame=renderFrame(source,m.plan,m.time,m.duration,{width:m.width,height:m.height,data:pixels});
   self.postMessage({id:m.id,frame,renderMs:performance.now()-began},[frame.data.buffer]);
   pixels=null;return;
  }
  throw Error('Unknown renderer request');
 }catch(error){self.postMessage({id:m.id,error:error.message||String(error)});}
};
