import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
const source = fileURLToPath(new URL('./detector-worker-source.mjs', import.meta.url));
const output = fileURLToPath(new URL('../detector-worker.js', import.meta.url));
await build({
  entryPoints: [source], outfile: output, bundle: true, format: 'iife',
  platform: 'browser', target: ['es2020'], minify: true, legalComments: 'linked',
  banner: { js: '/* FRAME CPU detector: MIT adapter; TensorFlow.js and COCO-SSD Apache-2.0. See edge/model/licenses. */' }
});
console.log('Built CPU-only detector worker:', output);
