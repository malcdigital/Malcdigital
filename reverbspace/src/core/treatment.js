// Where the soundproofing goes, and how much of the room it ends up covering.
//
// This was a percentage slider driving a shuffled list of wall cells: at 37%
// you got thirty-seven percent of the panels in arbitrary places, which is not
// a decision anyone makes about a room. Rooms get treated in stages, and the
// stages have an order -- kill the early reflections, then the wall behind the
// performer, then the corners where the low end piles up, then overhead. Each
// step here is one of those decisions, and each one is placed where it would
// actually go rather than wherever the shuffle put it.
//
// The plan is also the only source of truth for how much is covered. The
// geometry draws exactly these rectangles and the acoustics measure exactly
// these rectangles, so the picture and the sound cannot drift apart -- which
// they previously could, because the drawn panels were cut around windows and
// doors afterwards and the model never heard about it.

import { PRESETS_BY_ID } from './presets.js';
import { fittings, sconcesPer, defaultPlacement } from './fittings.js';

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/**
 * @typedef {Object} Stage
 * @property {string} id
 * @property {string} name    what the control shows
 * @property {string} blurb   what this step actually does to the sound
 */

/** @type {Stage[]} */
export const STAGES = [
  { id: 'bare', name: 'Bare', blurb: 'Nothing on the walls. Every surface is in play.' },
  { id: 'sides', name: 'Side reflections',
    blurb: 'A panel where the first reflection lands on each side wall. It follows you as you move.' },
  { id: 'ends', name: '+ front and back',
    blurb: 'The same again on the end walls. The early field goes, the tail stays.' },
  { id: 'rear', name: '+ rear wall',
    blurb: 'A broad band behind the performer, which is the loudest single reflection you get.' },
  { id: 'traps', name: '+ corner traps',
    blurb: 'The four vertical corners, where the low end piles up and rings longest.' },
  { id: 'cloud', name: '+ ceiling cloud',
    blurb: 'Clouds over the working area. Takes the slap between floor and ceiling out.' },
  { id: 'full', name: 'Wall to wall',
    blurb: 'Bands right around, floor to eaves. As dead as this room gets.' },
];

export const MAX_STAGE = STAGES.length - 1;

/**
 * The four walls in their own coordinates: `u` along the wall, `v` up it.
 * Wall 0 is z = 0 and carries the control-room window; 1 is z = d; 2 is x = 0
 * and carries the door; 3 is x = w.
 */
export function wallAxes(w, d) {
  return [
    { id: 0, len: w, at: (u, v) => [u, v, 0], n: [0, 0, 1], from: (u) => [u, 0, 0.02] },
    { id: 1, len: w, at: (u, v) => [w - u, v, d], n: [0, 0, -1], from: (u) => [w - u, 0, d - 0.02] },
    { id: 2, len: d, at: (u, v) => [0, v, d - u], n: [1, 0, 0], from: (u) => [0.02, 0, d - u] },
    { id: 3, len: d, at: (u, v) => [w, v, u], n: [-1, 0, 0], from: (u) => [w - 0.02, 0, u] },
  ];
}

/**
 * Where the first reflection off each wall lands, in that wall's own `u`.
 *
 * Mirror the source in the wall plane and draw a line to the mic: where it
 * crosses is the one point on that wall that sends a specular reflection
 * straight into the capsule. It is the first thing anyone treats, and it is
 * the reason a panel belongs somewhere in particular rather than anywhere.
 *
 * Worked out for the room's own working position, not for wherever you happen
 * to be standing this second. Panels are screwed to a wall: they are installed
 * once, for the spot the room is set up around. Having them slide about while
 * you drag the mic looked like a rendering fault, and it was not true either.
 * Where the reflection lands *now* is what the ray overlay is for.
 */
