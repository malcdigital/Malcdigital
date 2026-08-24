// The room model. Given a shoebox, its surfaces, where the performer stands and
// where the mic is, work out what the mic actually hears: the direct sound, a
// list of discrete early reflections from the image-source method, and the level
// and decay of the diffuse tail.
//
// Deliberately free of any browser API. Everything here is arithmetic.

import {
  BANDS, AIR_M, MATERIALS, TREATMENTS, TREATMENT_SCATTER, reflectance, blendAlpha,
} from './materials.js';
import { PRESETS_BY_ID } from './presets.js';
import { MICS_BY_ID, polarGain, proximityCurve, directivityFactor, PATTERNS } from './mics.js';

export const SPEED_OF_SOUND = 343;
export const NB = BANDS.length;

/** How much each band cares about off-axis dulling. Highs beam, lows wrap. */
const OFF_AXIS_WEIGHT = [0.0, 0.1, 0.25, 0.5, 0.8, 1.0];

const MAX_ORDER = 3;
const MAX_TAPS = 64;
const TAP_FLOOR_DB = -62;

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/** Build the default editable state for a preset. */
export function makeState(presetId = 'studio') {
  const p = PRESETS_BY_ID[presetId];
  const dims = { ...p.dims };
  const src = {
    x: p.sourceAt.x * dims.w,
    z: p.sourceAt.z * dims.d,
    height: Math.min(1.6, dims.h * 0.5),
  };
  const state = {
    presetId,
    scale: 1,
    dims,
    treatment: { ...p.treatment },
    source: src,
    mic: {
      x: src.x,
      z: src.z + p.micDistance,
      height: Math.min(1.5, dims.h * 0.45),
      azimuth: 0,
      aimAtSource: true,
      id: presetId === 'studio' ? 'ldc' : 'sdc',
    },
  };
  aimMic(state);
  return state;
}

/** Re-point the mic at the performer, if it is set to track them. */
export function aimMic(state) {
  if (!state.mic.aimAtSource) return state;
  state.mic.azimuth = Math.atan2(state.source.x - state.mic.x, state.source.z - state.mic.z);
  return state;
}

/** Straight-line distance from performer to mic, in metres. */
export function micDistance(state) {
  const dx = state.mic.x - state.source.x;
  const dz = state.mic.z - state.source.z;
  const dy = state.mic.height - state.source.height;
  return Math.sqrt(dx * dx + dz * dz + dy * dy);
}

/**
 * Move the mic to a given distance from the performer, keeping its bearing.
 * Clamped so it stays inside the room.
 */
export function setMicDistance(state, metres) {
  const dx = state.mic.x - state.source.x;
  const dz = state.mic.z - state.source.z;
  let len = Math.hypot(dx, dz);
  let ux, uz;
  if (len < 1e-6) { ux = 0; uz = 1; } else { ux = dx / len; uz = dz / len; }
  const d = Math.max(0.08, metres);
  state.mic.x = clamp(state.source.x + ux * d, 0.15, state.dims.w - 0.15);
  state.mic.z = clamp(state.source.z + uz * d, 0.15, state.dims.d - 0.15);
  aimMic(state);
  return state;
}

/** Apply a size scale factor to the preset's base dimensions. */
export function setScale(state, scale) {
  const p = PRESETS_BY_ID[state.presetId];
  const [lo, hi] = p.sizeRange;
  const s = clamp(scale, lo, hi);
  const before = { ...state.dims };
  state.scale = s;
  state.dims = { w: p.dims.w * s, d: p.dims.d * s, h: p.dims.h * s };
  // Keep everyone at the same relative spot in the room as it grows.
  const fx = state.dims.w / before.w, fz = state.dims.d / before.d, fy = state.dims.h / before.h;
  for (const o of [state.source, state.mic]) {
    o.x *= fx; o.z *= fz; o.height = Math.min(o.height * fy, state.dims.h - 0.2);
  }
  clampOccupants(state);
  return state;
}

/** Keep the performer and mic inside the walls. */
export function clampOccupants(state) {
  const { w, d, h } = state.dims;
  for (const o of [state.source, state.mic]) {
    o.x = clamp(o.x, 0.15, w - 0.15);
    o.z = clamp(o.z, 0.15, d - 0.15);
    o.height = clamp(o.height, 0.15, h - 0.15);
  }
  aimMic(state);
  return state;
}

/**
 * Effective per-band absorption of each surface once seating and wall
 * treatment are folded in, plus the areas they cover.
 */
