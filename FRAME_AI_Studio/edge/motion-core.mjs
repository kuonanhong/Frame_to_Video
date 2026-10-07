/*
 * FRAME CPU motion core. MIT, no network calls and no learned generative model.
 * Inverse mapping changes existing pixels only. Rectangular/polygon selections
 * are approximate effect masks, not segmentation, scene reconstruction or pose.
 * All region coordinates in a returned plan are normalized to the source image.
 */

const TAU = Math.PI * 2;
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const finite = (x, fallback = 0) => Number.isFinite(Number(x)) ? Number(x) : fallback;
const smooth = x => { x = clamp(x, 0, 1); return x * x * (3 - 2 * x); };

const WORDS = {
  zoomIn: ['拉近', '推近', '放大', 'zoom in', 'push in', 'acercar', 'acercamiento', 'rapprocher', 'rapprochement', 'hineinzoomen', 'näher', 'ズームイン', '近づ', '확대', '가까이'],
  zoomOut: ['拉遠', '拉远', '縮小', '缩小', 'zoom out', 'pull out', 'alejar', 'éloigner', 'eloigner', 'herauszoomen', 'ズームアウト', '遠ざ', '축소', '멀리'],
  left: ['向左', '左移', 'pan left', 'move left', 'vers la gauche', 'nach links', 'izquierda', '左へ', '왼쪽'],
  right: ['向右', '右移', 'pan right', 'move right', 'vers la droite', 'nach rechts', 'derecha', '右へ', '오른쪽'],
  up: ['向上', '上移', 'pan up', 'move up', 'vers le haut', 'nach oben', 'arriba', '上へ', '위로'],
  down: ['向下', '下移', 'pan down', 'move down', 'vers le bas', 'nach unten', 'abajo', '下へ', '아래로'],
  sway: ['搖擺', '摇摆', '搖動', '摇动', '晃動', '晃动', 'sway', 'sways', 'swaying', 'swing', 'swings', 'swinging', 'wobble', 'wobbles', 'wobbling', 'balancer', 'balancement', 'schwanken', 'schwingen', 'mecer', 'bambolear', '揺れ', '揺ら', '흔들'],
  bob: ['漂浮', '浮動', '浮动', '上下浮', '起伏', 'bob', 'bobs', 'bobbing', 'float', 'floats', 'floating', 'flotter', 'schweben', 'flotar', '浮か', '漂う', '뜨게'],
  pulse: ['呼吸', '脈動', '脉动', 'pulse', 'pulses', 'pulsing', 'breathe', 'breathes', 'breathing', 'pulsieren', 'respirer', 'respirar', 'atmen', '맥동', '호흡'],
  water: ['波紋', '波纹', '水波', '波浪', '水面', 'ripple', 'ripples', 'rippling', 'wave', 'waves', 'water waves', 'water ripple', 'water ripples', 'vagues', 'ondulation', 'wasser', 'wellen', 'olas', 'agua', '水の', '波を', '물결', '물의'],
  rain: ['下雨', '雨滴', '降雨', 'raining', 'rain', 'pluie', 'regen', 'lluvia', '雨', '비가'],
  snow: ['下雪', '雪花', '飄雪', '飘雪', 'snow', 'neige', 'schnee', 'nieve', '雪', '눈이'],
  animate: ['動起來', '动起来', '動畫', '动画', 'animate', 'animation', 'animer', 'animieren', 'animar', '動か', '움직'],
  unsupported: ['走路', '奔跑', '跑步', '飛翔', '飞翔', '飛起', '飞起', '說話', '说话', '張嘴', '张嘴', '轉身', '转身', '變成', '变成', '新增', '移除', 'walking', 'walk', 'running', 'run', 'flying', 'fly', 'talk', 'speaking', 'speak', 'turn around', 'generate', 'remove', 'add a', 'marche', 'courir', 'voler', 'parler', 'laufen', 'fliegen', 'sprechen', 'caminar', 'correr', 'volar', 'hablar', '歩く', '走る', '飛ぶ', '話す', '걷', '달리', '날아', '말하'],
};