export function reflectionPointU(state, wallId) {
  const { w, d } = state.dims;
  const { source: s, mic: m } = defaultPlacement(state);
  // Distance from each of the two points to the wall plane; the crossing
  // splits the run between them in that ratio.
  const split = (ds, dm) => (ds + dm < 1e-6 ? 0.5 : ds / (ds + dm));
  switch (wallId) {
    case 0: return s.x + (m.x - s.x) * split(s.z, m.z);
    case 1: return w - (s.x + (m.x - s.x) * split(d - s.z, d - m.z));
    case 2: return d - (s.z + (m.z - s.z) * split(s.x, m.x));
    default: return s.z + (m.z - s.z) * split(w - s.x, w - m.x);
  }
}

/** Rectangles on each wall that nothing may hang over. */
function reserved(state) {
  const { w, d, h } = state.dims;
  const f = fittings(state);
  const out = [[], [], [], []];
  const pad = 0.13;
  if (f.win) {
    out[0].push({ u0: f.win.x0 - pad, u1: f.win.x1 + pad, v0: f.win.y0 - pad, v1: f.win.y1 + pad });
    if (h > 2.2 && w > 3) {
      out[0].push({ u0: w * 0.04, u1: w * 0.36, v0: f.hookY - 0.62, v1: f.hookY + 0.32 });
    }
  }
  // Door and patch panel are on x = 0, whose along-axis runs back from z = d.
  out[2].push({ u0: d - f.doorZ - 0.7, u1: d - f.doorZ + 0.7, v0: 0, v1: f.doorH + 0.2 });
  out[2].push({ u0: d - f.patchZ - 0.42, u1: d - f.patchZ + 0.42, v0: 0.8, v1: 1.65 });
  // Sconces. Each fitting wall measures along its own axis and the treatment
  // walls do not always agree, so map from one to the other.
  const toWallU = [(a) => a, (a) => w - a, (a) => d - a, (a) => a];
  wallAxes(w, d).forEach((wall, i) => {
    const n = sconcesPer(wall.len);
    for (let k = 0; k < n; k++) {
      const u = toWallU[i](((k + 0.5) / n) * wall.len);
      out[i].push({ u0: u - 0.34, u1: u + 0.34, v0: f.lampY - 0.42, v1: f.lampY + 0.42 });
    }
  });
  return out;
}

/** The clear spans of a wall at a given height, in order along it. */
function freeRuns(rects, len, v0, v1) {
  const crossing = rects
    .filter((r) => v0 < r.v1 && v1 > r.v0)
    .sort((a, b) => a.u0 - b.u0);
  const out = [];
  let at = 0.1;
  for (const c of crossing) {
    if (c.u0 > at) out.push([at, Math.min(c.u0, len - 0.1)]);
    at = Math.max(at, c.u1);
  }
  if (at < len - 0.1) out.push([at, len - 0.1]);
  return out.filter(([a, b]) => b - a > 0.35);
}

/**
 * Put a panel of this width as near as possible to where it should go.
 *
 * The ideal spot is often taken -- the reflection point on this studio's left
 * wall lands squarely on the door -- and a panel that simply vanishes when its
 * spot is occupied leaves a step of the plan doing nothing. An installer slides
 * it to the nearest place it fits, so that is what happens here.
 */
function placeNear(rects, len, uIdeal, width, v0, v1) {
  const runs = freeRuns(rects, len, v0, v1);
  if (!runs.length) return null;
  let best = null;
  for (const [a, b] of runs) {
    const wide = Math.min(width, b - a);
    // Centre it on the ideal point, then slide it back inside the run.
    const centre = clamp(uIdeal, a + wide / 2, b - wide / 2);
    // Distance from the right spot costs more than being narrow. A wide panel
    // three metres from the reflection point is not doing the job the step
    // claims; a narrow one beside the window is, which is also what anyone
    // treating a room with a window in the middle of it ends up doing.
    const cost = Math.abs(centre - uIdeal) + (width - wide) * 0.8;
    if (!best || cost < best.cost) best = { u0: centre - wide / 2, u1: centre + wide / 2, cost };
  }
  return best && best.u1 - best.u0 > 0.4 ? best : null;
}

