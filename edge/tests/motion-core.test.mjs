import test from 'node:test';
import assert from 'node:assert/strict';
import { parsePrompt, cameraTransform, mapCameraPoint, renderFrame } from '../motion-core.mjs';

function image(w = 32, h = 24) {
  const data = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const p = (y * w + x) * 4; data[p] = x * 7; data[p + 1] = y * 9; data[p + 2] = (x + y) * 4; data[p + 3] = 255;
  }
  return { width: w, height: h, data };
}
const person = { label: 'person', bbox: [0.2, 0.15, 0.5, 0.7], normalized: true };

test('camera cover crop preserves the requested aspect and stays inside the image', () => {
  for (const [w, h] of [[1280, 720], [720, 1280], [500, 500]]) {
    const c = cameraTransform(1200, 800, w, h, { zoomStart: 1, zoomEnd: 1.2, panX: 0.9, panY: -0.5 }, 0.7);
    assert.ok(Math.abs(c.width / c.height - w / h) < 1e-10);
    assert.ok(c.x >= 0 && c.y >= 0 && c.x + c.width <= 1200 + 1e-9 && c.y + c.height <= 800 + 1e-9);
  }
});

test('no-motion equal-size frame preserves the original pixels exactly', () => {
  const src = image(); const out = renderFrame(src, parsePrompt(''), 0.6, 5);
  assert.deepEqual(out.data, src.data); assert.notEqual(out.data, src.data);
});

test('parse Chinese camera, object pulse, and snow into bounded rules', () => {
  const p = parsePrompt('人物呼吸，鏡頭拉近，飄雪', [person]);
  assert.equal(p.camera.zoomEnd, 1.15);
  assert.ok(p.effects.some(e => e.kind === 'pulse'));
  assert.ok(p.effects.some(e => e.kind === 'snow'));
  assert.equal(p.engine, 'cpu-geometric-rules');
});

test('Latin matching avoids keyword substrings in unrelated words', () => {
  const p = parsePrompt('brain cartoon', [{ label: 'car', bbox: [0, 0, 1, 1] }]);
  assert.equal(p.effects.length, 0); assert.ok(p.unhandled.length);
});

test('European and Asian action vocabulary maps to explicit simple effects', () => {
  for (const prompt of ['person breathe', 'personne respirer', 'mensch atmen', 'persona respirar', '人物呼吸', '사람 호흡']) {
    assert.ok(parsePrompt(prompt, [person]).effects.some(e => e.kind === 'pulse'), prompt);
  }
});

test('unsupported articulated motion is not claimed to be generated', () => {
  const p = parsePrompt('make person walk and bird fly', [person, { label: 'bird', bbox: [0.1, 0.1, 0.2, 0.2] }]);
  assert.ok(p.unhandled.includes('walk')); assert.ok(p.unhandled.includes('fly'));
  assert.equal(p.effects.length, 0);
});

test('water requires a manually labeled region instead of fabricated detector segmentation', () => {
  const detector = parsePrompt('water ripple', [{ label: 'water', bbox: [0, 0.5, 1, 0.5] }]);
  assert.equal(detector.effects.length, 0); assert.ok(detector.warnings.some(w => w.includes('manual')));
  const manual = parsePrompt('water ripple', [], { regions: [{ type: 'water', x: 0, y: 0.5, width: 1, height: 0.5 }] });
  assert.equal(manual.effects[0].kind, 'wave'); assert.equal(manual.effects[0].region.source, 'manual');
});

test('masked region motion leaves every pixel outside its selected region unchanged', () => {
  const src = image(40, 40), region = { type: 'tree', x: 0.25, y: 0.25, width: 0.5, height: 0.5 };
  const p = parsePrompt('tree sway', [], { regions: [region] });
  const out = renderFrame(src, p, 1, 4);
  let changedInside = 0;
  for (let y = 0; y < 40; y++) for (let x = 0; x < 40; x++) {
    const k = (y * 40 + x) * 4;
    if (x < 10 || x > 30 || y < 10 || y > 30) assert.deepEqual(out.data.slice(k, k + 4), src.data.slice(k, k + 4));
    else if (out.data[k] !== src.data[k]) changedInside++;
  }
  assert.ok(changedInside > 0);
});

test('polygon mask excludes pixels outside the selected polygon', () => {
  const src = image(40, 40);
  const p = parsePrompt('tree sway', [], { regions: [{ type: 'tree', x: 0.1, y: 0.1, width: 0.8, height: 0.8, polygon: [[0.1, 0.1], [0.9, 0.1], [0.1, 0.9]] }] });
  const out = renderFrame(src, p, 1, 4);
  const k = (32 * 40 + 32) * 4;
  assert.deepEqual(out.data.slice(k, k + 4), src.data.slice(k, k + 4));
});

