import {build} from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(new URL('..',import.meta.url).pathname);
await build({entryPoints:[root+'/src/app.js'],bundle:true,format:'iife',target:'es2020',minify:true,loader:{'.webp':'dataurl'},outfile:root+'/dist/assets/app.bundle.js'});
let html=fs.readFileSync(root+'/dist/index.html','utf8');
const i18n=JSON.parse(fs.readFileSync(root+'/dist/assets/i18n.json'));
for(const [locale,dict]of Object.entries(i18n)){
 const dir=root+'/dist/'+locale;fs.mkdirSync(dir,{recursive:true});
 let page=html.replace('<html lang="zh-Hant">',`<html lang="${locale}" data-locale="${locale}"${locale==='ar'?' dir="rtl"':''}>`).replace('<head>','<head>\n<base href="../">');
 page=page.replace(/(<[^>]*data-i18n="([^"]+)"[^>]*>)([^<]*)(<\/[^>]+>)/g,(all,start,key,text,end)=>start+(dict[key]||text)+end);
 page=page.replace(/<title>.*?<\/title>/,()=>'<title>FRAME — '+dict.studio+'</title>');
 fs.writeFileSync(dir+'/index.html',page);
}
const css=fs.readFileSync(root+'/dist/assets/style.css','utf8');
const js=fs.readFileSync(root+'/dist/assets/app.bundle.js','utf8').replace(/<\/script/gi,'<\\/script');
const image='data:image/webp;base64,'+fs.readFileSync(root+'/dist/assets/demo-coast.webp').toString('base64');
let standalone=html.replace('<link rel="stylesheet" href="assets/style.css">',()=>'<style>'+css+'</style>').replace('<script src="assets/app.bundle.js" defer></script>',()=>'<script>'+js+'</script>').replaceAll('assets/demo-coast.webp',image).replace('href="assets/icon.svg"','href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 64 64%27%3E%3Crect width=%2764%27 height=%2764%27 rx=%2714%27 fill=%27%23b4a0ff%27/%3E%3Ctext x=%2720%27 y=%2748%27 font-size=%2742%27%3EF%3C/text%3E%3C/svg%3E"');
// The demo URLs occur in the bundled JavaScript as well as the HTML.
standalone=standalone.replaceAll('assets/demo-coast.webp',image);
fs.writeFileSync(root+'/FRAME_Standalone.html',standalone);
console.log('Built bundled UI, '+Object.keys(i18n).length+' locale pages and standalone HTML.');