/** Split one rectangle around everything reserved on its wall. */
function cut(rects, rect) {
  const crossing = rects
    .filter((r) => rect.v0 < r.v1 && rect.v1 > r.v0 && r.u1 > rect.u0 && r.u0 < rect.u1)
    .sort((a, b) => a.u0 - b.u0);
  const out = [];
  let at = rect.u0;
  for (const c of crossing) {
    if (c.u0 > at) out.push({ ...rect, u0: at, u1: Math.min(c.u0, rect.u1) });
    at = Math.max(at, c.u1);
  }
  if (at < rect.u1) out.push({ ...rect, u0: at, u1: rect.u1 });
  return out.filter((r) => r.u1 - r.u0 > 0.35);
}

/**
 * The whole plan for the current stage: which rectangles on which walls, and
 * whether the corner traps and the ceiling clouds are in.
 *
 * Cumulative -- each stage is everything before it plus one more decision.
 */
export function treatmentZones(state) {
  const { w, d, h } = state.dims;
  const stage = clamp(Math.round(state.treatment.stage ?? 0), 0, MAX_STAGE);
  const f = fittings(state);
  const walls = wallAxes(w, d);
  const blocked = reserved(state);
  const zones = [[], [], [], []];
  if (stage === 0) return { zones, corners: false, cloud: 0, stage };

  // Drapes hang; they do not sit in a band at ear height. Every stage still
  // decides *where*, and a curtain then runs floor to rail over that span.
  const hanging = state.treatment.type === 'drapes';
  const railY = Math.min(f.eaves - 0.12, h * 0.94);
  const seat = defaultPlacement(state);
  const ear = clamp((seat.source.height + seat.mic.height) / 2, 0.7, f.eaves - 0.7);
  const panelH = clamp(h * 0.44, 0.9, 2.0);
  const band = (v) => (hanging ? { v0: 0.008, v1: railY } : { v0: v - panelH / 2, v1: v + panelH / 2 });

  const bounds = (v, height) => ({
    v0: Math.max(0.02, hanging ? 0.008 : v - height / 2),
    v1: Math.min(f.eaves - 0.08, hanging ? railY : v + height / 2),
  });
  /** A run across the wall, broken around whatever is in the way. */
  const span = (id, u0, u1, v, height) => {
    const b = bounds(v, height);
    const rect = {
      u0: Math.max(0.1, u0), u1: Math.min(walls[id].len - 0.1, u1), v0: b.v0, v1: b.v1,
    };
    if (rect.u1 > rect.u0 && rect.v1 > rect.v0) zones[id].push(...cut(blocked[id], rect));
  };
  /** One panel, as near this point as it will go. */
  const panel = (id, u, width, v, height) => {
    const b = bounds(v, height);
    if (b.v1 <= b.v0) return;
    const p = placeNear(blocked[id], walls[id].len, u, width, b.v0, b.v1);
    if (p) zones[id].push({ u0: p.u0, u1: p.u1, v0: b.v0, v1: b.v1 });
  };

  // 1: the mirror point on each side wall. 2: the same on the end walls.
  const pw = clamp(Math.min(w, d) * 0.26, 0.9, 2.2);
  for (const id of stage >= 2 ? [2, 3, 0, 1] : [2, 3]) {
    panel(id, reflectionPointU(state, id), pw, ear, panelH);
  }

  // 3: a broad band across the wall behind the performer. Which wall that is
  // depends on which way round the mic is, so work it out rather than assume.
  if (stage >= 3) {
    const behind = seat.mic.z > seat.source.z ? 0 : 1;
    span(behind, walls[behind].len * 0.1, walls[behind].len * 0.9, ear, panelH * 1.15);
  }

  // 6: right around, and taller -- but stopping short of the floor and the
  // cornice, because that is where it goes and because a wall covered corner
  // to corner reads as a padded cell rather than a room.
  if (stage >= 6) {
    const tall = (f.eaves - 0.5) * 0.82;
    for (const wall of walls) span(wall.id, 0.1, wall.len - 0.1, 0.42 + tall / 2, tall);
  }

  // Fabric-wrapped absorbers come in panels with a gap between them, so the
  // plan says panels. Drawing a band and then subdividing it would put area on
  // the wall that the model never heard about.
  const panelled = state.treatment.type === 'rockwool';
  return {
    zones: zones.map((z) => (panelled ? merge(z).flatMap(intoPanels) : merge(z))),
    // Corner traps happen whatever the material: a theatre masks its corners
    // with the same drape as its walls. A step of the plan that does nothing
    // for one treatment type is a step that reads as broken.
    corners: stage >= 4,
    cloud: stage >= 6 ? 0.45 : stage >= 5 ? 0.26 : 0,
    stage,
  };
}

