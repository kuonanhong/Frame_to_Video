import {getVisualSource,drawVisual} from './visual-render.mjs';
/**
 * FRAME local media engine. No network requests, remote encoder, or watermark.
 * MediaRecorder exports in real time; capability checks never imply every device
 * supports the same container. Audio must be an actual decoded AudioBuffer.
 */
const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const durationOf = scene => Math.max(0.1, finite(scene?.duration, 4));
let activeExport = false;

export function totalDuration(scenes = []) {
  return scenes.reduce((sum, scene) => sum + durationOf(scene), 0);
}

export function locateScene(scenes = [], time = 0) {
  if (!scenes.length) return null;
  const total = totalDuration(scenes);
  const t = clamp(finite(time), 0, Math.max(0, total - 1e-8));
  let start = 0;
  for (let index = 0; index < scenes.length; index++) {
    const duration = durationOf(scenes[index]);
    if (t < start + duration || index === scenes.length - 1) {
      const localTime = clamp(t - start, 0, duration);
      return { scene: scenes[index], index, start, end: start + duration, duration, localTime, progress: localTime / duration };
    }
    start += duration;
  }
  return null;
}

/** Source-space cover crop. Camera movements preserve the source aspect ratio. */
export function cropRect(sw, sh, tw, th, progress = 0, motion = 'still') {
  if (![sw, sh, tw, th].every(x => Number.isFinite(x) && x > 0)) throw new RangeError('Image dimensions must be positive.');
  const p = clamp(finite(progress), 0, 1);
  const baseW = Math.min(sw, sh * tw / th);
  const baseH = Math.min(sh, sw * th / tw);
  let zoom = 1, px = 0.5, py = 0.5;
  const smooth = p * p * (3 - 2 * p);
  if (motion === 'zoom-in') zoom = 1 + 0.14 * smooth;
  if (motion === 'zoom-out') zoom = 1.14 - 0.14 * smooth;
  if (motion === 'pan-left') { zoom = 1.10; px = 0.8 - 0.6 * smooth; }
  if (motion === 'pan-right') { zoom = 1.10; px = 0.2 + 0.6 * smooth; }
  zoom = Math.max(1, zoom);
  const width = baseW / zoom, height = baseH / zoom;
  return { x: Math.max(0, sw - width) * px, y: Math.max(0, sh - height) * py, width, height };
}

function sourceFor(scene) { return scene?.mediaType === 'video' ? scene.video : scene?.image; }
function sourceDimensions(source) {
  return { width: source?.videoWidth || source?.naturalWidth || source?.width || 0,
    height: source?.videoHeight || source?.naturalHeight || source?.height || 0 };
}

function drawScene(ctx, scene, progress, width, height) {
  const source = scene?.mediaType==='video'?sourceFor(scene):getVisualSource(scene,progress), dims = sourceDimensions(source);
  if (!source || !dims.width || !dims.height) {
    ctx.fillStyle = '#111'; ctx.fillRect(0, 0, width, height); return;
  }
  const rect = cropRect(dims.width, dims.height, width, height, progress, scene.motion);
  ctx.save();
  ctx.filter = `brightness(${clamp(finite(scene.brightness, 1), .2, 3)}) contrast(${clamp(finite(scene.contrast, 1), .2, 3)}) saturate(${clamp(finite(scene.saturation, 1), 0, 3)})`;
  ctx.drawImage(source, rect.x, rect.y, rect.width, rect.height, 0, 0, width, height);
  ctx.filter = 'none';
  const warmth = clamp(finite(scene.warmth), -1, 1);
  if (warmth) {
    ctx.globalCompositeOperation = 'source-atop';
    ctx.globalAlpha *= Math.abs(warmth) * 0.18;
    ctx.fillStyle = warmth > 0 ? '#ff8a27' : '#3294ff';
    ctx.fillRect(0, 0, width, height);
  }
  ctx.restore();
  drawVisual(ctx,scene,progress,width,height);
}