export function surfaces(state) {
  const p = PRESETS_BY_ID[state.presetId];
  const { w, d, h } = state.dims;
  const treat = TREATMENTS[state.treatment.type] || TREATMENTS.rockwool;
  const cov = clamp(state.treatment.coverage, 0, 1);
  const scatter = (TREATMENT_SCATTER[state.treatment.type] || 0) * cov;

  let floorAlpha = MATERIALS[p.surfaces.floor].alpha;
  let floorScatter = 0;
  if (p.seating) {
    floorAlpha = blendAlpha(floorAlpha, MATERIALS[p.seating.material].alpha, p.seating.coverage);
    floorScatter = p.seating.coverage * 0.5;
  }
  // Treatment goes on the walls in full, and on the ceiling as clouds.
  let wallBase = MATERIALS[p.surfaces.walls].alpha;
  if (p.wallBlend) {
    wallBase = blendAlpha(wallBase, MATERIALS[p.wallBlend.material].alpha, p.wallBlend.coverage);
  }
  const wallAlpha = blendAlpha(wallBase, treat.alpha, cov * 0.9);
  const ceilAlpha = blendAlpha(MATERIALS[p.surfaces.ceiling].alpha, treat.alpha, cov * 0.6);

  return {
    floor:   { area: w * d,            alpha: floorAlpha, scatter: floorScatter },
    ceiling: { area: w * d,            alpha: ceilAlpha,  scatter: scatter * 0.6 },
    walls:   { area: 2 * (w + d) * h,  alpha: wallAlpha,  scatter: scatter * 0.9 },
  };
}

/**
 * Reverberation time per band (Eyring, with the air-absorption term) plus the
 * room constant R that sets how loud the diffuse field sits.
 */
export function decayProfile(state) {
  const s = surfaces(state);
  const { w, d, h } = state.dims;
  const volume = w * d * h;
  const areaTotal = s.floor.area + s.ceiling.area + s.walls.area;

  const alphaBar = new Array(NB);
  const rt60 = new Array(NB);
  const roomConstant = new Array(NB);

  for (let b = 0; b < NB; b++) {
    const absorbed = s.floor.area * s.floor.alpha[b]
                   + s.ceiling.area * s.ceiling.alpha[b]
                   + s.walls.area * s.walls.alpha[b];
    const ab = clamp(absorbed / areaTotal, 0.002, 0.985);
    alphaBar[b] = ab;
    const eyring = -areaTotal * Math.log(1 - ab);
    rt60[b] = clamp((0.161 * volume) / (eyring + 4 * AIR_M[b] * volume), 0.03, 30);
    roomConstant[b] = Math.max(1e-3, (areaTotal * ab) / (1 - ab));
  }

  const midRt = (rt60[2] + rt60[3]) / 2;
  return {
    volume,
    areaTotal,
    alphaBar,
    rt60,
    roomConstant,
    midRt,
    meanFreePath: (4 * volume) / areaTotal,
    // Rubak's rule of thumb: the field is diffuse after about sqrt(V) ms.
    mixingTime: Math.sqrt(volume) / 1000,
    schroeder: 2000 * Math.sqrt(midRt / volume),
  };
}

/** Mirror a coordinate into image-source space for index n over length L. */
function mirror(n, s, L) {
  return n % 2 === 0 ? n * L + s : (n + 1) * L - s;
}

function dbToGain(db) { return Math.pow(10, db / 20); }

/**
 * Both capsule directions. A mono mic has one; a stereo pair has two splayed
 * by its spread angle, which is what puts the early reflections in stereo.
 */
function capsuleAxes(mic, azimuth) {
  const half = ((mic.spread || 0) * Math.PI) / 360;
  const make = (a) => ({ x: Math.sin(a), z: Math.cos(a) });
  return mic.spread ? [make(azimuth - half), make(azimuth + half)] : [make(azimuth), make(azimuth)];
}

/**
 * Gain of one capsule for sound arriving along unit vector (ux,uy,uz),
 * per band, including the pattern, the on-axis tone and off-axis dulling.
 */