const LABELS = {
  person: ['person', 'persons', 'people', 'human', 'humans', '人物', '人像', '人', 'personne', 'mensch', 'persona', '人物', '사람'],
  bird: ['bird', 'birds', '鳥', '鸟', 'oiseau', 'vogel', 'pájaro', 'pajaro', '鳥', '새'],
  cat: ['cat', 'cats', '貓', '猫', 'chat', 'katze', 'gato', '猫', '고양이'],
  dog: ['dog', 'dogs', '狗', '犬', 'chien', 'hund', 'perro', '犬', '강아지', '개'],
  car: ['car', 'cars', '汽車', '汽车', '車輛', '车辆', 'voiture', 'auto', 'coche', '車', '자동차'],
  truck: ['truck', 'trucks', '卡車', '卡车', 'camion', 'lastwagen', 'camión', 'トラック', '트럭'],
  boat: ['boat', 'boats', '船', 'bateau', 'boot', 'barco', '船', '배'],
  water: ['water', '水面', '水域', 'wasser', 'eau', 'agua', '水', '물'],
  tree: ['tree', 'trees', '樹', '树', 'arbre', 'baum', 'árbol', 'arbol', '木', '나무'],
  cloud: ['cloud', 'clouds', '雲', '云', 'nuage', 'wolke', 'nube', '雲', '구름'],
};
const MANUAL_ONLY = new Set(['water', 'tree', 'cloud']);

function contains(text, word) {
  // Latin whole-word boundaries prevent e.g. "car" matching "cartoon" and
  // "rain" matching "brain". Chinese/Japanese/Korean use substring matching.
  if (/^[a-zà-ž0-9 ]+$/iu.test(word)) {
    const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`(^|[^\\p{L}\\p{N}])${escaped}($|[^\\p{L}\\p{N}])`, 'iu').test(text);
  }
  return text.includes(word);
}

function matches(text, list) { return list.filter(word => contains(text, word)); }

function labelType(value) {
  const s = String(value || '').toLowerCase();
  for (const [kind, words] of Object.entries(LABELS)) if (words.some(w => s === w)) return kind;
  return s;
}

function normalizeRegion(item, options, manual = false) {
  if (!item || typeof item !== 'object') return null;
  let b = item.bbox || item.box;
  if (!Array.isArray(b)) b = [item.x, item.y, item.width ?? item.w, item.height ?? item.h];
  if (b.length < 4 || b.some(v => !Number.isFinite(Number(v)))) return null;
  let [x, y, width, height] = b.map(Number);
  // Set normalized:false explicitly for pixel boxes. Automatic conversion is
  // possible only when source dimensions are supplied and any value exceeds 1.
  const pixel = item.normalized === false || (item.normalized !== true && b.some(v => Number(v) > 1));
  if (pixel) {
    const sw = finite(options.sourceWidth), sh = finite(options.sourceHeight);
    if (!(sw > 0 && sh > 0)) return null;
    x /= sw; width /= sw; y /= sh; height /= sh;
  }
  const left = clamp(x, 0, 1), top = clamp(y, 0, 1);
  const right = clamp(x + width, 0, 1), bottom = clamp(y + height, 0, 1);
  if (!(right > left && bottom > top)) return null;
  let polygon;
  if (Array.isArray(item.polygon) && item.polygon.length >= 3) {
    polygon = item.polygon.map(p => Array.isArray(p) ? [finite(p[0], NaN), finite(p[1], NaN)] : [NaN, NaN]);
    if (pixel) polygon = polygon.map(([px, py]) => [px / options.sourceWidth, py / options.sourceHeight]);
    if (polygon.some(p => p.some(v => !Number.isFinite(v)))) polygon = undefined;
    else polygon = polygon.map(p => [clamp(p[0], left, right), clamp(p[1], top, bottom)]);
  }
  return {
    id: String(item.id || `${manual ? 'manual' : 'object'}-${left}-${top}`),
    type: labelType(item.type || item.label || item.class || item.className),
    x: left, y: top, width: right - left, height: bottom - top,
    normalized: true, source: manual ? 'manual' : 'detector',
    feather: clamp(finite(item.feather, 0.12), 0, 0.45),
    ...(polygon ? { polygon } : {}),
  };
}

