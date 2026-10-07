/* FRAME worker client, MIT. This module does not upload pictures. */
let worker = null;
let workerBlobUrl = null;
let loaded = false;
let loadPromise = null;
let sequence = 0;
const pending = new Map();
const abortError = () => new DOMException('Detection cancelled', 'AbortError');

function teardown(error = abortError()) {
  if (worker) worker.terminate();
  worker = null;
  loaded = false;
  loadPromise = null;
  if (workerBlobUrl) URL.revokeObjectURL(workerBlobUrl);
  workerBlobUrl = null;
  for (const entry of pending.values()) {
    clearTimeout(entry.timeout);
    entry.signal?.removeEventListener('abort', entry.onAbort);
    entry.reject(error);
  }
  pending.clear();
}

function createWorker({ workerSource, workerUrl } = {}) {
  if (worker) return;
  if (typeof Worker === 'undefined') throw new Error('Web Workers are not supported by this browser');
  if (workerSource) {
    workerBlobUrl = URL.createObjectURL(new Blob([workerSource], { type: 'text/javascript' }));
    // Self-contained IIFE uses a classic Blob worker: file:// module workers
    // may be blocked even where classic Blob workers are supported.
    worker = new Worker(workerBlobUrl, { name: 'frame-cpu-detector' });
  } else {
    worker = new Worker(workerUrl || new URL('./detector-worker.js', import.meta.url),
      { type: 'module', name: 'frame-cpu-detector' });
  }
  worker.onmessage = ({ data }) => {
    const entry = pending.get(data.requestId);
    if (!entry) return;
    if (data.type === 'progress') { entry.onProgress?.({ stage: data.stage, progress: data.progress }); return; }
    pending.delete(data.requestId);
    clearTimeout(entry.timeout);
    entry.signal?.removeEventListener('abort', entry.onAbort);
    if (data.type === 'error') entry.reject(new Error(data.error));
    else entry.resolve(data.result);
  };
  worker.onerror = event => teardown(new Error(event.message || 'CPU detector worker could not start'));
  worker.onmessageerror = () => teardown(new Error('Invalid message from detector worker'));
}

function request(type, payload, { signal, onProgress, transfer = [], timeoutMs = 180000 } = {}) {
  if (signal?.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const requestId = ++sequence;
    const onAbort = () => teardown(abortError());
    const timeout = setTimeout(() => teardown(new Error('CPU detector timed out; try a smaller picture')),
      timeoutMs);
    pending.set(requestId, { resolve, reject, signal, onProgress, onAbort, timeout });
    signal?.addEventListener('abort', onAbort, { once: true });
    try { worker.postMessage({ type, requestId, ...payload }, transfer); }
    catch (error) {
      pending.delete(requestId);
      clearTimeout(timeout);
      signal?.removeEventListener('abort', onAbort);
      reject(error);
    }
  });
}

/** Load the bundled CPU detector. Embedded model supports the single-file page.
 * @param {{onProgress?:Function,signal?:AbortSignal,workerSource?:string,
 * embeddedModel?:{modelTopology:Object,weightSpecs:Array,weightData:ArrayBuffer},
 * modelUrl?:string,workerUrl?:string}} options
 */
export async function loadDetector(options = {}) {
  if (options.signal?.aborted) throw abortError();
  if (loaded) return { backend: 'cpu', model: 'coco-ssd-lite-mobilenet-v2', classes: 80 };
  if (loadPromise) return loadPromise;
  createWorker(options);
  const embeddedModel = options.embeddedModel;
  // Embedded single-file pages need no URL; they may bundle import.meta away.
  const modelUrl = embeddedModel ? undefined :
    (options.modelUrl || new URL('./model/coco-ssd-lite/model.json', import.meta.url).href);
  const transfer = embeddedModel?.weightData instanceof ArrayBuffer ? [embeddedModel.weightData] : [];
  loadPromise = request('load', { options: { modelUrl, embeddedModel } },
    { signal: options.signal, onProgress: options.onProgress, transfer }).then(result => {
      loaded = true;
      return result;
    }).catch(error => { teardown(error); throw error; });
  return loadPromise;
}

/** Detect a photograph once, before constructing animation. Returns original pixel coordinates. */
export async function detectImage(imageData, { minScore = .45, maxObjects = 20, signal } = {}) {
  if (signal?.aborted) throw abortError();
  if (!loaded) await loadDetector({ signal });
  const { width, height, data } = imageData || {};
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 ||
      width * height > 24000000 || !data || data.length !== width * height * 4) {
    throw new Error('Expected ImageData of at most 24 megapixels');
  }
  // Copy once: transferring this buffer must not detach the caller's ImageData.
  const copy = new Uint8ClampedArray(data);
  return request('detect', { image: { width, height, data: copy }, options: { minScore, maxObjects } },
    { signal, transfer: [copy.buffer] });
}

export function disposeDetector() { teardown(); }
export function detectorReady() { return loaded; }
