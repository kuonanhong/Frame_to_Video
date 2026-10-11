/** Build classic JavaScript entry: file:// editing no longer depends on ESM fetch. */
import fs from 'node:fs';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';
const root=fileURLToPath(new URL('..',import.meta.url));
const {build}=process.env.FRAME_ESBUILD?await import(pathToFileURL(process.env.FRAME_ESBUILD)):await import('esbuild');
const image='data:image/webp;base64,'+fs.readFileSync(path.join(root,'dist/assets/demo-coast.webp')).toString('base64');
await build({entryPoints:[path.join(root,'story/app.mjs')],outfile:path.join(root,'story/app-v5.bundle.js'),bundle:true,format:'iife',platform:'browser',target:['es2020'],minify:true,legalComments:'eof',logOverride:{'empty-import-meta':'silent'},banner:{js:'/* FRAME Story Studio 5. Browser editor. CPU model weights are local assets. */\nglobalThis.__FRAME_DEMO__='+JSON.stringify(image)+';'}});
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
fs.writeFileSync(path.join(root,'story/index.html'),html.replace('<head>','<head><base href="../">'));
console.log('Built classic-script editor and root/story entries.');