function wrapCaption(ctx, text, maxWidth) {
  const result = [];
  for (const paragraph of String(text).replace(/\r/g, '').split('\n')) {
    // Grapheme segmentation keeps emoji and combining marks intact. Whitespace
    // becomes the preferred break point, while CJK can break between graphemes.
    const segments = typeof Intl.Segmenter === 'function'
      ? Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(paragraph), x => x.segment)
      : Array.from(paragraph);
    let line = '', lastSpace = -1;
    for (const segment of segments) {
      const next = line + segment;
      if (line && ctx.measureText(next).width > maxWidth) {
        if (lastSpace > 0) {
          result.push(line.slice(0, lastSpace).trimEnd());
          line = line.slice(lastSpace + 1) + segment;
        } else { result.push(line); line = segment; }
        lastSpace = line.lastIndexOf(' ');
      } else {
        line = next;
        if (/\s/.test(segment)) lastSpace = line.length - 1;
      }
    }
    result.push(line.trim());
  }
  return result;
}

function drawCaption(ctx, text, width, height, settings) {
  if (!text || settings.subtitle === false) return;
  ctx.save();
  const size = clamp(finite(settings.subtitleSize, 28), 12, Math.max(16, height / 9));
  ctx.font = `600 ${size}px ${settings.fontFamily || 'system-ui, sans-serif'}`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.direction = /[\u0590-\u08ff]/.test(text) ? 'rtl' : 'ltr';
  const lines = wrapCaption(ctx, text, width * .86);
  const lineHeight = size * 1.35;
  const boxHeight = Math.min(height * .65, lines.length * lineHeight + size);
  const bottom = height * .945, top = bottom - boxHeight;
  ctx.fillStyle = 'rgba(0,0,0,.64)';
  ctx.fillRect(width * .045, top, width * .91, boxHeight);
  ctx.fillStyle = settings.subtitleColor || '#ffffff';
  const maxLines = Math.max(1, Math.floor((boxHeight - size * .45) / lineHeight));
  const displayed = lines.slice(0, maxLines);
  if (lines.length > maxLines) displayed[maxLines - 1] += '…';
  displayed.forEach((line, i) => ctx.fillText(line, width / 2, top + size * .5 + lineHeight * (i + .5), width * .86));
  ctx.restore();
}

/** Preview rendering is synchronous. Call prepareVideoFrames before seeking. */
export function renderFrame(ctx, { scenes = [], time = 0, width = ctx.canvas.width,
  height = ctx.canvas.height, settings = {} } = {}) {
  ctx.save(); ctx.filter = 'none'; ctx.globalAlpha = 1;
  ctx.fillStyle = settings.background || '#111'; ctx.fillRect(0, 0, width, height);
  const position = locateScene(scenes, time);
  if (!position) { ctx.restore(); return; }
  const { scene, index, localTime, progress } = position;
  const transitionDuration = Math.min(durationOf(scene) / 2, clamp(finite(scene.transitionDuration, .5), 0, 2));
  const transition = index > 0 && scene.transition !== 'cut' && transitionDuration > 0 && localTime < transitionDuration;
  if (transition) {
    const mix = clamp(localTime / transitionDuration, 0, 1);
    drawScene(ctx, scenes[index - 1], 1, width, height);
    ctx.save();
    if (scene.transition === 'slide') ctx.translate(width * (1 - mix), 0);
    else ctx.globalAlpha = mix;
    drawScene(ctx, scene, progress, width, height);
    ctx.restore();
  } else drawScene(ctx, scene, progress, width, height);
  drawCaption(ctx, scene.subtitle || scene.narration || '', width, height, settings);
  ctx.restore();
}

function abortError() { return new DOMException('Video export was cancelled.', 'AbortError'); }
function throwIfAborted(signal) { if (signal?.aborted) throw abortError(); }
function mediaTarget(scene, localTime) {
  const start = Math.max(0, finite(scene.trimStart));
  const duration = Number.isFinite(scene.video?.duration) ? scene.video.duration : Infinity;
  const end = scene.trimEnd == null ? duration : Math.min(duration, Math.max(start, finite(scene.trimEnd, duration)));
  return Math.max(start, Math.min(start + Math.max(0, localTime), end - .035));
}