function capsuleGain(micModel, axis, ux, uy, uz, out) {
  // The capsule axis is horizontal, so a plain 3D dot product with the unit
  // arrival vector already accounts for elevation: sound from straight above
  // lands at 90 degrees off-axis and a cardioid halves it, as it should.
  const cosTheta = clamp(axis.x * ux + axis.z * uz, -1, 1);
  const pat = polarGain(micModel, Math.acos(cosTheta));
  // Off-axis dulling tracks the capsule's acceptance lobe, not simply "the
  // front": a ribbon's rear lobe is acoustically on-axis and stays bright,
  // while grazing incidence at the sides dulls even an omni a little.
  const axial = Math.abs(pat) / Math.abs(polarGain(micModel, 0) || 1);
  const grazing = 1 - Math.abs(cosTheta);
  const offness = clamp(Math.max(1 - axial, grazing * 0.6), 0, 1);
  for (let b = 0; b < NB; b++) {
    const dull = 1 - micModel.offAxisDamping * offness * OFF_AXIS_WEIGHT[b];
    out[b] = pat * Math.max(0.02, dull);
  }
  return out;
}

/**
 * Full analysis: what the mic hears, given the room and everyone's position.
 * Returns direct/early/late in a form the DSP layer can turn into filters.
 */
export function analyze(state) {
  const decay = decayProfile(state);
  const surf = surfaces(state);
  const { w, d, h } = state.dims;
  const micModel = MICS_BY_ID[state.mic.id] || MICS[0];
  const axes = capsuleAxes(micModel, state.mic.azimuth);

  const rWall = surf.walls.alpha.map(reflectance);
  const rFloor = surf.floor.alpha.map(reflectance);
  const rCeil = surf.ceiling.alpha.map(reflectance);
  const specWall = 1 - surf.walls.scatter;
  const specFloor = 1 - surf.floor.scatter;
  const specCeil = 1 - surf.ceiling.scatter;

  const sx = state.source.x, sy = state.source.height, sz = state.source.z;
  const mx = state.mic.x, my = state.mic.height, mz = state.mic.z;

  const dist0 = Math.max(0.08, micDistance(state));
  const prox = proximityCurve(micModel, dist0);

  const gL = new Array(NB), gR = new Array(NB);

  // --- direct sound -------------------------------------------------------
  const ux0 = (sx - mx) / dist0, uy0 = (sy - my) / dist0, uz0 = (sz - mz) / dist0;
  const direct = { delay: dist0 / SPEED_OF_SOUND, distance: dist0, left: new Array(NB), right: new Array(NB) };
  capsuleGain(micModel, axes[0], ux0, uy0, uz0, gL);
  capsuleGain(micModel, axes[1], ux0, uy0, uz0, gR);
  for (let b = 0; b < NB; b++) {
    const air = Math.exp(-AIR_M[b] * dist0);
    const p = dbToGain(prox[b]);
    direct.left[b] = (gL[b] / dist0) * air * p;
    direct.right[b] = (gR[b] / dist0) * air * p;
  }

  // --- early reflections, by image sources --------------------------------
  const taps = [];
  const refDb = 20 * Math.log10(Math.max(1e-9, Math.abs(direct.left[3]) + Math.abs(direct.right[3])) / 2);
  for (let nx = -MAX_ORDER; nx <= MAX_ORDER; nx++) {
    for (let ny = -MAX_ORDER; ny <= MAX_ORDER; ny++) {
      for (let nz = -MAX_ORDER; nz <= MAX_ORDER; nz++) {
        const order = Math.abs(nx) + Math.abs(ny) + Math.abs(nz);
        if (order === 0 || order > MAX_ORDER) continue;

        const ix = mirror(nx, sx, w), iy = mirror(ny, sy, h), iz = mirror(nz, sz, d);
        const dx = ix - mx, dy = iy - my, dz = iz - mz;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist < 0.05) continue;

        const wallHits = Math.abs(nx) + Math.abs(nz);
        const an = Math.abs(ny);
        const ceilHits = ny > 0 ? Math.ceil(an / 2) : Math.floor(an / 2);
        const floorHits = ny > 0 ? Math.floor(an / 2) : Math.ceil(an / 2);

        const ux = dx / dist, uy = dy / dist, uz = dz / dist;
        capsuleGain(micModel, axes[0], ux, uy, uz, gL);
        capsuleGain(micModel, axes[1], ux, uy, uz, gR);

        const spec = Math.pow(specWall, wallHits) * Math.pow(specCeil, ceilHits) * Math.pow(specFloor, floorHits);
        const left = new Array(NB), right = new Array(NB);
        let peak = 0;
        for (let b = 0; b < NB; b++) {
          const refl = Math.pow(rWall[b], wallHits) * Math.pow(rCeil[b], ceilHits) * Math.pow(rFloor[b], floorHits);
          const shared = (refl * spec * Math.exp(-AIR_M[b] * dist)) / dist;
          left[b] = gL[b] * shared;
          right[b] = gR[b] * shared;
          peak = Math.max(peak, Math.abs(left[b]), Math.abs(right[b]));
        }
        if (20 * Math.log10(Math.max(peak, 1e-9)) - refDb < TAP_FLOOR_DB) continue;

        taps.push({
          delay: dist / SPEED_OF_SOUND,
          distance: dist,
          order,
          left,
          right,
          image: { x: ix, y: iy, z: iz },
          n: { x: nx, y: ny, z: nz },
        });
      }
    }
  }
  taps.sort((a, b) => a.delay - b.delay);
  const early = taps.slice(0, MAX_TAPS);

  // --- diffuse tail -------------------------------------------------------
  // Amplitude of the reverberant field relative to a direct sound normalised to
  // 1/d. Independent of distance, which is exactly why walking away from the
  // mic buries you in the room.
  const qMic = directivityFactor(micModel);
  const late = { left: new Array(NB), right: new Array(NB) };
  for (let b = 0; b < NB; b++) {
    const amp = 4 * Math.sqrt(Math.PI / (decay.roomConstant[b] * qMic));
    late.left[b] = amp;
    late.right[b] = amp;
  }

  const criticalDistance = 0.141 * Math.sqrt(qMic * decay.roomConstant[3]);

  // Energy bookkeeping, for the meters.
  const energy = (bands) => bands.reduce((acc, v) => acc + v * v, 0) / NB;
  const directE = (energy(direct.left) + energy(direct.right)) / 2;
  let earlyE = 0;
  for (const t of early) earlyE += (energy(t.left) + energy(t.right)) / 2;
  const lateE = (energy(late.left) + energy(late.right)) / 2;

  return {
    state,
    decay,
    surfaces: surf,
    mic: micModel,
    direct,
    early,
    late,
    // Applied downstream as a band EQ across everything the capsule hears;
    // proximity rides on the direct path alone.
    micTone: micModel.tone.slice(),
    proximity: prox,
    criticalDistance,
    firstReflectionGap: early.length ? early[0].delay - direct.delay : 0,
    balance: {
      direct: directE,
      early: earlyE,
      late: lateE,
      drrDb: 10 * Math.log10(Math.max(1e-12, directE) / Math.max(1e-12, earlyE + lateE)),
    },
  };
}