/** Rule parser, not a language model. Unsupported sentences stay visible. */
export function parsePrompt(prompt = '', objects = [], options = {}) {
  const text = String(prompt).normalize('NFKC').toLowerCase().trim();
  const recognized = [], unhandled = [], warnings = [];
  const hits = {};
  for (const [key, words] of Object.entries(WORDS)) {
    hits[key] = matches(text, words);
    if (hits[key].length && key !== 'unsupported') recognized.push(key);
  }
  const maxRegions = clamp(Math.floor(finite(options.maxRegions, 8)), 0, 12);
  const requested = [];
  for (const [kind, names] of Object.entries(LABELS)) if (matches(text, names).length) requested.push(kind);
  const detected = (Array.isArray(objects) ? objects : []).map(x => normalizeRegion(x, options)).filter(Boolean);
  const manual = (Array.isArray(options.regions) ? options.regions : []).map(x => normalizeRegion(x, options, true)).filter(Boolean);
  const all = [...manual, ...detected.filter(x => !MANUAL_ONLY.has(x.type))];
  if (detected.some(x => MANUAL_ONLY.has(x.type))) warnings.push('Water, tree and cloud effects require a manual region; detector labels are not accepted as segmentation.');
  const zoomIn = hits.zoomIn.length > 0, zoomOut = hits.zoomOut.length > 0;
  const panX = (hits.right.length ? 0.16 : 0) - (hits.left.length ? 0.16 : 0);
  const panY = (hits.down.length ? 0.16 : 0) - (hits.up.length ? 0.16 : 0);
  // A slight cover crop gives a requested pan room to move even when source
  // and output have the same aspect. No blank border pixels are synthesized.
  const panZoom = (panX || panY) && !zoomIn && !zoomOut ? 1.08 : 1;
  const camera = {
    zoomStart: zoomOut ? 1.15 : panZoom,
    zoomEnd: zoomIn ? 1.15 : panZoom,
    panX, panY, easing: 'smoothstep',
  };
  if (zoomIn && zoomOut) warnings.push('Conflicting zoom directions were combined into a stationary crop.');
  if ((hits.left.length && hits.right.length) || (hits.up.length && hits.down.length)) warnings.push('Opposite camera directions cancel each other.');
  const effects = [];
  if (hits.rain.length) effects.push({ kind: 'rain', count: clamp(finite(options.particleCount, 90), 1, 200) });
  if (hits.snow.length) effects.push({ kind: 'snow', count: clamp(finite(options.particleCount, 65), 1, 200) });
  let regionCount = 0;
  for (const region of all) {
    if (requested.length && !requested.includes(region.type)) continue;
    let kind;
    if (region.type === 'water' && hits.water.length) kind = 'wave';
    else if (region.type === 'tree' && (hits.sway.length || hits.animate.length)) kind = 'sway';
    else if (region.type === 'cloud' && (hits.bob.length || hits.sway.length || hits.animate.length)) kind = 'bob';
    else if (hits.sway.length) kind = 'sway';
    else if (hits.bob.length && ['boat', 'bird', 'cloud'].includes(region.type)) kind = 'bob';
    else if (hits.pulse.length && ['person', 'cat', 'dog', 'bird'].includes(region.type)) kind = 'pulse';
    else if (hits.animate.length && ['boat', 'bird', 'cloud', 'car', 'truck'].includes(region.type)) kind = 'bob';
    else if (hits.animate.length && ['person', 'cat', 'dog'].includes(region.type)) kind = 'pulse';
    if (!kind) continue;
    if (regionCount >= maxRegions) continue;
    effects.push({ kind, region, amplitude: kind === 'pulse' ? 0.025 : kind === 'wave' ? 0.006 : 0.035, cycles: kind === 'wave' ? 2 : 1 });
    regionCount++;
  }
  if (all.length > maxRegions && regionCount === maxRegions) warnings.push(`Region budget is limited to ${maxRegions}; extra regions are skipped.`);
  if (regionCount) warnings.push('Selected regions use small masked pixel deformations. These do not infer pose, synthesize hidden backgrounds, or make a person walk or an animal fly.');
  if (hits.water.length && !effects.some(x => x.kind === 'wave')) warnings.push('Draw and label a manual water region to apply ripple distortion.');
  for (const kind of requested) if (!all.some(x => x.type === kind)) warnings.push(`No usable ${kind} region was supplied; it is not invented from the prompt.`);
  if (hits.unsupported.length) {
    unhandled.push(...hits.unsupported);
    warnings.push('Walking, flying, speech, object creation/removal and articulated motion need other tools. This engine changes existing pixels only.');
  }
  const active = effects.length || camera.zoomStart !== camera.zoomEnd || panX || panY;
  if (text && !active && !unhandled.length) {
    unhandled.push(String(prompt));
    warnings.push('No supported rule matched. Try “zoom in”, “sway”, “breathe”, “rain”, or select a manual water region and request ripples.');
  }
  return {
    version: 1, engine: 'cpu-geometric-rules', prompt: String(prompt),
    camera, effects, warnings: [...new Set(warnings)], recognized: [...new Set(recognized)],
    unhandled: [...new Set(unhandled)], seed: (finite(options.seed, 314159) >>> 0),
  };
}