function waitEvent(target, success, { signal, timeout = 12000, errors = ['error'] } = {}) {
  return new Promise((resolve, reject) => {
    let timer;
    const finish = (error) => {
      clearTimeout(timer); target.removeEventListener(success, ready);
      errors.forEach(type => target.removeEventListener(type, failed));
      signal?.removeEventListener('abort', cancelled);
      error ? reject(error) : resolve();
    };
    const ready = () => finish();
    const failed = () => finish(new Error('This media file cannot be decoded in this browser. Try a JPEG/PNG image, or H.264 MP4 video.'));
    const cancelled = () => finish(abortError());
    target.addEventListener(success, ready, { once: true });
    errors.forEach(type => target.addEventListener(type, failed, { once: true }));
    signal?.addEventListener('abort', cancelled, { once: true });
    timer = setTimeout(() => finish(new Error('Media loading or seeking timed out. Use a smaller local file and retry.')), timeout);
    if (signal?.aborted) cancelled();
  });
}

async function seekVideo(video, target, signal) {
  throwIfAborted(signal);
  if (video.readyState < 1) await waitEvent(video, 'loadedmetadata', { signal });
  if (Math.abs(video.currentTime - target) < .035 && video.readyState >= 2) return;
  const ready = waitEvent(video, 'seeked', { signal });
  video.currentTime = target;
  await ready;
  if (video.readyState < 2) await waitEvent(video, 'loadeddata', { signal });
}

export async function prepareVideoFrames(scenes, time, signal) {
  const position = locateScene(scenes, time);
  if (!position) return;
  const { scene, index, localTime } = position;
  const pending = [];
  if (scene.mediaType === 'video' && scene.video) pending.push(seekVideo(scene.video, mediaTarget(scene, localTime), signal));
  if (index > 0 && scene.transition !== 'cut' && localTime < finite(scene.transitionDuration, .5)) {
    const previous = scenes[index - 1];
    if (previous.mediaType === 'video' && previous.video && previous.video !== scene.video) {
      pending.push(seekVideo(previous.video, mediaTarget(previous, durationOf(previous)), signal));
    }
  }
  await Promise.all(pending);
}

/** Extend a scene instead of silently cutting a generated/recorded narration. */
export function fitAudioDurations(scenes = [], audioTracks = []) {
  const warnings = [];
  const fitted = scenes.map(scene => {
    const old = durationOf(scene);
    const required = audioTracks.filter(track => track.sceneId === scene.id && track.buffer)
      .reduce((max, track) => Math.max(max, Math.max(0, finite(track.offset)) + finite(track.buffer.duration)), old);
    if (required > old + .02) warnings.push(`Scene ${scene.id}: duration extended from ${old.toFixed(2)} s to ${required.toFixed(2)} s to preserve the complete narration.`);
    return { ...scene, duration: required };
  });
  return { scenes: fitted, warnings };
}

export function getExportCapabilities(settings = {}) {
  const Recorder = globalThis.MediaRecorder;
  const hasCanvas = typeof document !== 'undefined' && typeof document.createElement('canvas').captureStream === 'function';
  const preferred = settings.format || 'auto';
  const mp4Avc = ['video/mp4;codecs=avc1.42E01E,mp4a.40.2', 'video/mp4;codecs=avc1.42001E,mp4a.40.2', 'video/mp4;codecs=avc1,mp4a.40.2'];
  const mp4 = [...mp4Avc, 'video/mp4'];
  const webm = ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp9,opus', 'video/webm'];
  // Chromium builds can support generic MP4 using VP9/Opus even without an
  // H.264 encoder. Auto prefers an explicit H.264 MP4, then VP8 WebM, rather
  // than implying that every .mp4 is compatible with older Apple players.
  const candidates = preferred === 'mp4' ? mp4 : preferred === 'webm' ? webm : [...mp4Avc, ...webm, 'video/mp4'];
  const mime = typeof Recorder?.isTypeSupported === 'function' ? candidates.find(type => Recorder.isTypeSupported(type)) : null;
  return { supported: Boolean(Recorder && hasCanvas && mime), mime: mime || '',
    extension: mime?.startsWith('video/mp4') ? 'mp4' : 'webm', audio: Boolean(globalThis.AudioContext || globalThis.webkitAudioContext),
    reason: !Recorder || !hasCanvas ? 'This browser cannot record a canvas video. Use current Chrome, Edge, Firefox, or a Safari version supporting MediaRecorder and canvas.captureStream.'
      : !mime ? `${preferred === 'mp4' ? 'MP4' : 'Video'} encoding is unavailable here. Select Auto/WebM, or use a current desktop browser.` : '' };
}

