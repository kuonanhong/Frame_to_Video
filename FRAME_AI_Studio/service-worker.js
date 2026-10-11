/* Local-only cache. No accounts, location records, uploads, or paid endpoints. */
const CACHE='frame-story-v5-20261010-a';
const BASE=new URL('./',self.location.href);
const SHELL=['V5_START.html','VALIDATION_V5.html','MODEL_REALITY_GUIDE.html','GITHUB_PAT_GUIDE.html','edge/motion-core.mjs','story/advanced-ui.mjs','story/advanced-i18n.mjs','story/visual-tools.mjs','story/visual-render.mjs','story/expert-ui.mjs','story/app-v5.bundle.js','story/visual-tools.css','./','index.html','story/style.css','story/assets/fonts/jf-openhuninn.woff','story/app.mjs','story/index.html','story/media.mjs','story/i18n.mjs','edge/detector-client.mjs','使用與部署說明.html','story/assets/icon.svg','story/ai/client.mjs','story/ai/worker.mjs','story/models/manifest.json','offline-files.json','story.webmanifest','dist/assets/demo-coast.webp'];
self.addEventListener('install',event=>event.waitUntil((async()=>{const cache=await caches.open(CACHE);await cache.addAll(SHELL.map(p=>new URL(p,BASE).href));await self.skipWaiting()})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const key of await caches.keys())if(key.startsWith('frame-story-')&&key!==CACHE)await caches.delete(key);await self.clients.claim()})()));
self.addEventListener('fetch',event=>{
 if(event.request.method!=='GET'||event.request.headers.has('range'))return;
 const url=new URL(event.request.url);if(url.origin!==BASE.origin||!url.pathname.startsWith(BASE.pathname))return;
 const rel=url.pathname.slice(BASE.pathname.length);if(rel.startsWith('api/')||rel.startsWith('native_cpu/'))return;if(!(rel===''||rel==='index.html'||rel.startsWith('story/')||rel.startsWith('edge/model/')||rel.startsWith('edge/detector-')||rel==='edge/motion-core.mjs'||rel==='dist/assets/demo-coast.webp'||rel==='offline-files.json'||rel==='story.webmanifest'))return;
 if(rel===''||rel==='index.html'||rel==='story/'){event.respondWith((async()=>{const cache=await caches.open(CACHE);try{const r=await fetch(event.request);if(r.ok)await cache.put(event.request,r.clone());return r}catch{return await cache.match(event.request)||await cache.match(new URL(rel==='story/'?'story/index.html':'index.html',BASE).href)}})());return}
 event.respondWith((async()=>{const cache=await caches.open(CACHE);const hit=await cache.match(event.request);if(hit)return hit;const response=await fetch(event.request);if(response.ok)await cache.put(event.request,response.clone());return response})());
});
const cacheJobs=new Map();
self.addEventListener('message',event=>{
 if(event.data?.type==='CANCEL_CACHE'){cacheJobs.get(event.data.jobId)?.abort();return;}
 if(event.data?.type!=='CACHE_MODELS')return;
 const port=event.ports[0],controller=new AbortController();cacheJobs.set(event.data.jobId,controller);event.waitUntil((async()=>{try{const cache=await caches.open(CACHE);const response=await fetch(new URL('offline-files.json',BASE),{signal:controller.signal});if(!response.ok)throw new Error('Offline file index missing.');const list=await response.json();let done=0,bytes=0;for(const item of list.files){if(controller.signal.aborted)throw new DOMException('Cancelled','AbortError');const url=new URL(item.path,BASE).href;let r=await cache.match(url);if(!r){r=await fetch(url,{signal:controller.signal});if(!r.ok)throw new Error(item.path+': HTTP '+r.status);await cache.put(url,r.clone())}done++;bytes+=item.bytes;port?.postMessage({type:'progress',done,total:list.files.length})}port?.postMessage({type:'complete',files:done,bytes})}catch(error){port?.postMessage({type:'error',error:error.message})}finally{cacheJobs.delete(event.data.jobId)}})());
});
