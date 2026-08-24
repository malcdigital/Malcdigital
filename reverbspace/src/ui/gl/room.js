// Turns the room state into geometry batches and lights.
//
// Everything acoustic -- the six surfaces, the wall panels, the ceiling clouds,
// the seating -- is built from the same numbers the model uses. Everything else
// is marked `decor: true`, and the interface says so, because a stool absorbs
// sound in life and does not in here.

import { MeshBuilder } from './mesh.js';
import { MATERIALS, TREATMENTS } from '../../core/materials.js';
import { PRESETS_BY_ID } from '../../core/presets.js';

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const lerp = (a, b, t) => a + (b - a) * t;

function hash(a, b) {
  let n = (a * 374761393 + b * 668265263) | 0;
  n = (n ^ (n >> 13)) * 1274126177;
  return ((n ^ (n >> 16)) >>> 0) / 4294967296;
}

function shuffled(n, seed) {
  const a = [];
  for (let i = 0; i < n; i++) a.push(i);
  let s = seed * 2654435761 + 12345;
  for (let i = n - 1; i > 0; i--) {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    const j = s % (i + 1);
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/**
 * Build every mesh for the current room.
 * Returns batches keyed by material name plus the lights that fit in it.
 */
export function buildRoom(state) {
  const preset = PRESETS_BY_ID[state.presetId];
  const { w, d, h } = state.dims;
  const out = {
    walls: new MeshBuilder(),
    floor: new MeshBuilder(),
    ceiling: new MeshBuilder(),
    trim: new MeshBuilder(),
    panels: new MeshBuilder(),
    panelsAlt: new MeshBuilder(),
    metal: new MeshBuilder(),
    glow: new MeshBuilder(),
    glass: new MeshBuilder(),
    seats: new MeshBuilder(),
    decor: new MeshBuilder(),
  };
  const lights = [];

  // ---- the six surfaces the model actually uses --------------------------
  // Wound so the normals point into the room: a floor faces up, a ceiling
  // faces down. Backwards, the floor is lit as if from below and the ceiling
  // is culled away entirely.
  out.floor.quad([0, 0, 0], [0, 0, d], [w, 0, d], [w, 0, 0]);
  out.ceiling.quad([0, h, 0], [w, h, 0], [w, h, d], [0, h, d]);
  out.walls.quad([0, 0, 0], [w, 0, 0], [w, h, 0], [0, h, 0]);
  out.walls.quad([w, 0, d], [0, 0, d], [0, h, d], [w, h, d]);
  out.walls.quad([0, 0, d], [0, 0, 0], [0, h, 0], [0, h, d]);
  out.walls.quad([w, 0, 0], [w, 0, d], [w, h, d], [w, h, 0]);

  // ---- trim: what gives a room its scale ---------------------------------
  const skirt = clamp(h * 0.045, 0.08, 0.26);
  const t = 0.035;
  out.trim.box([0, 0, 0], [w, skirt, t]);
  out.trim.box([0, 0, d - t], [w, skirt, d]);
  out.trim.box([0, 0, t], [t, skirt, d - t]);
  out.trim.box([w - t, 0, t], [w, skirt, d - t]);

  // Cornice where wall meets ceiling.
  const cor = clamp(h * 0.028, 0.05, 0.2);
  out.trim.box([0, h - cor, 0], [w, h, cor]);
  out.trim.box([0, h - cor, d - cor], [w, h, d]);
  out.trim.box([0, h - cor, cor], [cor, h, d - cor]);
  out.trim.box([w - cor, h - cor, cor], [w, h, d - cor]);

  // Exposed ceiling beams, running the short way like a real timber ceiling.
  if (preset.id === 'studio' || preset.id === 'hall' || preset.id === 'theater') {
    const spacing = clamp(Math.max(1.1, w / 7), 1.1, 3.2);
    const bw = clamp(spacing * 0.16, 0.08, 0.3);
    const bh = clamp(h * 0.05, 0.09, 0.35);
    for (let x = spacing * 0.5; x < w - 0.2; x += spacing) {
      out.trim.box([x - bw / 2, h - bh, 0], [x + bw / 2, h, d]);
    }
  }

  // ---- treatment: coverage the model is using ----------------------------
  const cov = clamp(state.treatment.coverage, 0, 1);
  const treat = TREATMENTS[state.treatment.type] || TREATMENTS.rockwool;
  if (cov > 0.02) {
    const walls = [
      { id: 0, len: w, at: (u, v) => [u, v, 0.02], n: [0, 0, 1] },
      { id: 1, len: w, at: (u, v) => [w - u, v, d - 0.02], n: [0, 0, -1] },
      { id: 2, len: d, at: (u, v) => [0.02, v, d - u], n: [1, 0, 0] },
      { id: 3, len: d, at: (u, v) => [w - 0.02, v, u], n: [-1, 0, 0] },
    ];
    const thick = 0.07;
    for (const wall of walls) {
      const cols = Math.max(2, Math.round(wall.len / 1.9));
      const rows = Math.max(2, Math.round(h / 1.7));
      const order = shuffled(cols * rows, wall.id + 3);
      const want = Math.round(cols * rows * clamp(cov, 0, 0.92));
      for (let k = 0; k < want; k++) {
        const idx = order[k];
        const c = idx % cols, r = (idx / cols) | 0;
        const pad = 0.14;
        const u0 = (c / cols) * wall.len + pad, u1 = ((c + 1) / cols) * wall.len - pad;
        const v0 = (r / rows) * h + pad, v1 = ((r + 1) / rows) * h - pad;
        if (u1 <= u0 || v1 <= v0) continue;
        const a = wall.at(u0, v0), b = wall.at(u1, v1);
        const lo = [Math.min(a[0], b[0]), v0, Math.min(a[2], b[2])];
        const hi = [Math.max(a[0], b[0]), v1, Math.max(a[2], b[2])];
        // Give the slab depth on the axis it stands off the wall.
        if (wall.n[0] !== 0) { lo[0] -= thick * (wall.n[0] > 0 ? 0 : 1); hi[0] += thick * (wall.n[0] > 0 ? 1 : 0); }
        else { lo[2] -= thick * (wall.n[2] > 0 ? 0 : 1); hi[2] += thick * (wall.n[2] > 0 ? 1 : 0); }
        // A third of them in a second tone: nobody hangs a wall of identical
        // panels, and the variation is what stops it reading as wallpaper.
        (hash(wall.id * 31 + idx, 57) < 0.34 ? out.panelsAlt : out.panels).box(lo, hi);
      }
    }

    // Clouds hung under the ceiling on chains.
    const count = Math.round(cov * Math.max(3, (w * d) / 7));
    const cw = clamp(Math.min(w, d) * 0.17, 0.8, 2.4);
    const cd = cw * 0.6;
    for (let i = 0; i < count; i++) {
      const cx = lerp(cw, w - cw, hash(i, 101));
      const cz = lerp(cd, d - cd, hash(i, 211));
      const drop = lerp(0.2, 0.8, hash(i, 307)) * clamp(h / 3.2, 0.6, 2.6);
      const y = h - drop - 0.05;
      if (y < state.source.height + 0.35) continue;
      const rot = (hash(i, 401) - 0.5) * 0.9;
      out.panels.boxRotY([cx, y, cz], [cw, 0.1, cd], rot);
      // A frame round the edge, so a cloud reads as a built absorber rather
      // than a floating slab.
      const fr = 0.05;
      out.metal.boxRotY([cx, y, cz], [cw + fr, 0.045, cd + fr], rot);
      const ca = Math.cos(rot), sa = Math.sin(rot);
      for (const [ox, oz] of [[-cw / 2 + 0.12, -cd / 2 + 0.1], [cw / 2 - 0.12, cd / 2 - 0.1]]) {
        const px = cx + ox * ca - oz * sa;
        const pz = cz + ox * sa + oz * ca;
        out.metal.tube([px, y + 0.05, pz], [px, h, pz], 0.008, 5, false);
      }
    }
  }

  // ---- fittings ----------------------------------------------------------
  const lampY = clamp(h * 0.58, 1.5, 5.0);
  const along = [
    { len: w, at: (u) => [u, lampY, 0.08], push: [0, 0, 1] },
    { len: w, at: (u) => [u, lampY, d - 0.08], push: [0, 0, -1] },
    { len: d, at: (u) => [0.08, lampY, u], push: [1, 0, 0] },
    { len: d, at: (u) => [w - 0.08, lampY, u], push: [-1, 0, 0] },
  ];
  for (const wall of along) {
    const n = clamp(Math.round(wall.len / 4.2), 1, 8);
    for (let i = 0; i < n; i++) {
      const p = wall.at(((i + 0.5) / n) * wall.len);
      const s = 0.17;
      const lo = [p[0] - s, p[1] - s, p[2] - s];
      const hi = [p[0] + s, p[1] + s, p[2] + s];
      // Flatten against its wall.
      if (wall.push[0] !== 0) { lo[0] = p[0] - 0.05; hi[0] = p[0] + 0.05; }
      else { lo[2] = p[2] - 0.05; hi[2] = p[2] + 0.05; }
      out.glow.box(lo, hi);
      lights.push({
        pos: [p[0] + wall.push[0] * 0.3, p[1], p[2] + wall.push[2] * 0.3],
        colour: [1.0, 0.86, 0.68],
        range: clamp(Math.max(w, d, h) * 0.55, 4, 26),
        power: 0.95,
      });
    }
  }

  // Overhead fill. A tracking room is not lit by wall sconces alone, and
  // without this the floor reads as a black hole under everything.
  const fills = clamp(Math.round((w * d) / 26), 1, 4);
  for (let i = 0; i < fills; i++) {
    for (let j = 0; j < fills; j++) {
      lights.push({
        pos: [((i + 0.5) / fills) * w, h * 0.92, ((j + 0.5) / fills) * d],
        colour: [1.0, 0.94, 0.87],
        range: clamp(Math.max(w, d) * 0.8, 6, 40),
        power: 0.5,
      });
    }
  }

  // A window into the control room, and a door.
  if (preset.id === 'studio' || preset.id === 'theater') {
    const cw = clamp(w * 0.24, 1.2, 2.8);
    const cy = clamp(h * 0.44, 1.05, 1.7);
    const x0 = w / 2 - cw / 2, x1 = w / 2 + cw / 2;
    out.glass.box([x0, cy - 0.45, 0.01], [x1, cy + 0.45, 0.06]);
    out.trim.box([x0 - 0.09, cy - 0.55, 0], [x1 + 0.09, cy - 0.45, 0.1]);
    out.trim.box([x0 - 0.09, cy + 0.45, 0], [x1 + 0.09, cy + 0.55, 0.1]);
    out.trim.box([x0 - 0.09, cy - 0.55, 0], [x0, cy + 0.55, 0.1]);
    out.trim.box([x1, cy - 0.55, 0], [x1 + 0.09, cy + 0.55, 0.1]);
    lights.push({
      pos: [w / 2, cy, 0.5], colour: [1.0, 0.85, 0.62],
      range: clamp(Math.max(w, d) * 0.6, 4, 18), power: 0.9,
    });
  }

  const doorZ = clamp(d * 0.24, 0.6, d - 1.2);
  const doorH = Math.min(2.05, h - 0.1);
  out.decor.box([0.02, 0, doorZ - 0.45], [0.08, doorH, doorZ + 0.45]);
  out.trim.box([0, 0, doorZ - 0.56], [0.1, doorH + 0.1, doorZ - 0.45]);
  out.trim.box([0, 0, doorZ + 0.45], [0.1, doorH + 0.1, doorZ + 0.56]);
  out.trim.box([0, doorH, doorZ - 0.56], [0.1, doorH + 0.1, doorZ + 0.56]);

  // ---- seating -----------------------------------------------------------
  if (preset.seating) {
    const rows = clamp(Math.round((d * preset.seating.coverage) / 1.05), 3, 26);
    const cols = clamp(Math.round(w / 0.95), 4, 30);
    const z0 = d * (1 - preset.seating.coverage);
    for (let r = 0; r < rows; r++) {
      const z = z0 + ((r + 0.35) / rows) * (d - z0);
      for (let c = 0; c < cols; c++) {
        const x = ((c + 0.5) / cols) * w;
        out.seats.box([x - 0.3, 0, z - 0.22], [x + 0.3, 0.42, z + 0.22]);
        out.seats.box([x - 0.3, 0.42, z + 0.08], [x + 0.3, 0.92, z + 0.22]);
      }
    }
  }

  // ---- decoration: drawn, not modelled -----------------------------------
  // Spare stands along a wall, coiled cable on hooks, a stool. None of this
  // absorbs anything; it is here because a room without it looks unused.
  const stands = clamp(Math.round(d / 1.1), 2, 7);
  for (let i = 0; i < stands; i++) {
    const bz = clamp(d * 0.35 + i * 0.26, 0.4, d - 0.4);
    const bx = w - 0.42;
    out.decor.tube([bx, 0.02, bz], [bx - 0.12 - (i % 2) * 0.04, 1.42 + (i % 3) * 0.13, bz - 0.1], 0.015, 6);
    out.decor.box([bx - 0.15, 0, bz - 0.15], [bx + 0.14, 0.025, bz + 0.15]);
  }
  if (h > 2.2 && w > 3) {
    const hookY = clamp(h * 0.42, 1.1, 1.9);
    const rows = 2;
    const per = clamp(Math.round(w / 1.9), 2, 4);
    for (let r0 = 0; r0 < rows; r0++) {
      for (let i = 0; i < per; i++) {
        // Kept to one side: the control-room window is in the middle of this
        // wall, and nobody hangs their cable run across the glass.
        const cx = w * 0.06 + ((i + 0.5) / per) * (w * 0.26);
        const cy = hookY - r0 * 0.4;
        out.decor.ring([cx, cy, 0.07], 0.13, 0.02, 'z');
        out.decor.tube([cx, cy + 0.14, 0.015], [cx, cy + 0.14, 0.06], 0.011, 5);
      }
    }
  }
  const sx = 0.75, sz = d - 0.9;
  out.decor.box([sx - 0.19, 0.56, sz - 0.19], [sx + 0.19, 0.62, sz + 0.19]);
  for (const [ox, oz] of [[-0.14, -0.14], [0.14, -0.14], [0.14, 0.14], [-0.14, 0.14]]) {
    out.decor.tube([sx + ox, 0, sz + oz], [sx + ox * 0.75, 0.56, sz + oz * 0.75], 0.012, 5);
  }

  return { batches: out, lights };
}

/** The mic and its stand, rebuilt whenever it moves. */
export function buildMic(state) {
  const body = new MeshBuilder();
  const metal = new MeshBuilder();
  const m = { x: state.mic.x, y: state.mic.height, z: state.mic.z };
  const az = state.mic.azimuth;
  const fx = Math.sin(az), fz = Math.cos(az);

  for (let i = 0; i < 3; i++) {
    const a = az + (i / 3) * Math.PI * 2 + 0.6;
    metal.tube([m.x, 0.06, m.z], [m.x + Math.sin(a) * 0.32, 0.02, m.z + Math.cos(a) * 0.32], 0.014, 6);
  }
  const neck = Math.max(0.12, m.y - 0.24);
  metal.tube([m.x, 0.04, m.z], [m.x, neck, m.z], 0.019, 10);
  metal.tube([m.x, neck, m.z], [m.x - fx * 0.06, m.y, m.z - fz * 0.06], 0.013, 8);

  body.tube([m.x - fx * 0.06, m.y, m.z - fz * 0.06], [m.x + fx * 0.04, m.y, m.z + fz * 0.04], 0.027, 14);
  body.tube([m.x + fx * 0.04, m.y, m.z + fz * 0.04], [m.x + fx * 0.1, m.y, m.z + fz * 0.1], 0.034, 14);
  return { body, metal };
}