function exportSettings(settings) {
  const width = Math.round(clamp(finite(settings.width, 960), 160, 1280) / 2) * 2;
  const height = Math.round(clamp(finite(settings.height, 540), 160, 1280) / 2) * 2;
  const scale = Math.min(1, 921600 / (width * height));
  return { ...settings, width: Math.floor(width * Math.sqrt(scale) / 2) * 2,
    height: Math.floor(height * Math.sqrt(scale) / 2) * 2, fps: Math.round(clamp(finite(settings.fps, 24), 10, 30)) };
}

function addAudioSource(context, destination, sources, { buffer, volume, start, offset = 0, loop = false, duration, base, fade }) {
  if (!buffer || !buffer.length || duration <= 0) return;
  const source = context.createBufferSource(), gain = context.createGain();
  source.buffer = buffer; source.loop = loop; source.connect(gain); gain.connect(destination);
  const value = clamp(finite(volume, 1), 0, 2), when = base + start;
  const length = loop ? duration : Math.min(duration, Math.max(0, buffer.duration - offset));
  if (length <= 0) return;
  const ramp = Math.min(fade ? .2 : .012, length / 4);
  gain.gain.setValueAtTime(0, when);
  gain.gain.linearRampToValueAtTime(value, when + ramp);
  gain.gain.setValueAtTime(value, when + Math.max(ramp, length - ramp));
  gain.gain.linearRampToValueAtTime(0, when + length);
  source.start(when, offset, length);
  sources.push({ source, gain });
}

/**
 * Record locally in real time. Keep the tab visible and the device awake.
 * Cancellation always releases audio nodes, canvas tracks, and video playback.
 */