function frameTime(t, duration) {
  const d = finite(duration);
  return d > 0 ? clamp(finite(t) / d, 0, 1) : 0;
}

/** Aspect-preserving source crop. panX/panY move its center in available space. */
export function cameraTransform(sourceWidth, sourceHeight, outputWidth, outputHeight, camera = {}, progress = 0) {
  if (![sourceWidth, sourceHeight, outputWidth, outputHeight].every(x => Number.isFinite(x) && x > 0)) throw new RangeError('Positive image dimensions are required.');
  const p = smooth(progress);
  const start = clamp(finite(camera.zoomStart, 1), 1, 8), end = clamp(finite(camera.zoomEnd, 1), 1, 8);
  const zoom = start + (end - start) * p;
  const aspect = outputWidth / outputHeight;
  let cropWidth = sourceWidth, cropHeight = sourceHeight;
  if (sourceWidth / sourceHeight > aspect) cropWidth = cropHeight * aspect;
  else cropHeight = cropWidth / aspect;
  cropWidth /= zoom; cropHeight /= zoom;
  const availableX = (sourceWidth - cropWidth) / 2, availableY = (sourceHeight - cropHeight) / 2;
  const centerX = sourceWidth / 2 + availableX * clamp(finite(camera.panX), -1, 1) * (2 * p - 1);
  const centerY = sourceHeight / 2 + availableY * clamp(finite(camera.panY), -1, 1) * (2 * p - 1);
  return { x: centerX - cropWidth / 2, y: centerY - cropHeight / 2, width: cropWidth, height: cropHeight, zoom };
}

export function mapCameraPoint(x, y, source, plan, t, duration, output) {
  const crop = cameraTransform(source.width, source.height, output.width, output.height, plan?.camera, frameTime(t, duration));
  return { x: crop.x + (x + 0.5) * crop.width / output.width - 0.5, y: crop.y + (y + 0.5) * crop.height / output.height - 0.5 };
}

