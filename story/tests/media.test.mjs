import test from 'node:test';
import assert from 'node:assert/strict';
import { totalDuration, locateScene, cropRect, fitAudioDurations, subtitles, wavBlob, getExportCapabilities, fixWebMDuration } from '../media.mjs';

test('storyboard time mapping keeps cut boundaries and clamps end positions', () => {
  const scenes = [{ id: 'a', duration: 2 }, { id: 'b', duration: 3.5 }, { id: 'c', duration: 1 }];
  assert.equal(totalDuration(scenes), 6.5);
  assert.equal(locateScene(scenes, -8).index, 0);
  assert.equal(locateScene(scenes, 2).scene.id, 'b');
  assert.equal(locateScene(scenes, 2.75).localTime, .75);
  assert.equal(locateScene(scenes, 5.5).scene.id, 'c');
  assert.equal(locateScene(scenes, 100).scene.id, 'c');
  assert.ok(locateScene(scenes, 100).localTime <= 1);
  assert.equal(locateScene([], 0), null);
});

test('cover crops never stretch an image or leave its pixel bounds during camera motion', () => {
  for (const [sw, sh, tw, th] of [[1600, 900, 960, 540], [600, 1200, 1280, 720], [2200, 700, 540, 960]]) {
    for (const motion of ['still', 'zoom-in', 'zoom-out', 'pan-left', 'pan-right']) {
      for (const progress of [0, .5, 1]) {
        const r = cropRect(sw, sh, tw, th, progress, motion);
        assert.ok(Math.abs(r.width / r.height - tw / th) < 1e-10);
        assert.ok(r.x >= 0 && r.y >= 0);
        assert.ok(r.x + r.width <= sw + 1e-8);
        assert.ok(r.y + r.height <= sh + 1e-8);
      }
    }
  }
  assert.ok(cropRect(1000, 1000, 500, 500, 1, 'zoom-in').width < cropRect(1000, 1000, 500, 500, 0, 'zoom-in').width);
  assert.throws(() => cropRect(0, 100, 100, 100), RangeError);
});

test('audio fitting preserves complete narration with explicit warnings without mutating inputs', () => {
  const scenes = [{ id: 'one', duration: 2 }, { id: 'two', duration: 4 }];
  const result = fitAudioDurations(scenes, [{ sceneId: 'one', buffer: { duration: 4.25 }, offset: .75 }]);
  assert.equal(result.scenes[0].duration, 5);
  assert.equal(result.scenes[1].duration, 4);
  assert.equal(scenes[0].duration, 2);
  assert.equal(result.warnings.length, 1);
  assert.match(result.warnings[0], /preserve the complete narration/);
});

test('SRT and VTT use actual cumulative scene duration, including scenes without captions', () => {
  const scenes = [{ duration: 1.234, subtitle: '第一幕' }, { duration: .5 }, { duration: 2, narration: 'مرحبا\nHello' }];
  assert.equal(subtitles(scenes), '1\n00:00:00,000 --> 00:00:01,234\n第一幕\n\n2\n00:00:01,734 --> 00:00:03,734\nمرحبا\nHello\n');
  assert.match(subtitles(scenes, 'vtt'), /^WEBVTT\n\n1\n00:00:00\.000 --> 00:00:01\.234/);
  assert.throws(() => subtitles(scenes, 'csv'), TypeError);
});

test('WAV headers and PCM samples support real mono and stereo audio', async () => {
  const audio = { channels: [new Float32Array([-1, 0, 1]), new Float32Array([.5, -.5, 0])] };
  const blob = wavBlob({ audio, sampleRate: 16000 });
  assert.equal(blob.type, 'audio/wav');
  const buffer = await blob.arrayBuffer(), view = new DataView(buffer);
  assert.equal(new TextDecoder().decode(buffer.slice(0, 4)), 'RIFF');
  assert.equal(new TextDecoder().decode(buffer.slice(8, 12)), 'WAVE');
  assert.equal(view.getUint16(22, true), 2);
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint32(40, true), 12);
  assert.equal(view.getInt16(44, true), -32768);
  assert.equal(view.getInt16(46, true), 16384);
  assert.equal(view.getInt16(52, true), 32767);
  assert.throws(() => wavBlob({ audio: { channels: [[1], [1, 2]] }, sampleRate: 24000 }), RangeError);
});

test('Node reports browser export unavailable rather than claiming unsupported encoding works', () => {
  const capability = getExportCapabilities();
  assert.equal(capability.supported, false);
  assert.match(capability.reason, /cannot record a canvas video/);
});

test('WebM duration repair adds a finite duration without altering encoded cluster bytes', async () => {
  // Minimal EBML header + unknown-sized Segment + Info TimestampScale + Cluster.
  const original = new Uint8Array([0x1a,0x45,0xdf,0xa3,0x80,0x18,0x53,0x80,0x67,0xff,
    0x15,0x49,0xa9,0x66,0x87,0x2a,0xd7,0xb1,0x83,0x0f,0x42,0x40,
    0x1f,0x43,0xb6,0x75,0x83,0x11,0x22,0x33]);
  const blob = new Blob([original], { type: 'video/webm' });
  const repaired = await fixWebMDuration(blob, 3.25);
  const bytes = new Uint8Array(await repaired.arrayBuffer());
  assert.equal(bytes.length, original.length + 11);
  const view = new DataView(bytes.buffer);
  assert.deepEqual(Array.from(bytes.slice(22, 25)), [0x44, 0x89, 0x88]);
  assert.equal(view.getFloat64(25, false), 3250);
  assert.deepEqual(Array.from(bytes.slice(-8)), Array.from(original.slice(-8)));
  const invalid = new Blob(['not webm']);
  assert.equal(await fixWebMDuration(invalid, 3), invalid);
});