export async function exportVideo({ scenes = [], settings = {}, music = null, audioTracks = [], onProgress = () => {}, signal } = {}) {
  if (activeExport) throw new Error('Another video export is running. Wait for it or cancel it first.');
  if (!scenes.length) throw new Error('Add at least one storyboard scene before exporting.');
  throwIfAborted(signal);
  const capability = getExportCapabilities(settings);
  if (!capability.supported) throw new Error(capability.reason);
  const fitted = fitAudioDurations(scenes, audioTracks);
  const warnings = [...fitted.warnings];
  if (settings.fitNarration === false && warnings.length) throw new Error('A narration is longer than its scene. Extend the scene duration or use fitAudioDurations before exporting.');
  const project = fitted.scenes;
  const duration = totalDuration(project);
  if (duration > 600) throw new Error('This browser export is limited to 10 minutes. Split the project into smaller videos.');
  const config = exportSettings(settings);
  if (config.width !== finite(settings.width, 960) || config.height !== finite(settings.height, 540) || config.fps !== finite(settings.fps, 24)) {
    warnings.push(`Export size/rate adjusted to ${config.width}×${config.height}, ${config.fps} fps to bound device load.`);
  }
  const hasAudio = Boolean(music?.buffer || audioTracks.some(track => track.buffer));
  if (hasAudio && !capability.audio) throw new Error('Web Audio mixing is unavailable. Use a current browser or export without audio.');
  const unknownTracks = audioTracks.filter(track => !project.some(scene => scene.id === track.sceneId));
  if (unknownTracks.length) warnings.push(`${unknownTracks.length} audio track(s) referenced a deleted scene and were omitted.`);
  activeExport = true;
  let canvas, stream, recorder, context, destination, wakeLock, frameTimer, stopped = false, recorderError = null;
  const chunks = [], sources = [], videoStates = new Map();
  let stopPromise, finishStop, failStop, rejectRender;
  const stopRecording = () => { if (recorder && recorder.state !== 'inactive') recorder.stop(); };
  const cancel = () => { stopped = true; clearTimeout(frameTimer); stopRecording(); rejectRender?.(abortError()); };
  try {
    canvas = document.createElement('canvas'); canvas.width = config.width; canvas.height = config.height;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) throw new Error('A 2D canvas cannot be created. Close other tabs and retry.');
    for (const scene of project) {
      throwIfAborted(signal);
      if (scene.mediaType === 'video') {
        if (!scene.video) throw new Error(`Scene ${scene.id} has no loaded video.`);
        if (!videoStates.has(scene.video)) videoStates.set(scene.video, { time: scene.video.currentTime, paused: scene.video.paused, muted: scene.video.muted, rate: scene.video.playbackRate });
        scene.video.pause(); scene.video.muted = true; scene.video.playbackRate = 1; scene.video.playsInline = true;
        if (scene.video.readyState < 1) await waitEvent(scene.video, 'loadedmetadata', { signal });
        if (Math.max(0, finite(scene.trimStart)) >= scene.video.duration) throw new Error(`Scene ${scene.id}: trim start is outside the video. Reset the trim range.`);
        if (scene.trimEnd != null && finite(scene.trimEnd) <= finite(scene.trimStart)) throw new Error(`Scene ${scene.id}: trim end must be after trim start.`);
        const available = (scene.trimEnd == null ? scene.video.duration : Math.min(scene.video.duration, finite(scene.trimEnd))) - Math.max(0, finite(scene.trimStart));
        if (durationOf(scene) > available + .05) warnings.push(`Scene ${scene.id}: the last video frame is held after the trimmed clip ends.`);
      } else {
        if (!scene.image) throw new Error(`Scene ${scene.id} has no loaded image.`);
        if (typeof scene.image.decode === 'function' && !scene.image.complete) await scene.image.decode();
        if (!sourceDimensions(scene.image).width) throw new Error(`Scene ${scene.id} image could not be decoded.`);
      }
    }
    await prepareVideoFrames(project, 0, signal);
    renderFrame(ctx, { scenes: project, time: 0, width: config.width, height: config.height, settings: config });
    // Detect CORS-tainted canvas before recording, rather than returning an empty video.
    try { ctx.getImageData(0, 0, 1, 1); } catch { throw new Error('A remote image/video blocked canvas export. Import the file from your device, or use media served with CORS permission.'); }
    stream = canvas.captureStream(config.fps);
    if (hasAudio) {
      const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
      context = new AudioContextClass(); destination = context.createMediaStreamDestination();
      await context.resume();
      if (context.state !== 'running') throw new Error('Audio could not start. Click Export directly, enable sound permission, and keep the tab active.');
      // Keep the stream live during gaps and after the final narration. A zero
      // signal is real PCM silence, not speechSynthesis audio capture.
      const silence = context.createConstantSource(); silence.offset.value = 0;
      silence.connect(destination); silence.start(); sources.push({ source: silence });
      destination.stream.getAudioTracks().forEach(track => stream.addTrack(track));
    }
    recorder = new MediaRecorder(stream, { mimeType: capability.mime,
      videoBitsPerSecond: Math.round(config.width * config.height * config.fps * .14), audioBitsPerSecond: 128000 });
    stopPromise = new Promise((resolve, reject) => { finishStop = resolve; failStop = reject; });
    // The recording error may arrive before the render loop finishes. Attach a
    // rejection handler now; the same rejection is awaited below.
    stopPromise.catch(() => {});
    recorder.addEventListener('dataavailable', event => { if (event.data.size) chunks.push(event.data); });
    recorder.addEventListener('stop', () => finishStop());
    recorder.addEventListener('error', event => {
      recorderError = event.error || new Error('The browser video encoder failed. Try 640×360 at 15 fps.');
      failStop(recorderError); stopRecording();
    });
    signal?.addEventListener('abort', cancel, { once: true });
    if (globalThis.navigator?.wakeLock?.request) {
      try { wakeLock = await navigator.wakeLock.request('screen'); } catch { /* optional */ }
    }
    recorder.start(1000);
    // Start producing both audio and frames immediately. Some encoders dispatch
    // "start" only when every track has supplied data; awaiting that event
    // before scheduling audio would deadlock a freshly-created audio graph.
    renderFrame(ctx, { scenes: project, time: 0, width: config.width, height: config.height, settings: config });
    stream.getVideoTracks()[0]?.requestFrame?.();
    const baseAudio = context?.currentTime || 0, basePerformance = performance.now();
    const clock = () => context ? context.currentTime - baseAudio : (performance.now() - basePerformance) / 1000;
    if (music?.buffer) addAudioSource(context, destination, sources, { buffer: music.buffer,
      volume: music.volume ?? config.musicVolume ?? .2, start: Math.max(0, finite(music.start)),
      loop: music.loop !== false, duration: duration - Math.max(0, finite(music.start)), base: baseAudio, fade: config.fadeAudio !== false });
    let sceneStart = 0;
    for (const scene of project) {
      for (const track of audioTracks.filter(item => item.sceneId === scene.id && item.buffer)) {
        const offset = Math.max(0, finite(track.offset));
        addAudioSource(context, destination, sources, { buffer: track.buffer,
          volume: finite(track.volume, 1) * finite(config.narrationVolume, 1), start: sceneStart + offset,
          // Narration uses only a 12 ms anti-click ramp, so a music-style fade
          // does not attenuate the final spoken word.
          duration: durationOf(scene) - offset, base: baseAudio, fade: false });
      }
      sceneStart += durationOf(scene);
    }
    const activeVideos = new Set();
    let slowFrames = 0, frameCount = 0;
    const syncVideo = async time => {
      const pos = locateScene(project, time), needed = new Set();
      if (!pos) return;
      if (pos.scene.mediaType === 'video' && pos.scene.video) {
        const video = pos.scene.video, target = mediaTarget(pos.scene, pos.localTime);
        needed.add(video);
        const end = pos.scene.trimEnd == null ? video.duration : Math.min(video.duration, finite(pos.scene.trimEnd, video.duration));
        if (!activeVideos.has(video) || Math.abs(video.currentTime - target) > .25) await seekVideo(video, target, signal);
        if (target >= end - .06 || pos.localTime >= end - finite(pos.scene.trimStart)) video.pause();
        else if (video.paused) {
          try { await video.play(); } catch { throw new Error('The imported video cannot play during export. Tap Export again, or use a supported MP4 clip.'); }
        }
      }
      for (const video of activeVideos) if (!needed.has(video)) video.pause();
      activeVideos.clear(); needed.forEach(video => activeVideos.add(video));
      if (pos.index > 0 && pos.scene.transition !== 'cut' && pos.localTime < finite(pos.scene.transitionDuration, .5)) {
        const previous = project[pos.index - 1];
        if (previous.mediaType === 'video' && previous.video && previous.video !== pos.scene.video) {
          previous.video.pause();
          await seekVideo(previous.video, mediaTarget(previous, durationOf(previous)), signal);
        }
      }
    };
    await new Promise((resolve, reject) => {
      rejectRender = reject;
      const tick = async () => {
        if (recorderError) { reject(recorderError); return; }
        if (stopped || signal?.aborted) { reject(abortError()); return; }
        try {
          if (document.hidden) throw new Error('Export paused because this tab became hidden. Keep this tab visible, then export again.');
          const before = performance.now();
          let time = Math.min(clock(), duration);
          await syncVideo(time);
          time = Math.min(clock(), duration);
          renderFrame(ctx, { scenes: project, time, width: config.width, height: config.height, settings: config });
          onProgress(clamp(time / duration, 0, 1), { elapsed: time, duration, realTime: true });
          frameCount++;
          const elapsed = performance.now() - before;
          if (elapsed > 1000 / config.fps * 1.5) slowFrames++;
          if (time >= duration) { stopRecording(); resolve(); }
          else frameTimer = setTimeout(tick, Math.max(0, 1000 / config.fps - elapsed));
        } catch (error) { stopRecording(); reject(error); }
      };
      tick();
    });
    await stopPromise;
    throwIfAborted(signal);
    if (!chunks.length) throw new Error('The browser returned no recorded video. Try a smaller output size in a current desktop browser.');
    if (slowFrames > Math.max(3, frameCount * .1)) warnings.push('This device could not draw every target frame in real time. Try a lower resolution or frame rate for smoother output.');
    const mime = recorder.mimeType || capability.mime;
    if (mime.startsWith('video/mp4') && !/avc1|h264/i.test(mime)) warnings.push(`The browser selected ${mime}. This MP4 may not play on older devices; use an H.264-capable browser for wider MP4 compatibility.`);
    let blob = new Blob(chunks, { type: mime });
    if (mime.startsWith('video/webm')) {
      const repaired = await fixWebMDuration(blob, duration);
      if (repaired === blob) warnings.push('This browser did not expose a safely patchable WebM duration header; some players may display an unknown duration until playback.');
      blob = repaired;
    }
    onProgress(1, { elapsed: duration, duration, realTime: true });
    return { blob, extension: mime.startsWith('video/mp4') ? 'mp4' : 'webm', mime,
      width: config.width, height: config.height, duration, warnings };
  } finally {
    stopped = true; clearTimeout(frameTimer); signal?.removeEventListener('abort', cancel);
    stopRecording();
    for (const { source, gain } of sources) { try { source.stop(); } catch { /* ended */ } source.disconnect(); gain?.disconnect(); }
    stream?.getTracks().forEach(track => track.stop());
    destination?.disconnect();
    if (context && context.state !== 'closed') await context.close().catch(() => {});
    for (const [video, state] of videoStates) {
      video.pause(); video.muted = state.muted; video.playbackRate = state.rate;
      try { video.currentTime = state.time; if (!state.paused) await video.play(); } catch { /* media may have been removed */ }
    }
    await wakeLock?.release().catch(() => {});
    activeExport = false;
  }
}

