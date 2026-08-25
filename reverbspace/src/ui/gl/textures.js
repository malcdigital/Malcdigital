// Surfaces, generated rather than photographed.
//
// Every texture here is drawn at load into an offscreen canvas, which keeps the
// whole app a single small file -- a photographic set would add megabytes, and
// the page has to load over a phone connection. Each one also produces a normal
// map derived from its own luminance, so the lighting has something to catch:
// grain in the wood, the weave in a panel, the mortar between stones.

const TEX = 512;

/** Value noise with a smooth interpolant, tiling at `period`. */
function noiseField(period, seed) {
  const g = new Float32Array(period * period);
  let s = seed >>> 0;
  for (let i = 0; i < g.length; i++) {
    s ^= s << 13; s ^= s >>> 17; s ^= s << 5;
    g[i] = (s >>> 0) / 4294967296;
  }
  return (x, y) => {
    const xi = Math.floor(x), yi = Math.floor(y);
    const xf = x - xi, yf = y - yi;
    const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
    const at = (a, b) => g[(((b % period) + period) % period) * period + (((a % period) + period) % period)];
    return (at(xi, yi) * (1 - u) + at(xi + 1, yi) * u) * (1 - v)
         + (at(xi, yi + 1) * (1 - u) + at(xi + 1, yi + 1) * u) * v;
  };
}

/** Sum of octaves, so the grain has both broad figure and fine detail. */
function fbm(period, seed, octaves = 4) {
  const layers = [];
  for (let o = 0; o < octaves; o++) layers.push(noiseField(period * (1 << o), seed + o * 977));
  return (x, y) => {
    let sum = 0, amp = 1, norm = 0, f = 1;
    for (const n of layers) {
      sum += n(x * f, y * f) * amp;
      norm += amp;
      amp *= 0.5;
      f *= 2;
    }
    return sum / norm;
  };
}

function makeCanvas(size = TEX) {
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  return c;
}

const mix = (a, b, t) => a + (b - a) * t;
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

