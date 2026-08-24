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
    screens: new MeshBuilder(),
    booth: new MeshBuilder(),
    decor: new MeshBuilder(),
  };
  const lights = [];

  // ---- the surfaces the model actually uses ------------------------------
  // A gable rises `rise` above the mean height and the eaves drop as far
  // below, so the volume matches the flat ceiling the decay is computed from.
  const rise = preset.pitch ? preset.pitch * (w / preset.dims.w) : 0;
  const eaves = h - rise;
  const ridge = h + rise;
  const win = windowOpening(preset, w, h);

  out.floor.quad([0, 0, 0], [0, 0, d], [w, 0, d], [w, 0, 0]);

  if (rise > 0.01) {
    // Two slopes meeting over the middle of the room, normals facing down.
    out.ceiling.quad([0, eaves, 0], [w / 2, ridge, 0], [w / 2, ridge, d], [0, eaves, d]);
    out.ceiling.quad([w / 2, ridge, 0], [w, eaves, 0], [w, eaves, d], [w / 2, ridge, d]);
    out.trim.box([w / 2 - 0.09, ridge - 0.16, 0], [w / 2 + 0.09, ridge, d]);
  } else {
    out.ceiling.quad([0, h, 0], [w, h, 0], [w, h, d], [0, h, d]);
  }

  // Front wall, with the control-room opening cut out of it.
  const front = (x0, y0, x1, y1) => out.walls.quad([x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0]);
  if (win) {
    front(0, 0, w, win.y0);
    front(0, win.y1, w, eaves);
    front(0, win.y0, win.x0, win.y1);
    front(win.x1, win.y0, w, win.y1);
  } else {
    front(0, 0, w, eaves);
  }
  out.walls.quad([w, 0, d], [0, 0, d], [0, eaves, d], [w, eaves, d]);
  out.walls.quad([0, 0, d], [0, 0, 0], [0, eaves, 0], [0, eaves, d]);
  out.walls.quad([w, 0, 0], [w, 0, d], [w, eaves, d], [w, eaves, 0]);

  if (rise > 0.01) {
    out.walls.tri([0, eaves, 0], [w, eaves, 0], [w / 2, ridge, 0]);
    out.walls.tri([w, eaves, d], [0, eaves, d], [w / 2, ridge, d]);
  }

  // ---- trim: what gives a room its scale ---------------------------------
  const skirt = clamp(h * 0.045, 0.08, 0.26);
  const t = 0.035;
  out.trim.box([0, 0, 0], [w, skirt, t]);
  out.trim.box([0, 0, d - t], [w, skirt, d]);
  out.trim.box([0, 0, t], [t, skirt, d - t]);
  out.trim.box([w - t, 0, t], [w, skirt, d - t]);

  // Cornice along the eaves.
  const cor = clamp(h * 0.028, 0.05, 0.2);
  out.trim.box([0, eaves - cor, 0], [w, eaves, cor]);
  out.trim.box([0, eaves - cor, d - cor], [w, eaves, d]);
  out.trim.box([0, eaves - cor, cor], [cor, eaves, d - cor]);
  out.trim.box([w - cor, eaves - cor, cor], [w, eaves, d - cor]);

  // Rafters, following the slope where there is one.
  if (preset.id === 'studio' || preset.id === 'hall' || preset.id === 'theater') {
    const spacing = clamp(Math.max(1.1, d / 6), 0.9, 3.2);
    const bw = clamp(spacing * 0.14, 0.07, 0.26);
    const bh = clamp(h * 0.045, 0.08, 0.3);
    for (let z = spacing * 0.5; z < d - 0.15; z += spacing) {
      if (rise > 0.01) {
        // Along the slope, eaves to ridge. A box turned about the vertical
        // cannot tilt, so these are built as prisms between the two ends.
        const drop = bh * 0.55;
        out.trim.tube([0.02, eaves - drop, z], [w / 2, ridge - drop, z], bw * 0.8, 4);
        out.trim.tube([w / 2, ridge - drop, z], [w - 0.02, eaves - drop, z], bw * 0.8, 4);
      } else {
        out.trim.box([0, h - bh, z - bw / 2], [w, h, z + bw / 2]);
      }
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
      const rows = Math.max(2, Math.round(eaves / 1.7));
      const order = shuffled(cols * rows, wall.id + 3);
      const want = Math.round(cols * rows * clamp(cov, 0, 0.92));
      for (let k = 0; k < want; k++) {
        const idx = order[k];
        const c = idx % cols, r = (idx / cols) | 0;
        const pad = 0.14;
        const u0 = (c / cols) * wall.len + pad, u1 = ((c + 1) / cols) * wall.len - pad;
        const v0 = (r / rows) * eaves + pad, v1 = ((r + 1) / rows) * eaves - pad;
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
      // Hung below whatever the ceiling is doing overhead at that point.
      const local = rise > 0.01 ? eaves + (1 - Math.abs(cx - w / 2) / (w / 2)) * rise * 2 : h;
      const drop = lerp(0.2, 0.8, hash(i, 307)) * clamp(h / 3.2, 0.6, 2.6);
      const y = local - drop - 0.05;
      if (y < state.source.height + 0.35) continue;
      const rot = (hash(i, 401) - 0.5) * 0.9;
      out.panels.boxRotY([cx, y, cz], [cw, 0.1, cd], rot);
      // A timber frame round the edge, so a cloud reads as a built absorber
      // rather than a floating slab. Wood, not steel: a cold blue frame reads
      // wrong against cedar.
      const fr = 0.05;
      out.trim.boxRotY([cx, y, cz], [cw + fr, 0.045, cd + fr], rot);
      const ca = Math.cos(rot), sa = Math.sin(rot);
      for (const [ox, oz] of [[-cw / 2 + 0.12, -cd / 2 + 0.1], [cw / 2 - 0.12, cd / 2 - 0.1]]) {
        const px = cx + ox * ca - oz * sa;
        const pz = cz + ox * sa + oz * ca;
        out.metal.tube([px, y + 0.05, pz], [px, local, pz], 0.008, 5, false);
      }
    }
  }

  // ---- fittings ----------------------------------------------------------
  const lampY = clamp(eaves * 0.58, 1.4, 5.0);
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
      // A shade: wide, shallow, standing off the wall, open top and bottom.
      const halfW = 0.22, halfH = 0.15, depth = 0.11;
      const lo = [p[0] - halfW, p[1] - halfH, p[2] - halfW];
      const hi = [p[0] + halfW, p[1] + halfH, p[2] + halfW];
      if (wall.push[0] !== 0) {
        lo[0] = p[0] - (wall.push[0] > 0 ? 0.01 : depth);
        hi[0] = p[0] + (wall.push[0] > 0 ? depth : 0.01);
      } else {
        lo[2] = p[2] - (wall.push[2] > 0 ? 0.01 : depth);
        hi[2] = p[2] + (wall.push[2] > 0 ? depth : 0.01);
      }
      out.glow.box(lo, hi);
      out.trim.box(
        [lo[0] - 0.012, lo[1] - 0.03, lo[2] - 0.012],
        [hi[0] + 0.012, lo[1], hi[2] + 0.012]);
      // Two sources, just clear of the shade top and bottom and close in to
      // the wall, which is what gives a sconce its pair of pools.
      const range = clamp(Math.max(w, d, h) * 0.4, 3, 18);
      for (const dy of [halfH + 0.06, -halfH - 0.06]) {
        lights.push({
          pos: [p[0] + wall.push[0] * 0.16, p[1] + dy, p[2] + wall.push[2] * 0.16],
          colour: [1.0, 0.84, 0.63],
          range,
          power: 0.62,
        });
      }
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

  // The control room on the other side of the glass.
  if (win) {
    buildControlRoom(out, lights, win, w);
    // Reveal round the opening, and the pane itself.
    const j = 0.1;
    out.trim.box([win.x0 - j, win.y0 - j, -0.02], [win.x1 + j, win.y0, j]);
    out.trim.box([win.x0 - j, win.y1, -0.02], [win.x1 + j, win.y1 + j, j]);
    out.trim.box([win.x0 - j, win.y0, -0.02], [win.x0, win.y1, j]);
    out.trim.box([win.x1, win.y0, -0.02], [win.x1 + j, win.y1, j]);
    out.glass.quad([win.x0, win.y0, 0.012], [win.x1, win.y0, 0.012],
                   [win.x1, win.y1, 0.012], [win.x0, win.y1, 0.012]);
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

/** Where the control-room window sits, or null for a room that has none. */
function windowOpening(preset, w, h) {
  if (preset.id !== 'studio' && preset.id !== 'theater') return null;
  const cw = clamp(w * 0.26, 1.3, 2.9);
  const cy = clamp(h * 0.46, 1.1, 1.75);
  return { x0: w / 2 - cw / 2, x1: w / 2 + cw / 2, y0: cy - 0.48, y1: cy + 0.48 };
}

/**
 * A room behind the glass, built inside-out so you see its inner faces through
 * the opening: back wall, desk, a pair of monitors and a lamp of its own.
 * Entirely decoration -- the model's walls stop at the studio side.
 */
function buildControlRoom(out, lights, win, w) {
  const cx = (win.x0 + win.x1) / 2;
  const halfW = Math.max(2.2, (win.x1 - win.x0) * 0.95);
  const back = -3.1;
  const top = win.y1 + 0.75;
  const x0 = cx - halfW, x1 = cx + halfW;

  // Faces wound to be seen from the studio side.
  out.booth.quad([x0, 0, back], [x1, 0, back], [x1, top, back], [x0, top, back]);
  out.booth.quad([x0, 0, back], [x0, 0, -0.05], [x0, top, -0.05], [x0, top, back]);
  out.booth.quad([x1, 0, -0.05], [x1, 0, back], [x1, top, back], [x1, top, -0.05]);
  out.booth.quad([x0, 0, back], [x0, 0, -0.05], [x1, 0, -0.05], [x1, 0, back]);
  out.booth.quad([x0, top, -0.05], [x0, top, back], [x1, top, back], [x1, top, -0.05]);

  // Desk under the window, with a pair of screens and nearfields on it.
  const deskY = win.y0 - 0.18;
  const deskZ0 = -1.5, deskZ1 = -0.55;
  out.decor.box([cx - 1.5, deskY, deskZ0], [cx + 1.5, deskY + 0.06, deskZ1]);
  for (const sx of [cx - 1.42, cx + 1.36]) {
    out.decor.box([sx - 0.05, 0, deskZ0 + 0.1], [sx + 0.05, deskY, deskZ0 + 0.2]);
    out.decor.box([sx - 0.05, 0, deskZ1 - 0.2], [sx + 0.05, deskY, deskZ1 - 0.1]);
  }
  for (const mx of [cx - 0.62, cx + 0.62]) {
    out.decor.box([mx - 0.36, deskY + 0.06, deskZ0 + 0.06], [mx + 0.36, deskY + 0.5, deskZ0 + 0.12]);
    out.screens.box([mx - 0.33, deskY + 0.1, deskZ0 + 0.04], [mx + 0.33, deskY + 0.47, deskZ0 + 0.062]);
  }
  for (const sx of [cx - 1.25, cx + 1.25]) {
    out.decor.box([sx - 0.16, deskY + 0.06, deskZ0 + 0.05], [sx + 0.16, deskY + 0.48, deskZ0 + 0.3]);
  }

  // Its own light, so the booth reads as lit rather than as a painted panel.
  lights.push({ pos: [cx - 1.1, top - 0.3, back + 1.2], colour: [1.0, 0.9, 0.76], range: 6.5, power: 1.5 });
  lights.push({ pos: [cx + 1.2, top - 0.3, back + 1.2], colour: [1.0, 0.9, 0.76], range: 6.5, power: 1.1 });
  lights.push({ pos: [cx, deskY + 0.55, deskZ0 + 0.5], colour: [0.62, 0.76, 1.0], range: 2.6, power: 0.8 });
  void w;
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
