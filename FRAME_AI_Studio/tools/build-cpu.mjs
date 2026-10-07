import {build} from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('..',import.meta.url));
const edge=path.join(root,'edge');
await build({entryPoints:[path.join(edge,'app.mjs')],bundle:true,format:'iife',target:'es2020',minify:true,loader:{'.webp':'dataurl'},outfile:path.join(edge,'app.bundle.js')});
await build({entryPoints:[path.join(edge,'motion-worker.js')],bundle:true,format:'iife',target:'es2020',minify:true,outfile:path.join(edge,'motion-worker.bundle.js')});
const html=fs.readFileSync(path.join(edge,'index.html'),'utf8');
const locales=JSON.parse(fs.readFileSync(path.join(edge,'locales.json'),'utf8'));
const replaceLocale=(page,code)=>page.replace('<html lang="zh-Hant">',`<html lang="${code}" data-locale="${code}"${code==='ar'?' dir="rtl"':''}>`).replace(/(<[^>]*data-i18n="([^"]+)"[^>]*>)([^<]*)(<\/[^>]+>)/g,(a,b,k,c,d)=>b+escape(locales[code][k]||c)+d).replace(/<title>.*?<\/title>/,()=>'<title>FRAME CPU — '+escape(locales[code].title)+'</title>');
function escape(value){return String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');}
for(const code of Object.keys(locales)){const dir=path.join(edge,'l',code);fs.mkdirSync(dir,{recursive:true});fs.writeFileSync(path.join(dir,'index.html'),replaceLocale(html,code).replace('<head>','<head>\n<base href="../../">'));}
fs.writeFileSync(path.join(root,'index.html'),html.replace('<head>','<head>\n<base href="edge/">'));
const modelDir=path.join(edge,'model/coco-ssd-lite');
const json=JSON.parse(fs.readFileSync(path.join(modelDir,'model.json'),'utf8'));
const paths=json.weightsManifest.flatMap(group=>group.paths);
const weights=Buffer.concat(paths.map(p=>fs.readFileSync(path.join(modelDir,p)))).toString('base64');
const inline=v=>JSON.stringify(v).replaceAll('<','\\u003c');
const globals='window.__FRAME_EMBEDDED_MODEL__='+inline({json,weights})+';window.__FRAME_DETECTOR_WORKER__='+inline(fs.readFileSync(path.join(edge,'detector-worker.js'),'utf8'))+';window.__FRAME_MOTION_WORKER__='+inline(fs.readFileSync(path.join(edge,'motion-worker.bundle.js'),'utf8'))+';';
let standalone=html.replace('<link rel="stylesheet" href="style.css">',()=>'<style>'+fs.readFileSync(path.join(edge,'style.css'),'utf8')+'</style>');
const app=fs.readFileSync(path.join(edge,'app.bundle.js'),'utf8').replace(/<\/script/gi,'<\\/script');
standalone=standalone.replace('<script src="app.bundle.js" defer></script>',()=>'<script>'+globals+'\n'+app+'</script>');
// Documentation/classic links remain useful in the package; no network is needed for CPU processing.
standalone=standalone.replace('href="../dist/"','href="dist/"').replaceAll('href="../docs/','href="docs/');
const notices=['FRAME original adapter and motion code — MIT\n'+fs.readFileSync(path.join(root,'LICENSE'),'utf8'),'TensorFlow.js / COCO-SSD / model — Apache-2.0\n'+fs.readFileSync(path.join(edge,'model/licenses/tensorflow-models-Apache-2.0.txt'),'utf8'),'Runtime third-party notices\n'+fs.readFileSync(path.join(edge,'detector-worker.js.LEGAL.txt'),'utf8'),'long — Apache-2.0\n'+fs.readFileSync(path.join(edge,'model/licenses/long-Apache-2.0.txt'),'utf8'),'seedrandom — MIT\n'+fs.readFileSync(path.join(edge,'model/licenses/seedrandom-MIT.txt'),'utf8')].join('\n\n');
standalone=standalone.replace('</main>',()=>'<details style="font-size:11px;color:#a7aabf;margin:20px 0"><summary>OPEN SOURCE LICENSES / THIRD-PARTY NOTICES</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto">'+escape(notices)+'</pre></details></main>');
fs.writeFileSync(path.join(root,'FRAME_CPU_Studio.html'),standalone);
console.log(`Built CPU studio, ${Object.keys(locales).length} locale pages, local model, root index and self-contained HTML (${(Buffer.byteLength(standalone)/1024/1024).toFixed(1)} MiB).`);