/**
 * Break a run into equal panels with a gap between them.
 *
 * A single four-metre slab of rockwool is not a thing anyone has ever hung. It
 * comes in panels, and the rhythm of panel-gap-panel is most of why a treated
 * wall looks designed rather than upholstered.
 */
function intoPanels(rect) {
  const width = rect.u1 - rect.u0;
  if (width < 1.05) return [rect];
  const gap = 0.075;
  const n = clamp(Math.round(width / 0.72), 2, 8);
  const each = (width - gap * (n - 1)) / n;
  if (each < 0.4) return [rect];
  const out = [];
  for (let i = 0; i < n; i++) {
    const u0 = rect.u0 + i * (each + gap);
    out.push({ ...rect, u0, u1: u0 + each });
  }
  return out;
}

/** Fold overlapping rectangles on one wall together, so area is not counted twice. */
function merge(rects) {
  if (rects.length < 2) return rects;
  const byBand = new Map();
  for (const r of rects) {
    const key = `${r.v0.toFixed(3)}|${r.v1.toFixed(3)}`;
    if (!byBand.has(key)) byBand.set(key, []);
    byBand.get(key).push(r);
  }
  const out = [];
  for (const group of byBand.values()) {
    group.sort((a, b) => a.u0 - b.u0);
    let cur = { ...group[0] };
    for (const r of group.slice(1)) {
      if (r.u0 <= cur.u1 + 1e-6) cur.u1 = Math.max(cur.u1, r.u1);
      else { out.push(cur); cur = { ...r }; }
    }
    out.push(cur);
  }
  // Bands at different heights can still overlap each other; the wider one
  // wins, which is what the geometry draws too.
  return out.filter((r, i) => !out.some((o, j) => j !== i
    && o.u0 <= r.u0 + 1e-6 && o.u1 >= r.u1 - 1e-6
    && o.v0 <= r.v0 + 1e-6 && o.v1 >= r.v1 - 1e-6
    && (o.u1 - o.u0) * (o.v1 - o.v0) > (r.u1 - r.u0) * (r.v1 - r.v0)));
}

/**
 * How much of the wall and ceiling the plan actually covers.
 *
 * Measured off the same rectangles the renderer draws, cuts and all, so the
 * number the decay is computed from is the treatment you can see.
 */
export function zoneCoverage(state) {
  const { w, d, h } = state.dims;
  const plan = treatmentZones(state);
  const f = fittings(state);
  let area = 0;
  for (const wall of plan.zones) {
    for (const r of wall) area += (r.u1 - r.u0) * (r.v1 - r.v0);
  }
  if (plan.corners) {
    // Four traps across the vertical corners: a flat face of this chord,
    // running the full height.
    area += 4 * cornerChord(state) * Math.min(f.eaves - 0.05, h);
  }
  const total = 2 * (w + d) * h;
  return { wall: clamp(area / total, 0, 1), ceiling: clamp(plan.cloud, 0, 1) };
}

/** How far a corner trap reaches along each wall it straddles. */
export function cornerChord(state) {
  const p = PRESETS_BY_ID[state.presetId];
  return clamp(Math.min(state.dims.w, state.dims.d) * 0.06, 0.22, 0.5) * (p.seating ? 1.4 : 1);
}