/**
 * Where the first-order reflections actually bounce, for drawing.
 *
 * An image source sits behind a wall; the real path from performer to mic is
 * the straight line from that image to the mic, folded at the point where it
 * crosses the wall. That crossing point is what gets drawn, so the rays on
 * screen are the same ones feeding the early-reflection taps.
 */
export function reflectionPaths(response) {
  const { state } = response;
  const { w, d, h } = state.dims;
  const m = { x: state.mic.x, y: state.mic.height, z: state.mic.z };
  const out = [];

  for (const tap of response.early) {
    if (tap.order !== 1) continue;
    const img = tap.image;
    let axis, plane;
    if (tap.n.x !== 0) { axis = 'x'; plane = tap.n.x > 0 ? w : 0; }
    else if (tap.n.z !== 0) { axis = 'z'; plane = tap.n.z > 0 ? d : 0; }
    else { axis = 'y'; plane = tap.n.y > 0 ? h : 0; }

    const from = { x: img.x, y: img.y, z: img.z };
    const span = m[axis] - from[axis];
    if (Math.abs(span) < 1e-6) continue;
    const t = (plane - from[axis]) / span;
    if (t < 0 || t > 1) continue;

    const hit = {
      x: from.x + (m.x - from.x) * t,
      y: from.y + (m.y - from.y) * t,
      z: from.z + (m.z - from.z) * t,
    };
    hit[axis] = plane;

    // Broadband amplitude, for how brightly to draw the ray.
    let amp = 0;
    for (let b = 0; b < NB; b++) amp += Math.abs(tap.left[b]) + Math.abs(tap.right[b]);
    amp /= 2 * NB;

    out.push({
      hit,
      surface: axis === 'y' ? (tap.n.y > 0 ? 'ceiling' : 'floor') : 'wall',
      axis,
      delay: tap.delay,
      distance: tap.distance,
      amp,
    });
  }
  out.sort((a, b) => a.delay - b.delay);
  return out;
}