function rgb(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/**
 * Boards running down the V axis, with grain, knots and a dark seam at every
 * joint. `boards` is how many fit across one tile.
 */
export function woodTexture({ base = '#8a5a30', boards = 4, seed = 7, grain = 0.55, knots = 3 } = {}) {
  const c = makeCanvas();
  const g = c.getContext('2d');
  const img = g.createImageData(TEX, TEX);
  const d = img.data;
  const [br, bg, bb] = rgb(base);
  const fine = fbm(64, seed, 4);
  const figure = fbm(8, seed + 31, 3);
  const boardW = TEX / boards;

  // Each board gets its own tone, the way a real wall of cedar does.
  const tone = [];
  for (let i = 0; i < boards; i++) {
    const n = noiseField(16, seed + i * 131)(i * 3.7, 1.3);
    tone.push(0.82 + n * 0.36);
  }

  const knotList = [];
  for (let k = 0; k < knots; k++) {
    const n = noiseField(32, seed + 700 + k)(k * 5.1, k * 2.3);
    const m = noiseField(32, seed + 900 + k)(k * 1.7, k * 6.1);
    knotList.push({ x: n * TEX, y: m * TEX, r: 4 + m * 9 });
  }

  for (let y = 0; y < TEX; y++) {
    for (let x = 0; x < TEX; x++) {
      const bi = Math.floor(x / boardW);
      const inBoard = (x % boardW) / boardW;
      let v = tone[bi];

      // Grain: stretched along the board, so it reads as timber not marble.
      const gx = x * 0.14 + bi * 17;
      const gv = fine(gx, y * 0.012) * 0.55 + figure(gx * 0.3, y * 0.004) * 0.45;
      v *= 1 - grain * 0.35 + gv * grain * 0.7;

      // Seams: a dark line and a lit edge, which is what makes planks read.
      const edge = Math.min(inBoard, 1 - inBoard);
      if (edge < 0.018) v *= 0.42 + edge * 18;
      else if (edge < 0.05) v *= 0.94 + edge * 1.2;

      for (const k of knotList) {
        const dx = x - k.x, dy = y - k.y;
        const dist = Math.hypot(dx, dy * 2.4);
        if (dist < k.r) v *= mix(0.45, 1, clamp01(dist / k.r));
        else if (dist < k.r * 2.4) v *= mix(0.86, 1, clamp01((dist - k.r) / (k.r * 1.4)));
      }

      const i = (y * TEX + x) * 4;
      d[i] = clamp01((br * v) / 255) * 255;
      d[i + 1] = clamp01((bg * v) / 255) * 255;
      d[i + 2] = clamp01((bb * v) / 255) * 255;
      d[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return c;
}

/** Courses of stone with mortar joints and mottled faces. */
export function stoneTexture({ base = '#8d8b84', rows = 6, seed = 11 } = {}) {
  const c = makeCanvas();
  const g = c.getContext('2d');
  const img = g.createImageData(TEX, TEX);
  const d = img.data;
  const [br, bg, bb] = rgb(base);
  const mottle = fbm(16, seed, 4);
  const fine = fbm(96, seed + 51, 3);
  const rowH = TEX / rows;
  const cols = Math.max(2, Math.round(rows * 1.6));
  const colW = TEX / cols;

  for (let y = 0; y < TEX; y++) {
    const row = Math.floor(y / rowH);
    const offset = (row % 2) * colW * 0.5;
    for (let x = 0; x < TEX; x++) {
      const sx = (x + offset) % TEX;
      const col = Math.floor(sx / colW);
      const blockSeed = noiseField(32, seed + 300)(col * 2.3, row * 3.1);
      let v = 0.78 + blockSeed * 0.34;
      v *= 0.82 + mottle(x * 0.03 + col * 9, y * 0.03 + row * 7) * 0.36;
      v *= 0.93 + fine(x * 0.2, y * 0.2) * 0.14;

      const ey = Math.min(y % rowH, rowH - (y % rowH)) / rowH;
      const ex = Math.min(sx % colW, colW - (sx % colW)) / colW;
      const joint = Math.min(ey, ex);
      if (joint < 0.022) v *= 0.46 + joint * 12;      // mortar
      else if (joint < 0.06) v *= 1.04;                // lit arris

      const i = (y * TEX + x) * 4;
      d[i] = clamp01((br * v) / 255) * 255;
      d[i + 1] = clamp01((bg * v) / 255) * 255;
      d[i + 2] = clamp01((bb * v) / 255) * 255;
      d[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return c;
}

/** Acoustic-panel fabric: a woven grid under fine noise. */
export function fabricTexture({ base = '#4a5a48', seed = 5 } = {}) {
  const c = makeCanvas();
  const g = c.getContext('2d');
  const img = g.createImageData(TEX, TEX);
  const d = img.data;
  const [br, bg, bb] = rgb(base);
  const fine = fbm(128, seed, 3);
  for (let y = 0; y < TEX; y++) {
    for (let x = 0; x < TEX; x++) {
      const weave = (Math.sin(x * 0.9) * Math.sin(y * 0.9)) * 0.055;
      const v = 0.9 + weave + (fine(x * 0.35, y * 0.35) - 0.5) * 0.22;
      const i = (y * TEX + x) * 4;
      d[i] = clamp01((br * v) / 255) * 255;
      d[i + 1] = clamp01((bg * v) / 255) * 255;
      d[i + 2] = clamp01((bb * v) / 255) * 255;
      d[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return c;
}

/** Flat finishes: plaster, board, paint. Barely textured, but not plastic. */
export function plasterTexture({ base = '#c8c2b6', seed = 3, strength = 0.12 } = {}) {
  const c = makeCanvas();
  const g = c.getContext('2d');
  const img = g.createImageData(TEX, TEX);
  const d = img.data;
  const [br, bg, bb] = rgb(base);
  const n = fbm(48, seed, 4);
  for (let y = 0; y < TEX; y++) {
    for (let x = 0; x < TEX; x++) {
      const v = 1 + (n(x * 0.09, y * 0.09) - 0.5) * strength;
      const i = (y * TEX + x) * 4;
      d[i] = clamp01((br * v) / 255) * 255;
      d[i + 1] = clamp01((bg * v) / 255) * 255;
      d[i + 2] = clamp01((bb * v) / 255) * 255;
      d[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return c;
}

/**
 * Normal map derived from an albedo's luminance. Not physically the same thing
 * as a measured height field, but grain darker than its surround does sit
 * lower, so it catches light convincingly.
 */
export function normalFrom(canvas, strength = 2.2) {
  const size = canvas.width;
  const src = canvas.getContext('2d').getImageData(0, 0, size, size).data;
  const out = document.createElement('canvas');
  out.width = size;
  out.height = size;
  const g = out.getContext('2d');
  const img = g.createImageData(size, size);
  const d = img.data;
  const lum = (x, y) => {
    const i = ((((y % size) + size) % size) * size + (((x % size) + size) % size)) * 4;
    return (src[i] * 0.299 + src[i + 1] * 0.587 + src[i + 2] * 0.114) / 255;
  };
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (lum(x + 1, y) - lum(x - 1, y)) * strength;
      const dy = (lum(x, y + 1) - lum(x, y - 1)) * strength;
      const len = Math.sqrt(dx * dx + dy * dy + 1);
      const i = (y * size + x) * 4;
      d[i] = ((-dx / len) * 0.5 + 0.5) * 255;
      d[i + 1] = ((-dy / len) * 0.5 + 0.5) * 255;
      d[i + 2] = (1 / len) * 0.5 * 255 + 127.5;
      // Height rides in the alpha channel. A normal map says which way a
      // surface tilts but not how far in it sits, and without that a groove
      // between two boards stays perfectly flat however you look along it.
      d[i + 3] = lum(x, y) * 255;
    }
  }
  g.putImageData(img, 0, 0);
  return out;
}