function ebmlElement(bytes, offset) {
  if (offset >= bytes.length) return null;
  const vint = (at, id = false) => {
    let length = 1, mask = 128;
    while (length <= 8 && !(bytes[at] & mask)) { length++; mask >>= 1; }
    if (length > (id ? 4 : 8) || at + length > bytes.length) return null;
    let value = BigInt(id ? bytes[at] : bytes[at] & (mask - 1));
    for (let i = 1; i < length; i++) value = value * 256n + BigInt(bytes[at + i]);
    return { length, value, unknown: !id && value === (1n << BigInt(7 * length)) - 1n };
  };
  const id = vint(offset, true);
  if (!id) return null;
  const size = vint(offset + id.length);
  if (!size) return null;
  const dataOffset = offset + id.length + size.length;
  const dataLength = size.unknown ? null : Number(size.value);
  return { id: Number(id.value), offset, idLength: id.length, sizeLength: size.length, dataOffset, dataLength,
    end: dataLength == null ? null : dataOffset + dataLength };
}

function ebmlSize(value) {
  const number = BigInt(value);
  let length = 1;
  while (number >= (1n << BigInt(length * 7)) - 1n) length++;
  let encoded = number | (1n << BigInt(length * 7));
  const bytes = new Uint8Array(length);
  for (let i = length - 1; i >= 0; i--) { bytes[i] = Number(encoded & 255n); encoded >>= 8n; }
  return bytes;
}