function insidePolygon(x, y, polygon) {
  if (!polygon) return true;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i], [xj, yj] = polygon[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function sample(data, width, height, x, y, target, at, mix = 1) {
  x = clamp(x, 0, width - 1); y = clamp(y, 0, height - 1);
  const x0 = Math.floor(x), y0 = Math.floor(y), x1 = Math.min(x0 + 1, width - 1), y1 = Math.min(y0 + 1, height - 1);
  const fx = x - x0, fy = y - y0;
  const a = (y0 * width + x0) * 4, b = (y0 * width + x1) * 4, c = (y1 * width + x0) * 4, d = (y1 * width + x1) * 4;
  for (let ch = 0; ch < 4; ch++) {
    const top = data[a + ch] * (1 - fx) + data[b + ch] * fx;
    const bottom = data[c + ch] * (1 - fx) + data[d + ch] * fx;
    const value = top * (1 - fy) + bottom * fy;
    target[at + ch] = mix === 1 ? value : target[at + ch] * (1 - mix) + value * mix;
  }
}

function regionMask(x, y, r) {
  if (x < r.x || x > r.right || y < r.y || y > r.bottom || !insidePolygon(x, y, r.polygon)) return 0;
  if (r.feather === 0) return 1;
  const dx = Math.min(x - r.x, r.right - x) / Math.max(1e-9, r.width * r.feather);
  const dy = Math.min(y - r.y, r.bottom - y) / Math.max(1e-9, r.height * r.feather);
  return smooth(Math.min(dx, dy));
}

function rng(seed) {
  let a = seed >>> 0;
  return () => { a += 0x6D2B79F5; let v = a; v = Math.imul(v ^ v >>> 15, v | 1); v ^= v + Math.imul(v ^ v >>> 7, v | 61); return ((v ^ v >>> 14) >>> 0) / 4294967296; };
}

function blendPixel(data, w, h, x, y, color, alpha) {
  x = Math.round(x); y = Math.round(y);
  if (x < 0 || y < 0 || x >= w || y >= h) return;
  const k = (y * w + x) * 4;
  for (let ch = 0; ch < 3; ch++) data[k + ch] = data[k + ch] * (1 - alpha) + color[ch] * alpha;
  // Compositing on transparent images preserves the expected source-over alpha.
  data[k + 3] = data[k + 3] + (255 - data[k + 3]) * alpha;
}

function particles(data, width, height, effect, seed, p) {
  const random = rng(seed ^ (effect.kind === 'rain' ? 0xAA7711 : 0x1177AA));
  const count = clamp(Math.floor(finite(effect.count, 65)), 0, 200);
  for (let i = 0; i < count; i++) {
    const startX = random(), startY = random(), speed = 0.6 + random() * 0.9;
    const size = 1 + Math.floor(random() * Math.max(1, Math.min(width, height) / 240));
    const y = ((startY + p * speed) % 1) * height;
    const x = ((startX + (effect.kind === 'snow' ? Math.sin(p * TAU + i) * 0.025 : p * 0.07) + 1) % 1) * width;
    if (effect.kind === 'rain') {
      const length = Math.max(3, Math.round(height / 60));
      for (let k = 0; k < length; k++) blendPixel(data, width, height, x - k * 0.2, y - k, [185, 215, 235], 0.32);
    } else {
      for (let dy = -size; dy <= size; dy++) for (let dx = -size; dx <= size; dx++) if (dx * dx + dy * dy <= size * size) blendPixel(data, width, height, x + dx, y + dy, [255, 255, 255], 0.7);
    }
  }
}

/**
 * Render RGBA on the CPU. output may be a reused buffer to avoid allocations:
 * {width,height,data:Uint8ClampedArray}. t is seconds; duration is seconds.
 */
export function renderFrame(source, plan = {}, t = 0, duration = 5, output = {}) {
  const sw = Number(source?.width), sh = Number(source?.height);
  if (!Number.isInteger(sw) || !Number.isInteger(sh) || sw <= 0 || sh <= 0 || !source?.data || source.data.length !== sw * sh * 4) throw new TypeError('Source must be a valid RGBA ImageData-like object.');
  const width = Math.floor(finite(output.width, sw)), height = Math.floor(finite(output.height, sh));
  if (width <= 0 || height <= 0 || width > 4096 || height > 4096 || width * height > 8_388_608) throw new RangeError('Output size exceeds the bounded CPU canvas budget.');
  if (output.data !== undefined && (!(output.data instanceof Uint8ClampedArray) || output.data.length !== width * height * 4 || output.data === source.data)) throw new TypeError('Output buffer must be separate RGBA Uint8ClampedArray of the requested size.');
  const data = output.data || new Uint8ClampedArray(width * height * 4);
  const p = frameTime(t, duration);
  const crop = cameraTransform(sw, sh, width, height, plan.camera || {}, p);
  const effects = (Array.isArray(plan.effects) ? plan.effects : []).filter(e => e?.region).slice(0, 12).map(e => {
    const r = e.region;
    const x = clamp(finite(r.x), 0, 1) * sw, y = clamp(finite(r.y), 0, 1) * sh;
    const rw = clamp(finite(r.width), 0, 1) * sw, rh = clamp(finite(r.height), 0, 1) * sh;
    return { ...e, region: { x, y, width: rw, height: rh, right: x + rw, bottom: y + rh, feather: clamp(finite(r.feather, 0.12), 0, 0.45), polygon: r.polygon?.map(([px, py]) => [px * sw, py * sh]) }, phase: TAU * p * clamp(finite(e.cycles, 1), 0.1, 8), amplitude: clamp(finite(e.amplitude, 0.035), 0, 0.08) };
  });
  const stepX = crop.width / width, stepY = crop.height / height;
  for (let py = 0, at = 0; py < height; py++) {
    const sy = crop.y + (py + 0.5) * stepY - 0.5;
    for (let px = 0; px < width; px++, at += 4) {
      const sx = crop.x + (px + 0.5) * stepX - 0.5;
      sample(source.data, sw, sh, sx, sy, data, at);
      for (const effect of effects) {
        const r = effect.region, mask = regionMask(sx, sy, r);
        if (mask <= 0) continue;
        const u = (sx - r.x) / Math.max(1, r.width), v = (sy - r.y) / Math.max(1, r.height);
        let wx = sx, wy = sy;
        const wave = Math.sin(effect.phase);
        if (effect.kind === 'sway') wx -= wave * effect.amplitude * r.width * (1 - v);
        else if (effect.kind === 'bob') wy -= wave * effect.amplitude * r.height;
        else if (effect.kind === 'pulse') {
          const scale = 1 + wave * effect.amplitude;
          wx = r.x + r.width / 2 + (sx - r.x - r.width / 2) / scale;
          wy = r.y + r.height / 2 + (sy - r.y - r.height / 2) / scale;
        } else if (effect.kind === 'wave') {
          wx -= Math.sin(v * TAU * 3 + effect.phase) * effect.amplitude * r.width;
          wy -= Math.sin(u * TAU * 2 - effect.phase) * effect.amplitude * r.height * 0.45;
        } else continue;
        // Mask stays fixed. Sampling is clamped to its selected rectangle and
        // rejected outside the selected polygon: no fake background inpainting.
        wx = clamp(wx, r.x, Math.max(r.x, r.right - 1)); wy = clamp(wy, r.y, Math.max(r.y, r.bottom - 1));
        if (insidePolygon(wx, wy, r.polygon)) sample(source.data, sw, sh, wx, wy, data, at, mask);
      }
    }
  }
  for (const effect of (Array.isArray(plan.effects) ? plan.effects : [])) if (effect.kind === 'rain' || effect.kind === 'snow') particles(data, width, height, effect, finite(plan.seed, 314159), p);
  return { width, height, data };
}
