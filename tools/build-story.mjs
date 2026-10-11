import fs from 'node:fs';import path from 'node:path';import{fileURLToPath}from'node:url';
const root=fileURLToPath(new URL('..',import.meta.url)),files=[];
function walk(dir){for(const name of fs.readdirSync(dir)){const p=path.join(dir,name),s=fs.statSync(p);if(s.isDirectory())walk(p);else if(!/\.(md|tgz|tar|gz|txt|download)$/.test(name)&&!p.includes(`${path.sep}tests${path.sep}`)&&!p.includes(`${path.sep}source${path.sep}`))files.push({path:path.relative(root,p).split(path.sep).join('/'),bytes:s.size})}}
for(const rel of ['story','edge/model/coco-ssd-lite'])walk(path.join(root,rel));
for(const rel of ['V5_START.html','VALIDATION_V5.html','MODEL_REALITY_GUIDE.html','GITHUB_PAT_GUIDE.html','edge/motion-core.mjs','edge/detector-client.mjs','edge/detector-worker.js','index.html','service-worker.js','story.webmanifest','dist/assets/demo-coast.webp'])files.push({path:rel,bytes:fs.statSync(path.join(root,rel)).size});
fs.writeFileSync(path.join(root,'offline-files.json'),JSON.stringify({version:5,files},null,2));
console.log(`Offline index: ${files.length} files / ${(files.reduce((n,f)=>n+f.bytes,0)/1024/1024).toFixed(1)} MiB`);