/**
 * MediaRecorder often omits WebM Info/Duration. Add it to an unindexed,
 * unknown-sized Segment using EBML (RFC 8794) and Matroska Duration (0x4489).
 * Only the small header is copied; encoded media Blob slices remain intact.
 * Indexed or otherwise unsupported layouts are returned unchanged, never
 * rewritten speculatively because stored byte offsets could become invalid.
 */
export async function fixWebMDuration(blob, duration) {
  if (!(duration > 0) || !blob?.slice) return blob;
  const bytes = new Uint8Array(await blob.slice(0, 65536).arrayBuffer());
  let header = ebmlElement(bytes, 0);
  if (header?.id !== 0x1a45dfa3 || header.end == null) return blob;
  const segment = ebmlElement(bytes, header.end);
  if (segment?.id !== 0x18538067 || segment.dataLength != null) return blob;
  let info = null, offset = segment.dataOffset;
  while (offset < bytes.length) {
    const element = ebmlElement(bytes, offset);
    if (!element || element.id === 0x114d9b74 || element.id === 0x1c53bb6b) return blob; // SeekHead / Cues
    if (element.id === 0x1f43b675) break; // first Cluster
    if (element.end == null || element.end > bytes.length) return blob;
    if (element.id === 0x1549a966) info = element;
    offset = element.end;
  }
  if (!info) return blob;
  let scale = 1000000, existing = null;
  for (offset = info.dataOffset; offset < info.end;) {
    const element = ebmlElement(bytes, offset);
    if (!element || element.end == null || element.end > info.end) return blob;
    if (element.id === 0x2ad7b1) {
      scale = 0;
      for (let i = element.dataOffset; i < element.end; i++) scale = scale * 256 + bytes[i];
    }
    if (element.id === 0x4489) existing = element;
    offset = element.end;
  }
  if (!(scale > 0)) return blob;
  const ticks = duration * 1e9 / scale;
  if (existing) {
    if (![4, 8].includes(existing.dataLength)) return blob;
    const replacement = bytes.slice(0, existing.end);
    const view = new DataView(replacement.buffer);
    if (existing.dataLength === 4) view.setFloat32(existing.dataOffset, ticks, false);
    else view.setFloat64(existing.dataOffset, ticks, false);
    return new Blob([replacement, blob.slice(existing.end)], { type: blob.type });
  }
  const durationElement = new Uint8Array(11);
  durationElement.set([0x44, 0x89, 0x88]);
  new DataView(durationElement.buffer).setFloat64(3, ticks, false);
  const newInfo = new Blob([bytes.slice(info.offset, info.offset + info.idLength), ebmlSize(info.dataLength + 11),
    bytes.slice(info.dataOffset, info.end), durationElement]);
  return new Blob([blob.slice(0, info.offset), newInfo, blob.slice(info.end)], { type: blob.type });
}