test('duration and extreme time are clamped; zero duration produces a valid first frame', () => {
  const src = image(); const p = parsePrompt('zoom in');
  assert.deepEqual(renderFrame(src, p, -5, 3).data, renderFrame(src, p, 0, 3).data);
  assert.deepEqual(renderFrame(src, p, 100, 3).data, renderFrame(src, p, 3, 3).data);
  assert.deepEqual(renderFrame(src, p, 1, 0).data, renderFrame(src, p, 0, 3).data);
});

test('particles have deterministic seeds and valid bounded RGBA', () => {
  const src = image(); const p = parsePrompt('snow rain', [], { seed: 42 });
  const a = renderFrame(src, p, 1.2, 4), b = renderFrame(src, p, 1.2, 4);
  assert.deepEqual(a.data, b.data); assert.ok(a.data.every(x => x >= 0 && x <= 255));
  assert.notDeepEqual(a.data, renderFrame(src, { ...p, seed: 43 }, 1.2, 4).data);
});

test('pixel coordinates normalize with supplied dimensions and region count is bounded', () => {
  const detections = Array.from({ length: 9 }, (_, i) => ({ label: 'person', bbox: [i * 2, 5, 10, 20], normalized: false }));
  const p = parsePrompt('people breathe', detections, { sourceWidth: 100, sourceHeight: 100, maxRegions: 3 });
  assert.equal(p.effects.length, 3); assert.equal(p.effects[0].region.height, 0.2); assert.ok(p.warnings.some(x => x.includes('budget')));
});

test('render supports a reusable buffer and rejects aliasing or unbounded output allocation', () => {
  const src = image(); const data = new Uint8ClampedArray(16 * 9 * 4);
  const out = renderFrame(src, {}, 0, 3, { width: 16, height: 9, data });
  assert.equal(out.data, data);
  assert.throws(() => renderFrame(src, {}, 0, 3, { data: src.data }), TypeError);
  assert.throws(() => renderFrame(src, {}, 0, 3, { width: 50000, height: 50000 }), RangeError);
});

test('mapped canvas coordinates agree with cover crop coordinates', () => {
  const point = mapCameraPoint(4, 3, { width: 100, height: 100 }, {}, 0, 5, { width: 10, height: 10 });
  assert.deepEqual(point, { x: 44.5, y: 34.5 });
});

test('pan-only prompt produces actual movement at matching source and output aspect', () => {
  const src = image(), plan = parsePrompt('pan right');
  const first = renderFrame(src, plan, 0, 5), last = renderFrame(src, plan, 5, 5);
  assert.notDeepEqual(first.data, last.data);
  assert.ok(plan.camera.zoomStart > 1);
});

test('default simple animation depends on supported object type and avoids invented traits for unknown labels', () => {
  const plan = parsePrompt('animate', [person, { label: 'car', bbox: [0, 0, 0.2, 0.2] }, { label: 'bottle', bbox: [0, 0, 0.1, 0.1] }]);
  assert.deepEqual(plan.effects.map(e => [e.region.type, e.kind]), [['person', 'pulse'], ['car', 'bob']]);
});

test('common English water plurals combine camera, manual ripples and particles', () => {
  for (const prompt of ['zoom in, water ripples, snow', 'zoom in, waves and snow', 'zoom in, rippling water, snow']) {
    const plan = parsePrompt(prompt, [], { regions: [{ type: 'water', x: 0, y: 0.5, width: 1, height: 0.5 }] });
    assert.ok(plan.effects.some(e => e.kind === 'wave'), prompt);
    assert.ok(plan.effects.some(e => e.kind === 'snow'), prompt);
    assert.equal(plan.camera.zoomEnd, 1.15);
  }
});

test('English plural target names and common action forms retain selected target filtering', () => {
  const objects = [person, { label: 'cat', bbox: [0, 0, 0.1, 0.1] }, { label: 'boat', bbox: [0, 0, 0.1, 0.1] }];
  assert.deepEqual(parsePrompt('cats breathing', objects).effects.map(e => e.region.type), ['cat']);
  assert.deepEqual(parsePrompt('boats floating', objects).effects.map(e => e.region.type), ['boat']);
  const manual = [{ type: 'tree', x: 0, y: 0, width: 0.2, height: 0.5 }, { type: 'cloud', x: 0.6, y: 0, width: 0.3, height: 0.2 }];
  assert.deepEqual(parsePrompt('trees swaying', [], { regions: manual }).effects.map(e => [e.region.type, e.kind]), [['tree', 'sway']]);
  assert.deepEqual(parsePrompt('clouds floating', [], { regions: manual }).effects.map(e => [e.region.type, e.kind]), [['cloud', 'bob']]);
});
