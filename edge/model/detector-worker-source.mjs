/* FRAME CPU detector adapter. Project code: MIT.
 * TensorFlow.js / COCO-SSD: Google LLC, Apache-2.0, see model/licenses.
 * Only the JavaScript CPU backend is bundled; no WebGL/WebGPU backend.
 */
import * as tf from '@tensorflow/tfjs-core';
import '@tensorflow/tfjs-backend-cpu';
import * as cocoSsd from '@tensorflow-models/coco-ssd';
import cocoClasses from './coco-classes.json';

const CLASS_IDS = new Map(cocoClasses.map(c => [c.label, c.id]));
let detector = null;
let modelPromise = null;
const notify = message => {
  if (typeof self !== 'undefined' && typeof self.postMessage === 'function') self.postMessage(message);
};

export async function loadCpuModel({ modelUrl, embeddedModel, requestId } = {}) {
  if (detector) return { backend: tf.getBackend(), model: 'coco-ssd-lite-mobilenet-v2', classes: 80 };
  if (!modelPromise) modelPromise = (async () => {
    await tf.setBackend('cpu');
    await tf.ready();
    if (tf.getBackend() !== 'cpu') throw new Error('CPU backend unavailable');
    notify({ type: 'progress', requestId, stage: 'loading-model', progress: 0.1 });
    let modelSource = modelUrl;
    if (embeddedModel) {
      if (!embeddedModel.modelTopology || !Array.isArray(embeddedModel.weightSpecs) ||
          !(embeddedModel.weightData instanceof ArrayBuffer)) throw new Error('Invalid embedded model');
      // coco-ssd 2.2.3 delegates modelUrl directly to loadGraphModel. The latter
      // supports IOHandler; tf.io.fromMemory is its official in-memory handler.
      modelSource = tf.io.fromMemory({
        modelTopology: embeddedModel.modelTopology,
        weightSpecs: embeddedModel.weightSpecs,
        weightData: embeddedModel.weightData
      });
    }
    if (!modelSource) throw new Error('A local model URL or embedded model is required');
    detector = await cocoSsd.load({ base: 'lite_mobilenet_v2', modelUrl: modelSource });
    notify({ type: 'progress', requestId, stage: 'ready', progress: 1 });
    return { backend: tf.getBackend(), model: 'coco-ssd-lite-mobilenet-v2', classes: 80 };
  })().catch(error => { modelPromise = null; detector = null; throw error; });
  return modelPromise;
}

export function rgbaToRgb({ data, width, height }, maxSide = 640) {
  if (!(data instanceof Uint8Array || data instanceof Uint8ClampedArray) ||
      !Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 ||
      width * height > 24000000 || data.length !== width * height * 4) {
    throw new Error('Expected RGBA ImageData of at most 24 megapixels');
  }
  const scale = Math.min(1, maxSide / Math.max(width, height));
  const w = Math.max(1, Math.round(width * scale));
  const h = Math.max(1, Math.round(height * scale));
  const rgb = new Int32Array(w * h * 3);
  // Resample once before tensor creation to bound memory for large photographs.
  // Blend transparent pixels against white; do not treat their hidden RGB as an object.
  for (let y = 0; y < h; y++) {
    const sy = Math.min(height - 1, Math.floor((y + .5) * height / h));
    for (let x = 0; x < w; x++) {
      const sx = Math.min(width - 1, Math.floor((x + .5) * width / w));
      const src = (sy * width + sx) * 4;
      const dst = (y * w + x) * 3;
      const a = data[src + 3] / 255;
      for (let c = 0; c < 3; c++) rgb[dst + c] = Math.round(data[src + c] * a + 255 * (1 - a));
    }
  }
  return { rgb, width: w, height: h, scaleX: width / w, scaleY: height / h };
}

export async function detectPixels(image, { minScore = .45, maxObjects = 20 } = {}) {
  if (!detector) throw new Error('Detector not loaded');
  minScore = Math.max(.05, Math.min(.99, Number(minScore) || .45));
  maxObjects = Math.max(1, Math.min(30, Math.round(Number(maxObjects) || 20)));
  const small = rgbaToRgb(image);
  const input = tf.tensor3d(small.rgb, [small.height, small.width, 3], 'int32');
  try {
    const objects = await detector.detect(input, maxObjects, minScore);
    return objects.map(obj => {
      const [sx, sy, sw, sh] = obj.bbox;
      const x = Math.max(0, Math.min(image.width, sx * small.scaleX));
      const y = Math.max(0, Math.min(image.height, sy * small.scaleY));
      const right = Math.max(x, Math.min(image.width, (sx + sw) * small.scaleX));
      const bottom = Math.max(y, Math.min(image.height, (sy + sh) * small.scaleY));
      return { label: obj.class, classId: CLASS_IDS.get(obj.class), score: obj.score,
        bbox: [x, y, right - x, bottom - y] };
    }).filter(obj => obj.bbox[2] > 0 && obj.bbox[3] > 0 && obj.score >= minScore);
  } finally {
    input.dispose();
  }
}

export function disposeCpuModel() {
  if (detector) detector.dispose();
  detector = null;
  modelPromise = null;
}

// Serialize requests: one model and one inference per tab, not one per video frame.
if (typeof self !== 'undefined' && typeof self.postMessage === 'function') {
  let queue = Promise.resolve();
  self.onmessage = event => {
    const message = event.data;
    queue = queue.then(async () => {
      const requestId = message.requestId;
      try {
        let result;
        if (message.type === 'load') result = await loadCpuModel({ ...message.options, requestId });
        else if (message.type === 'detect') result = await detectPixels(message.image, message.options);
        else if (message.type === 'dispose') { disposeCpuModel(); result = true; }
        else throw new Error('Unknown detector request');
        notify({ type: 'result', requestId, result });
      } catch (error) {
        notify({ type: 'error', requestId, error: String(error?.message || error) });
      }
    });
  };
}