/** PCM16 WAV encoder: AudioBuffer, Float32Array, or {channels:[Float32Array]}. */
export function wavBlob({ audio, sampleRate } = {}) {
  let channels;
  if (audio?.getChannelData) channels = Array.from({ length: audio.numberOfChannels }, (_, i) => audio.getChannelData(i));
  else if (audio?.channels) channels = audio.channels;
  else if (audio instanceof Float32Array || Array.isArray(audio)) channels = [audio];
  else throw new TypeError('WAV audio must contain PCM sample data.');
  const rate = Math.round(finite(sampleRate, audio?.sampleRate || 24000));
  const count = channels.length, length = channels[0]?.length || 0;
  if (!count || count > 8 || rate < 8000 || rate > 192000 || channels.some(channel => channel.length !== length)) throw new RangeError('Invalid WAV channels or sample rate.');
  const bytes = length * count * 2;
  if (bytes > 0xffffffff - 36) throw new RangeError('WAV is too large for the standard RIFF container.');
  const buffer = new ArrayBuffer(44 + bytes), view = new DataView(buffer);
  const text = (offset, value) => Array.from(value).forEach((ch, i) => view.setUint8(offset + i, ch.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + bytes, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, count, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * count * 2, true);
  view.setUint16(32, count * 2, true); view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, bytes, true);
  let offset = 44;
  for (let i = 0; i < length; i++) for (const channel of channels) {
    const value = clamp(finite(channel[i]), -1, 1);
    view.setInt16(offset, Math.round(value < 0 ? value * 32768 : value * 32767), true); offset += 2;
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

function timestamp(seconds, format) {
  const ms = Math.max(0, Math.round(seconds * 1000));
  const hh = Math.floor(ms / 3600000), mm = Math.floor(ms / 60000) % 60, ss = Math.floor(ms / 1000) % 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}${format === 'vtt' ? '.' : ','}${String(ms % 1000).padStart(3, '0')}`;
}

export function subtitles(scenes = [], format = 'srt') {
  if (!['srt', 'vtt'].includes(format)) throw new TypeError('Subtitle format must be srt or vtt.');
  let start = 0, number = 0;
  const blocks = [];
  for (const scene of scenes) {
    const end = start + durationOf(scene);
    const text = String(scene.subtitle || scene.narration || '').replace(/\r/g, '').trim();
    if (text) blocks.push(`${++number}\n${timestamp(start, format)} --> ${timestamp(end, format)}\n${text}`);
    start = end;
  }
  return (format === 'vtt' ? 'WEBVTT\n\n' : '') + blocks.join('\n\n') + '\n';
}
