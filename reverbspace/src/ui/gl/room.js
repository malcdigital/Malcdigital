// Turns the room state into geometry batches and lights.
//
// Everything acoustic -- the six surfaces, the wall panels, the ceiling clouds,
// the seating -- is built from the same numbers the model uses. Everything else
// is marked `decor: true`, and the interface says so, because a stool absorbs
// sound in life and does not in here.

import { MeshBuilder } from './mesh.js';
import { MATERIALS, TREATMENTS } from '../../core/materials.js';
import { PRESETS_BY_ID } from '../../core/presets.js';
import { fittings, sconcesPer } from '../../core/fittings.js';
import { treatmentZones, wallAxes, cornerChord } from '../../core/treatment.js';

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
    drape: new MeshBuilder(),
    foam: new MeshBuilder(),
    diffuser: new MeshBuilder(),
    rug: new MeshBuilder(),
    propDark: new MeshBuilder(),
    cloth: new MeshBuilder(),
    paper: new MeshBuilder(),
    door: new MeshBuilder(),
    shade: new MeshBuilder(),
    shadeSoft: new MeshBuilder(),
    decor: new MeshBuilder(),
  };
  const lights = [];

  // ---- the surfaces the model actually uses ------------------------------
  // A gable rises `rise` above the mean height and the eaves drop as far
  // below, so the volume matches the flat ceiling the decay is computed from.
  // Every fitting comes from the same place the treatment planner reads, so a
  // panel can be kept off the window without the two disagreeing about where
  // the window is.
  const { rise, eaves, ridge, win, doorZ, doorH, patchZ, hookY, lampY } = fittings(state);

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

  // Pendants. These were bare point lights with no fixture at all -- light
  // arriving from nothing, which is the least convincing thing a room can do.
  // Now they hang, and they are what actually lights the place.
  const cols = clamp(Math.round(w / 3.1), 1, 3);
  const rows = clamp(Math.round(d / 2.7), 1, 4);
  const hangY = clamp(Math.min(eaves - 0.5, h * 0.72), 1.95, 4.2);
  const pendants = [];
  for (let i = 0; i < cols; i++) {
    for (let j = 0; j < rows; j++) {
      const px = ((i + 0.5) / cols) * w;
      const pz = ((j + 0.5) / rows) * d;
      // Follow the roof line, so every shade still hangs level.
      const local = rise > 0.01 ? eaves + (1 - Math.abs(px - w / 2) / (w / 2)) * rise * 2 : h;
      if (hangY > local - 0.35) continue;
      const shadeTop = hangY + 0.24;
      const rTop = 0.055, rMouth = 0.21;

      out.metal.box([px - 0.05, local - 0.03, pz - 0.05], [px + 0.05, local, pz + 0.05]);
      out.metal.tube([px, local - 0.02, pz], [px, shadeTop, pz], 0.006, 5, false);
      out.shade.frustum([px, shadeTop, pz], [px, hangY, pz], rTop, rMouth, 20, true, false);
      // The inside of the shade and the lamp itself, both lit.
      out.glow.disc([px, hangY + 0.012, pz], rMouth * 0.94, [0, -1, 0]);
      out.glow.frustum([px, hangY + 0.13, pz], [px, hangY + 0.04, pz], 0.028, 0.045, 10, true, true);
      pendants.push([px, pz]);

      lights.push({
        pos: [px, hangY - 0.06, pz],
        colour: [1.0, 0.88, 0.72],
        range: clamp(Math.max(w, d) * 0.7, 5, 34),
        power: 1.3,
        // The shade is opaque, so this throws down and not up. It is what
        // leaves the top of the wall dark and puts a cone in the air.
        dir: [0, -1, 0],
        cone: [Math.cos(1.36), Math.cos(0.87)],
      });
      // A little spill upward. Every pendant marks the ceiling above it, and
      // without that the shade floats against a flat surface.
      lights.push({
        pos: [px, shadeTop + 0.18, pz],
        colour: [1.0, 0.88, 0.74],
        range: clamp(Math.max(w, d) * 0.3, 1.6, 6),
        power: 0.5,
      });
    }
  }

  // ---- treatment ---------------------------------------------------------
  // Where it goes is decided in core/treatment.js, which the model measures the
  // same rectangles out of. Here they only get rendered -- in the style of
  // whatever the material is, because a drape, a wedge tile, a diffuser and a
  // fabric panel are four different objects and should not all be a rectangle.
  const kind = state.treatment.type;
  const plan = treatmentZones(state);
  const walls = wallAxes(w, d);
  const railY = Math.min(eaves - 0.12, h * 0.94);

  walls.forEach((wall, i) => {
    for (const r of plan.zones[i]) {
      if (kind === 'drapes') {
        out.drape.curtain(wall.from(r.u0), wall.from(r.u1), 0.008, r.v1, wall.n,
                          { depth: 0.16, period: 0.32, seed: wall.id * 2.7 + r.u0 });
        const a = wall.at(r.u0, r.v1 + 0.06), b = wall.at(r.u1, r.v1 + 0.06);
        out.metal.tube([a[0] + wall.n[0] * 0.09, a[1], a[2] + wall.n[2] * 0.09],
                       [b[0] + wall.n[0] * 0.09, b[1], b[2] + wall.n[2] * 0.09], 0.018, 8);
      } else if (kind === 'foam') {
        tileWedges(out, wall, r);
      } else if (kind === 'diffusion') {
        skyline(out, wall, r);
      } else {
        fabricPanel(out, wall, r);
      }
    }
  });

  // Bass traps straddling the vertical corners.
  if (plan.corners) {
    const r0 = cornerChord(state);
    const top = Math.min(eaves - 0.05, h);
    for (const [cx, cz, sx, sz] of [[0, 0, 1, 1], [w, 0, -1, 1], [w, d, -1, -1], [0, d, 1, -1]]) {
      const a = [cx + sx * r0, 0.02, cz];
      const b = [cx, 0.02, cz + sz * r0];
      const at2 = [cx + sx * r0, top, cz];
      const bt = [cx, top, cz + sz * r0];
      const mesh = kind === 'drapes' ? out.drape : out.panels;
      mesh.quad(a, b, bt, at2);
      mesh.tri(at2, bt, [cx, top, cz]);
    }
  }

  // Clouds overhead, laid on a grid rather than scattered: they hang off the
  // same joists in life, and a random spread never looked hung, only dropped.
  if (plan.cloud > 0) {
    const cw = clamp(Math.min(w, d) * 0.19, 0.9, 2.6);
    const cd = cw * 0.62;
    const cols = clamp(Math.round((w * plan.cloud * 1.6) / cw), 1, 4);
    const rows = clamp(Math.round((d * plan.cloud * 1.6) / (cd * 1.7)), 1, 4);
    for (let cI = 0; cI < cols; cI++) {
      for (let rI = 0; rI < rows; rI++) {
        const cx = ((cI + 0.5) / cols) * w;
        const cz = ((rI + 0.5) / rows) * d;
        if (pendants.some(([px, pz]) => Math.hypot(px - cx, pz - cz) < cw * 0.72)) continue;
        const local = rise > 0.01 ? eaves + (1 - Math.abs(cx - w / 2) / (w / 2)) * rise * 2 : h;
        const drop = clamp(h * 0.14, 0.18, 0.9);
        const y = local - drop - 0.05;
        if (y < state.source.height + 0.35) continue;
        out.panels.box([cx - cw / 2, y, cz - cd / 2], [cx + cw / 2, y + 0.1, cz + cd / 2]);
        out.trim.box([cx - cw / 2 - 0.025, y - 0.022, cz - cd / 2 - 0.025],
                     [cx + cw / 2 + 0.025, y + 0.023, cz + cd / 2 + 0.025]);
        for (const [ox, oz] of [[-cw / 2 + 0.12, -cd / 2 + 0.1], [cw / 2 - 0.12, cd / 2 - 0.1]]) {
          out.metal.tube([cx + ox, y + 0.05, cz + oz], [cx + ox, local, cz + oz], 0.008, 5, false);
        }
      }
    }
  }

  // ---- fittings ----------------------------------------------------------
  const along = [
    { len: w, at: (u) => [u, lampY, 0.08], push: [0, 0, 1] },
    { len: w, at: (u) => [u, lampY, d - 0.08], push: [0, 0, -1] },
    { len: d, at: (u) => [0.08, lampY, u], push: [1, 0, 0] },
    { len: d, at: (u) => [w - 0.08, lampY, u], push: [-1, 0, 0] },
  ];
  for (const wall of along) {
    const n = sconcesPer(wall.len);
    for (let i = 0; i < n; i++) {
      const p = wall.at(((i + 0.5) / n) * wall.len);
      // An upright fabric shade on a bracket, open top and bottom -- the shade
      // itself glows, which is what a lit lampshade does and what a dark cone
      // stuck to the wall conspicuously does not.
      const back = [p[0], p[1], p[2]];
      const out1 = [p[0] + wall.push[0] * 0.16, p[1], p[2] + wall.push[2] * 0.16];
      const lo = [out1[0], p[1] - 0.17, out1[2]];
      const hi = [out1[0], p[1] + 0.17, out1[2]];
      out.shadeSoft.frustum(lo, hi, 0.135, 0.115, 16, false, false);
      out.metal.tube(back, out1, 0.013, 6);
      out.metal.box([back[0] - 0.055, p[1] - 0.075, back[2] - 0.055],
                    [back[0] + 0.055, p[1] + 0.075, back[2] + 0.055]);
      out.glow.disc([out1[0], p[1] + 0.168, out1[2]], 0.105, [0, 1, 0]);
      out.glow.disc([out1[0], p[1] - 0.168, out1[2]], 0.125, [0, -1, 0]);
      // Two sources, just clear of the shade top and bottom and close in to
      // the wall, which is what gives a sconce its pair of pools.
      const range = clamp(Math.max(w, d, h) * 0.34, 2.6, 14);
      for (const dy of [0.2, -0.2]) {
        lights.push({
          pos: [p[0] + wall.push[0] * 0.13, p[1] + dy, p[2] + wall.push[2] * 0.13],
          colour: [1.0, 0.84, 0.63],
          range,
          power: 0.42,
        });
      }
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


  // Left ajar, with daylight from the corridor coming past it. A room lit
  // entirely by tungsten has nothing for the warmth to read against.
  out.door.box([0.02, 0, doorZ - 0.45], [0.08, doorH, doorZ + 0.28]);
  out.glow.box([0.005, 0.004, doorZ + 0.3], [0.02, doorH - 0.02, doorZ + 0.45]);
  lights.push({
    pos: [0.42, doorH * 0.62, doorZ + 0.42],
    colour: [0.56, 0.68, 1.0],
    range: clamp(Math.max(w, d) * 0.42, 2.4, 9),
    power: 0.95,
  });
  out.metal.tube([0.09, doorH * 0.5, doorZ + 0.3], [0.16, doorH * 0.5, doorZ + 0.3], 0.018, 6);
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
  // Kept to the left-hand wall: the piano lives against the right one, and a
  // second forest of chrome poles growing through it looked like a mistake.
  const stands = clamp(Math.round(d / 1.5), 2, 5);
  for (let i = 0; i < stands; i++) {
    const bz = clamp(patchZ + 0.55 + i * 0.28, 0.4, Math.max(0.6, d - 1.7));
    const bx = 0.42;
    out.decor.tube([bx, 0.02, bz], [bx + 0.12 + (i % 2) * 0.04, 1.42 + (i % 3) * 0.13, bz - 0.1], 0.015, 6);
    out.decor.box([bx - 0.14, 0, bz - 0.15], [bx + 0.15, 0.025, bz + 0.15]);
  }
  if (h > 2.2 && w > 3) {
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
  // A rug under the working area, and outlet plates at skirting height.
  if (w > 3 && d > 3) {
    const rw = clamp(w * 0.42, 1.4, 3.6), rd = clamp(d * 0.4, 1.2, 3.2);
    out.rug.box([w / 2 - rw / 2, 0.004, d * 0.55 - rd / 2],
                [w / 2 + rw / 2, 0.016, d * 0.55 + rd / 2]);
  }
  const plateY = clamp(skirt + 0.16, 0.2, 0.5);
  for (const [px, pz, nx, nz] of [[w * 0.3, 0, 0, 1], [w * 0.72, 0, 0, 1],
                                  [0, d * 0.6, 1, 0], [w, d * 0.42, -1, 0]]) {
    const halfA = 0.11, halfB = 0.07;
    const lo = [px - (nz ? halfA : 0.008), plateY - halfB, pz - (nx ? halfA : 0.008)];
    const hi = [px + (nz ? halfA : 0.02), plateY + halfB, pz + (nx ? halfA : 0.02)];
    if (nz) { lo[2] = pz - 0.005; hi[2] = pz + 0.022 * nz; }
    if (nx) { lo[0] = px - 0.005 + (nx < 0 ? -0.022 : 0); hi[0] = px + (nx > 0 ? 0.022 : 0.005); }
    out.decor.box(lo, hi);
  }
  // A patch panel by the door.
  const panelZ = patchZ;
  out.decor.box([0.01, 0.9, panelZ - 0.3], [0.07, 1.55, panelZ + 0.3]);
  for (let u = 0; u < 4; u++) {
    out.decor.box([0.07, 1.0 + u * 0.13, panelZ - 0.26], [0.09, 1.08 + u * 0.13, panelZ + 0.26]);
  }

  buildProps(out, preset, w, d, h);

  // The stool goes in the far right corner -- the far left one has the amp.
  const sx = w - 0.8, sz = d - 0.8;
  out.decor.box([sx - 0.19, 0.56, sz - 0.19], [sx + 0.19, 0.62, sz + 0.19]);
  for (const [ox, oz] of [[-0.14, -0.14], [0.14, -0.14], [0.14, 0.14], [-0.14, 0.14]]) {
    out.decor.tube([sx + ox, 0, sz + oz], [sx + ox * 0.75, 0.56, sz + oz * 0.75], 0.012, 5);
  }

  return { batches: out, lights };
}

/** A fabric-wrapped absorber: the panel, in one of the two fabrics. */
function fabricPanel(out, wall, r) {
  const thick = 0.07;
  const a = wall.at(r.u0, r.v0), b = wall.at(r.u1, r.v1);
  const lo = [Math.min(a[0], b[0]), r.v0, Math.min(a[2], b[2])];
  const hi = [Math.max(a[0], b[0]), r.v1, Math.max(a[2], b[2])];
  if (wall.n[0] !== 0) { lo[0] -= thick * (wall.n[0] > 0 ? 0 : 1); hi[0] += thick * (wall.n[0] > 0 ? 1 : 0); }
  else { lo[2] -= thick * (wall.n[2] > 0 ? 0 : 1); hi[2] += thick * (wall.n[2] > 0 ? 1 : 0); }
  // Every so often the second fabric, which is what stops a treated wall
  // reading as one enormous cushion.
  const alt = hash(wall.id * 31 + Math.round(r.u0 * 7), Math.round(r.v0 * 11)) < 0.34;
  (alt ? out.panelsAlt : out.panels).box(lo, hi);
}

/** Wedge foam, tiled across the rectangle it was given. */
function tileWedges(out, wall, r) {
  const tile = 0.3;
  const cols = Math.max(1, Math.floor((r.u1 - r.u0) / tile));
  const rows = Math.max(1, Math.floor((r.v1 - r.v0) / tile));
  const u0 = r.u0 + ((r.u1 - r.u0) - cols * tile) / 2;
  const v0 = r.v0 + ((r.v1 - r.v0) - rows * tile) / 2;
  const axis = wall.n[0] !== 0 ? 0 : 2;
  const sign = wall.n[0] + wall.n[2];
  for (let c = 0; c < cols; c++) {
    for (let q = 0; q < rows; q++) {
      const centre = wall.at(u0 + (c + 0.5) * tile, v0 + (q + 0.5) * tile);
      centre[axis] += sign * 0.02;
      out.foam.wedge(centre, tile * 0.98, 0.055, axis, sign);
    }
  }
}

/** A skyline diffuser: a grid of wells, each a different depth. */
function skyline(out, wall, r) {
  const cell = 0.17;
  const cols = Math.max(2, Math.floor((r.u1 - r.u0) / cell));
  const rows = Math.max(2, Math.floor((r.v1 - r.v0) / cell));
  const u0 = r.u0 + ((r.u1 - r.u0) - cols * cell) / 2;
  const v0 = r.v0 + ((r.v1 - r.v0) - rows * cell) / 2;
  for (let c = 0; c < cols; c++) {
    for (let q = 0; q < rows; q++) {
      const u = u0 + (c + 0.5) * cell, v = v0 + (q + 0.5) * cell;
      const depth = 0.03 + hash(wall.id * 91 + c + Math.round(r.u0 * 5), q) * 0.16;
      const a = wall.at(u - cell * 0.46, v - cell * 0.46);
      const b = wall.at(u + cell * 0.46, v + cell * 0.46);
      const lo = [Math.min(a[0], b[0]), v - cell * 0.46, Math.min(a[2], b[2])];
      const hi = [Math.max(a[0], b[0]), v + cell * 0.46, Math.max(a[2], b[2])];
      if (wall.n[0] !== 0) {
        if (wall.n[0] > 0) hi[0] = lo[0] + depth; else lo[0] = hi[0] - depth;
      } else if (wall.n[2] > 0) hi[2] = lo[2] + depth; else lo[2] = hi[2] - depth;
      out.diffuser.box(lo, hi);
    }
  }
}

/**
 * The things that make a room look worked in rather than rendered: an electric
 * piano along one wall, an amp in the corner, a guitar on its stand, a music
 * stand out in the floor and headphones on a hook.
 *
 * Every one of these is decoration. They would all absorb sound in life -- a
 * speaker cabinet is a bass trap with a handle -- and none of them does here.
 */
function buildProps(out, preset, w, d, h) {
  // A guitar amp in a cathedral is a joke, not a detail. These belong to the
  // studio, and to a studio with room for them.
  if (preset.id !== 'studio' || w < 3.4 || d < 3) return;

  // --- electric piano, along the right-hand wall --------------------------
  const px = w - 0.44, pz = clamp(d * 0.36, 0.9, d - 1.2);
  const bodyY = 0.72, bodyLen = clamp(Math.min(1.35, d * 0.32), 0.9, 1.35);
  out.propDark.box([px - 0.24, bodyY, pz - bodyLen / 2], [px + 0.2, bodyY + 0.14, pz + bodyLen / 2]);

  // A keyboard is the one thing here everyone can name on sight, so it is
  // worth the geometry: a white bed, then the sharps in their 2-3 pattern.
  const kz0 = pz - bodyLen / 2 + 0.055, kz1 = pz + bodyLen / 2 - 0.055;
  const whites = Math.max(14, Math.round((kz1 - kz0) / 0.0232));
  const kw = (kz1 - kz0) / whites;
  out.paper.box([px - 0.155, bodyY + 0.14, kz0], [px + 0.02, bodyY + 0.158, kz1]);
  for (let i = 0; i < whites - 1; i++) {
    const step = i % 7;
    if (step === 2 || step === 6) continue;      // no sharp between E-F or B-C
    const z = kz0 + (i + 1) * kw;
    out.propDark.box([px - 0.155, bodyY + 0.158, z - kw * 0.28],
                     [px - 0.056, bodyY + 0.171, z + kw * 0.28]);
  }
  // Fall behind the keys, with a control strip and a power lamp on it.
  out.propDark.box([px + 0.02, bodyY + 0.14, pz - bodyLen / 2 + 0.04],
                   [px + 0.2, bodyY + 0.21, pz + bodyLen / 2 - 0.04]);
  for (let i = 0; i < 4; i++) {
    const z = pz - 0.24 + i * 0.16;
    out.metal.tube([px + 0.09, bodyY + 0.21, z], [px + 0.09, bodyY + 0.235, z], 0.014, 8);
  }
  out.glow.box([px + 0.05, bodyY + 0.212, pz - 0.4], [px + 0.09, bodyY + 0.218, pz - 0.36]);

  // An X-frame stand under it: four spindles read as scaffolding, two crossed
  // tubes per end read as the thing you actually carry to gigs.
  for (const oz of [-bodyLen / 2 + 0.16, bodyLen / 2 - 0.16]) {
    out.metal.tube([px - 0.3, 0.012, pz + oz], [px + 0.1, bodyY, pz + oz], 0.023, 8);
    out.metal.tube([px + 0.14, 0.012, pz + oz], [px - 0.22, bodyY, pz + oz], 0.023, 8);
  }
  out.metal.tube([px - 0.06, bodyY * 0.5, pz - bodyLen / 2 + 0.16],
                 [px - 0.06, bodyY * 0.5, pz + bodyLen / 2 - 0.16], 0.018, 6);

  // --- amp cabinet, in the far corner -------------------------------------
  const ax = 0.62, az = d - 0.62;
  out.propDark.box([ax - 0.3, 0.05, az - 0.24], [ax + 0.3, 0.78, az + 0.22]);
  // Grille cloth, recessed behind the baffle, in a weave rather than the
  // cabinet's own near-black: a grille you cannot see is just a crate.
  out.cloth.box([ax - 0.24, 0.16, az - 0.252], [ax + 0.24, 0.58, az - 0.238]);
  // Control panel along the top of the front, four knobs and a pilot lamp.
  out.propDark.box([ax - 0.28, 0.63, az - 0.26], [ax + 0.28, 0.74, az - 0.235]);
  for (let i = 0; i < 4; i++) {
    const kx = ax - 0.13 + i * 0.087;
    out.metal.tube([kx, 0.685, az - 0.26], [kx, 0.685, az - 0.285], 0.016, 8);
  }
  out.glow.box([ax + 0.21, 0.665, az - 0.268], [ax + 0.25, 0.705, az - 0.262]);
  // Strap handle on top, and rubber feet.
  out.propDark.arcTube([ax, 0.78, az], 0.1, 0.15, Math.PI - 0.15, 0.014, 'xy', 10);
  for (const ox of [-0.24, 0.24]) {
    for (const oz of [-0.16, 0.16]) {
      out.metal.tube([ax + ox, 0.05, az + oz], [ax + ox, 0.0, az + oz], 0.022, 5);
    }
  }

  // --- guitar on its stand ------------------------------------------------
  // Built in the plane it leans in: two bouts and a waist for the body, then
  // neck, fretboard and head straight up that same axis. A guitar is all
  // silhouette, so the outline has to be right before anything else matters.
  const gx = clamp(px - 0.78, 1, w - 1), gz = clamp(pz + bodyLen / 2 + 0.6, 0.7, d - 0.7);
  const lean = 0.2;
  const up = [Math.sin(lean), Math.cos(lean), 0];
  const right = [0, 0, 1];
  const fwd = [-Math.cos(lean), Math.sin(lean), 0];   // out of the soundboard
  const at = (u, f = 0) => [gx + up[0] * u + fwd[0] * f, 0.24 + up[1] * u + fwd[1] * f,
                            gz + up[2] * u + fwd[2] * f];
  const slab = (u, f, halfDepth, r, sides) =>
    out.trim.tube(at(u, f - halfDepth), at(u, f + halfDepth), r, sides);
  slab(0.06, 0, 0.043, 0.175, 18);                    // lower bout
  slab(0.34, 0, 0.04, 0.135, 16);                     // upper bout
  out.trim.orientedBox(at(0.2), right, up, [0.2, 0.3, 0.083]);   // waist
  out.propDark.tube(at(0.24, 0.038), at(0.24, 0.05), 0.048, 14); // soundhole
  out.propDark.orientedBox(at(0.0, 0.048), right, up, [0.14, 0.022, 0.014]);  // bridge
  out.trim.tube(at(0.44, 0.012), at(0.95, 0.012), 0.019, 10);    // neck
  out.propDark.orientedBox(at(0.7, 0.03), right, up, [0.056, 0.45, 0.009]);   // fretboard
  out.propDark.orientedBox(at(1.02, 0.014), right, up, [0.076, 0.15, 0.015]); // head
  // The A-frame under it.
  for (const s2 of [-1, 1]) {
    out.metal.tube([gx - 0.17, 0.012, gz + s2 * 0.2], [gx + 0.03, 0.3, gz + s2 * 0.05], 0.013, 6);
    out.metal.tube([gx + 0.25, 0.012, gz + s2 * 0.2], [gx + 0.03, 0.3, gz + s2 * 0.05], 0.013, 6);
  }
  out.metal.tube([gx + 0.03, 0.28, gz - 0.11], [gx + 0.03, 0.28, gz + 0.11], 0.012, 6);

  // --- music stand --------------------------------------------------------
  const mx = clamp(w * 0.34, 0.8, w - 0.8), mz = clamp(d * 0.66, 0.8, d - 0.8);
  const deskY = 1.06;
  for (let i = 0; i < 3; i++) {
    const a = (i / 3) * Math.PI * 2 + 0.4;
    out.metal.tube([mx, 0.09, mz], [mx + Math.sin(a) * 0.26, 0.012, mz + Math.cos(a) * 0.26], 0.011, 5);
  }
  out.metal.tube([mx, 0.06, mz], [mx, deskY - 0.02, mz], 0.014, 8);
  // Desk tipped back off vertical, with a lip along the bottom.
  const tilt = 0.34;
  const deskUp = [0, Math.cos(tilt), -Math.sin(tilt)];
  out.propDark.orientedBox([mx, deskY + 0.12, mz + 0.04], [1, 0, 0], deskUp, [0.48, 0.3, 0.012]);
  out.propDark.orientedBox([mx, deskY - 0.02, mz + 0.09], [1, 0, 0], deskUp, [0.48, 0.03, 0.03]);
  // Sheet music, sitting on the lip and leaning on the desk.
  out.paper.orientedBox([mx - 0.01, deskY + 0.15, mz + 0.028], [1, 0, 0], deskUp, [0.42, 0.29, 0.004]);

  // --- headphones, hooked on the far wall ---------------------------------
  if (h > 2.2) {
    const hx = w - 0.02, hy = clamp(h * 0.46, 1.2, 1.9), hz = clamp(d * 0.72, 0.6, d - 0.6);
    out.metal.tube([hx, hy, hz], [hx - 0.09, hy + 0.01, hz], 0.011, 5);
    const bandR = 0.105;
    out.propDark.arcTube([hx - 0.09, hy - 0.02, hz], bandR, Math.PI * 0.08, Math.PI * 0.92,
                         0.012, 'zy', 14);
    for (const s2 of [-1, 1]) {
      const cz = hz + Math.cos(s2 > 0 ? Math.PI * 0.08 : Math.PI * 0.92) * bandR;
      const cy = hy - 0.02 + Math.sin(Math.PI * 0.08) * bandR;
      out.cloth.frustum([hx - 0.045, cy - 0.03, cz], [hx - 0.115, cy - 0.03, cz],
                        0.045, 0.052, 14, true, true);
    }
  }
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

  // An engineer's chair, and a rack of outboard against the side wall.
  const chairZ = deskZ1 + 0.62;
  out.decor.box([cx - 0.26, 0.42, chairZ - 0.26], [cx + 0.26, 0.48, chairZ + 0.26]);
  out.decor.box([cx - 0.26, 0.48, chairZ + 0.18], [cx + 0.26, 0.94, chairZ + 0.26]);
  out.decor.tube([cx, 0.04, chairZ], [cx, 0.42, chairZ], 0.035, 8);
  for (let i = 0; i < 5; i++) {
    const a = (i / 5) * Math.PI * 2;
    out.decor.tube([cx, 0.05, chairZ], [cx + Math.sin(a) * 0.26, 0.03, chairZ + Math.cos(a) * 0.26], 0.02, 5);
  }
  const rackX = x0 + 0.42;
  out.decor.box([rackX - 0.3, 0, back + 0.5], [rackX + 0.3, 1.3, back + 1.05]);
  for (let u = 0; u < 7; u++) {
    out.decor.box([rackX - 0.27, 0.14 + u * 0.16, back + 0.46],
                  [rackX + 0.27, 0.26 + u * 0.16, back + 0.5]);
  }

  // Its own light, so the booth reads as lit rather than as a painted panel.
  lights.push({ pos: [cx - 1.1, top - 0.3, back + 1.2], colour: [1.0, 0.9, 0.76], range: 6.5, power: 1.5 });
  lights.push({ pos: [cx + 1.2, top - 0.3, back + 1.2], colour: [1.0, 0.9, 0.76], range: 6.5, power: 1.1 });
  lights.push({ pos: [cx, deskY + 0.55, deskZ0 + 0.5], colour: [0.62, 0.76, 1.0], range: 2.6, power: 0.8 });
  void w;
}

/*
 * The microphones, each built as the thing it actually is.
 *
 * Dimensions are the real ones, from the manufacturers' own sheets: a U 87 is
 * 56 mm across and 200 mm long, a KM 184 is 22 mm by 107, an SM7B 63.5 by 189,
 * an R-121 25 by 156, an MKH 416 19 by 250. At a metre away that difference is
 * most of what you have to go on, and it is worth getting right -- the mic you
 * pick already changes what you hear, and it should change what you see.
 *
 * The mounting matters as much as the body. Half of recognising a mic across a
 * room is how it is hanging: a large condenser sits nose-out in a spider, an
 * SM7B is slung in a yoke, a pencil sits in a clip pointing the way it hears.
 */

/** Where each model's capsule sits, so the acoustics and the picture agree. */
const MIC_BODIES = {
  // Neumann U 87: tapered body, squared-off mesh basket, hung in a spider and
  // facing sideways out of it. 56 x 200 mm.
  ldc: (out, at, aim) => {
    // Basket: a wire drum with a domed crown, banded top and bottom. Two
    // layers, because a U 87's headgrille is two layers and you can see it.
    for (let i = 0; i < 2; i++) {
      const r = 0.028 - i * 0.002;
      out.grille.tube(at(0, 0.052 + i * 0.002, 0), at(0, 0.114 - i * 0.003, 0), r, 18, false);
    }
    out.grille.frustum(at(0, 0.114, 0), at(0, 0.126, 0), 0.028, 0.019, 18, false, true);
    for (const v of [0.056, 0.084, 0.112]) {
      ringAround(out.body, at(0, v, 0), [0, 1, 0], 0.0284, 0.0016, 18);
    }
    out.body.tube(at(0, 0.044, 0), at(0, 0.054, 0), 0.0286, 18);         // collar
    out.body.frustum(at(0, 0.046, 0), at(0, -0.078, 0), 0.026, 0.023, 16, false, true);
    // Pattern switch on the front, pad and roll-off on the back.
    out.dark.orientedBox(at(0, 0.03, 0.021), [1, 0, 0], [0, 1, 0], [0.016, 0.012, 0.004]);
    out.dark.orientedBox(at(0, -0.02, -0.02), [1, 0, 0], [0, 1, 0], [0.02, 0.016, 0.004]);
    spider(out, at, 0.03, 0.078);
    return { cable: at(0, -0.078, 0), aimAt: at(0, 0.084, 0.028), boom: at(0, -0.078, -0.029), aim };
  },

  // Neumann KM 184: a plain slim cylinder that points at what it is hearing.
  // 22 x 107 mm, so it is a third the diameter of the U 87 and half as long.
  sdc: (out, at, aim) => {
    pencil(out, at(0, 0, -0.054), at(0, 0, 0.053));
    clip(out, at(0, 0, -0.03), at(0, 0, 1), 0.012);
    return { cable: at(0, 0, -0.056), aimAt: at(0, 0, 0.053), boom: at(0, -0.043, -0.03), aim };
  },

  // Shure SM7B: a chunky black barrel lying along its aim, most of the front
  // buried in foam, slung in a yoke that straddles it. 63.5 x 189 mm.
  dynamic: (out, at) => {
    out.dark.tube(at(0, 0, -0.094), at(0, 0, 0.02), 0.032, 18, true);
    out.dark.tube(at(0, 0, -0.098), at(0, 0, -0.09), 0.026, 16, true);   // rear cap
    // Windscreen: a fat foam sleeve, wider than the body it sits on.
    out.foam.tube(at(0, 0, 0.012), at(0, 0, 0.083), 0.038, 20, true);
    out.dark.orientedBox(at(0, 0.031, -0.05), [0, 0, 1], [0, 1, 0], [0.05, 0.006, 0.03]);
    yoke(out, at, 0.034, -0.03);
    return { cable: at(0, 0, -0.1), aimAt: at(0, 0, 0.086), boom: at(0, -0.05, -0.03) };
  },

  // Royer R-121: a slim nickel cylinder standing upright with a band of mesh
  // near the top and the ribbon housing bulging out either side of it -- the
  // "ears" that are the whole of how you know one across a room. 25 x 156 mm.
  ribbon: (out, at, aim) => {
    out.body.tube(at(0, -0.072, 0), at(0, 0.05, 0), 0.0125, 16, true);
    out.grille.tube(at(0, 0.05, 0), at(0, 0.084, 0), 0.013, 16, false);
    for (const s2 of [-1, 1]) {
      out.body.tube(at(s2 * 0.012, 0.067, 0), at(s2 * 0.018, 0.067, 0), 0.011, 12, true);
    }
    out.body.tube(at(0, 0.082, 0), at(0, 0.09, 0), 0.0125, 16, true);
    spider(out, at, 0.02, 0.062);
    return { cable: at(0, -0.072, 0), aimAt: at(0, 0.067, 0.013), boom: at(0, -0.062, -0.024), aim };
  },

  // Sennheiser MKH 416: a long thin tube, the front two thirds of it the
  // interference tube with its slots. 19 x 250 mm, and the length is the point.
  shotgun: (out, at, aim) => {
    out.body.tube(at(0, 0, -0.125), at(0, 0, -0.04), 0.0095, 14, true);
    out.grille.tube(at(0, 0, -0.04), at(0, 0, 0.122), 0.0092, 14, true);
    // The slots down each side, which is what makes it read as an interference
    // tube rather than a length of pipe.
    for (let i = 0; i < 11; i++) {
      const z = -0.028 + i * 0.0132;
      for (const s2 of [-1, 1]) {
        out.dark.orientedBox(at(s2 * 0.0088, 0, z), [0, 0, 1], [0, 1, 0], [0.009, 0.006, 0.003]);
      }
    }
    out.body.tube(at(0, 0, -0.128), at(0, 0, -0.12), 0.0105, 14, true);
    clip(out, at(0, 0, -0.075), at(0, 0, 1), 0.0105);
    return { cable: at(0, 0, -0.131), aimAt: at(0, 0, 0.124), boom: at(0, -0.042, -0.075), aim };
  },

  // Two pencils crossed at ninety degrees with their capsules almost touching,
  // which is the whole trick: one arrival time, two directions.
  xy: (out, at, aim) => {
    // The capsules nearly touch at the front and the bodies splay back and
    // apart at forty-five degrees each. One arrival time, two directions --
    // that near-coincidence is the whole reason the pattern works, so it has
    // to be visible.
    for (const s2 of [-1, 1]) {
      const c = Math.cos(Math.PI / 4), sn = Math.sin(Math.PI / 4);
      const L = 0.107;
      const tip = at(s2 * 0.008, s2 * 0.012, 0.042);
      pencil(out, at(s2 * 0.008 - s2 * sn * L, s2 * 0.012, 0.042 - c * L), tip);
    }
    out.metal.tube(at(-0.055, -0.028, -0.03), at(0.055, -0.028, -0.03), 0.006, 8);
    for (const s2 of [-1, 1]) {
      out.metal.tube(at(s2 * 0.05, -0.028, -0.03), at(s2 * 0.05, -0.012, -0.03), 0.005, 8);
    }
    out.metal.tube(at(0, -0.028, -0.03), at(0, -0.05, -0.03), 0.007, 8);
    return { cable: at(0, -0.02, -0.05), aimAt: at(0, 0, 0.042), boom: at(0, -0.05, -0.03), aim };
  },
};

const vsub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const vlen = (a) => Math.hypot(a[0], a[1], a[2]);
const vnorm = (a) => { const l = vlen(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const vcross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const along = (p, dir, t) => [p[0] + dir[0] * t, p[1] + dir[1] * t, p[2] + dir[2] * t];

/**
 * A ring of tube around an arbitrary axis.
 *
 * MeshBuilder's own ring and arcTube only know the three world planes, which
 * is fine for a lamp but not for a clip round a mic barrel: the barrel points
 * wherever the mic is aimed, and a ring built in world xy only encircles it
 * when the mic happens to be facing down z.
 */
function ringAround(mesh, centre, axis, r, thickness, segments = 16, from = 0, to = Math.PI * 2) {
  const a = vnorm(axis);
  const u = vnorm(vcross(a, Math.abs(a[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0]));
  const v = vcross(a, u);
  const pt = (t) => {
    const ang = from + (to - from) * t;
    const c = Math.cos(ang) * r, s2 = Math.sin(ang) * r;
    return [centre[0] + u[0] * c + v[0] * s2,
            centre[1] + u[1] * c + v[1] * s2,
            centre[2] + u[2] * c + v[2] * s2];
  };
  for (let i = 0; i < segments; i++) mesh.tube(pt(i / segments), pt((i + 1) / segments), thickness, 6, false);
}

/** A pencil condenser between two points: barrel, ring, short mesh cap. */
function pencil(out, tail, tip) {
  const dir = vnorm(vsub(tip, tail));
  const len = vlen(vsub(tip, tail));
  out.body.tube(tail, along(tail, dir, len - 0.023), 0.011, 14, true);
  out.body.tube(along(tail, dir, len - 0.023), along(tail, dir, len - 0.019), 0.0122, 14, false);
  out.grille.tube(along(tail, dir, len - 0.019), tip, 0.0108, 14, true);
}

/** The clip a pencil or a shotgun sits in, and its stub down to the boom. */
function clip(out, centre, axis, r) {
  ringAround(out.metal, centre, axis, r + 0.005, 0.005, 14, 0.5, Math.PI * 2 - 0.5);
  out.metal.tube([centre[0], centre[1] - r - 0.005, centre[2]],
                 [centre[0], centre[1] - r - 0.026, centre[2]], 0.007, 8);
}

/**
 * A spider: an outer ring, elastic lines in to the body, a yoke underneath.
 * It is most of how you know a large condenser from across the room.
 */
function spider(out, at, r, drop) {
  const R = r + 0.028;
  ringAround(out.metal, at(0, 0.02, 0), [0, 1, 0], R, 0.0028, 22);
  // Lines alternate high and low on the body, which is what makes a spider a
  // spider rather than a hoop with spokes.
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2 + 0.39;
    const v = i % 2 ? 0.05 : -0.012;
    out.cable.tube(at(Math.cos(a) * R, 0.02, Math.sin(a) * R),
                   at(Math.cos(a) * r * 0.92, v, Math.sin(a) * r * 0.92), 0.002, 4, false);
  }
  // Two arms down off the ring to the swivel, rather than one stub: it is
  // what stops the ring reading as a plate the mic is standing on.
  for (const s2 of [-1, 1]) {
    out.metal.tube(at(s2 * R * 0.72, 0.02, -R * 0.68), at(0, -drop + 0.012, -R * 0.5), 0.0035, 6);
  }
  out.metal.tube(at(0, -drop + 0.014, -R * 0.5), at(0, -drop, -R * 0.5), 0.006, 8);
}

/** The SM7B's yoke: a bracket straddling the barrel with a thumbscrew a side. */
function yoke(out, at, r, z) {
  for (const s2 of [-1, 1]) {
    out.metal.tube(at(s2 * (r + 0.004), 0, z), at(s2 * (r + 0.004), -0.03, z), 0.005, 8);
    out.metal.tube(at(s2 * (r + 0.004), 0, z), at(s2 * (r + 0.011), 0, z), 0.008, 10);
  }
  out.metal.tube(at(-r - 0.004, -0.03, z), at(r + 0.004, -0.03, z), 0.005, 8);
  out.metal.tube(at(0, -0.03, z), at(0, -0.05, z), 0.008, 10);
}

/**
 * The mic and its stand, rebuilt whenever it moves or the model changes.
 *
 * Everything is laid out in the mic's own frame: +w points at the performer,
 * +u across, +v up. A large condenser and a ribbon stand upright and listen
 * out of their side; a pencil, a dynamic and a shotgun lie along their aim.
 */
export function buildMic(state) {
  const out = {
    body: new MeshBuilder(),
    dark: new MeshBuilder(),
    foam: new MeshBuilder(),
    grille: new MeshBuilder(),
    metal: new MeshBuilder(),
    cable: new MeshBuilder(),
  };
  const m = { x: state.mic.x, y: state.mic.height, z: state.mic.z };
  const az = state.mic.azimuth;
  const fx = Math.sin(az), fz = Math.cos(az);
  const at = (u, v, w) => [m.x + fz * u + fx * w, m.y + v, m.z - fx * u + fz * w];

  const build = MIC_BODIES[state.mic.id] || MIC_BODIES.ldc;
  const rig = build(out, at, az);

  // Stand: tripod, column straight up to just under the mount, and a short
  // link across to it. Stopping the column 280 mm short and reaching up with
  // a boom left a fat pale bar leaning across the shot at nothing.
  const foot = rig.boom;
  const neck = Math.max(0.12, foot[1] - 0.055);
  for (let i = 0; i < 3; i++) {
    const a = az + (i / 3) * Math.PI * 2 + 0.6;
    // Folding legs, thinner than the column they fold under. At 28 mm across
    // one pointing at the camera was the fattest thing in the frame.
    out.metal.tube([m.x, 0.055, m.z], [m.x + Math.sin(a) * 0.32, 0.016, m.z + Math.cos(a) * 0.32], 0.006, 6);
  }
  // A K&M column is 25 mm across and its boom arm is smaller again. At 38 and
  // 26 the rig read as scaffolding and drew the eye off the mic on it.
  out.metal.tube([m.x, 0.04, m.z], [m.x, neck, m.z], 0.0125, 12);
  out.metal.tube([m.x, neck, m.z], foot, 0.009, 8);

  // Cable: out of the base of the mic, down the stand, then a slack run along
  // the floor to the nearest wall.
  const { w, d } = state.dims;
  const tail = rig.cable;
  out.cable.tube(tail, [m.x + 0.015, neck, m.z], 0.0032, 5, false);
  out.cable.tube([m.x + 0.015, neck, m.z], [m.x + 0.03, 0.03, m.z + 0.02], 0.0032, 5, false);
  const toWall = [
    { p: [m.x, 0.012, 0.05], dist: m.z },
    { p: [m.x, 0.012, d - 0.05], dist: d - m.z },
    { p: [0.05, 0.012, m.z], dist: m.x },
    { p: [w - 0.05, 0.012, m.z], dist: w - m.x },
  ].sort((a, b) => a.dist - b.dist)[0];
  let from = [m.x + 0.03, 0.012, m.z + 0.02];
  const steps = 7;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    // A lazy S rather than a taut line, which is how cable actually lies.
    const sway = Math.sin(t * Math.PI) * 0.22;
    const to = [
      lerp(from[0], toWall.p[0], 1 / (steps - i + 1)) + (i < steps ? sway * 0.3 : 0),
      0.012,
      lerp(from[2], toWall.p[2], 1 / (steps - i + 1)) + (i < steps ? sway * 0.3 : 0),
    ];
    const end = i === steps ? toWall.p : to;
    out.cable.tube(from, end, 0.0038, 5, false);
    from = end;
  }
  return out;
}
