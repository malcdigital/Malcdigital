// The room's own resonances, and what note they ring at.
//
// Everything else in here treats the tail as a diffuse field, which is what it
// is above the Schroeder frequency: so many modes overlapping that no single
// one is audible. Below it they are separate, and in a small room they are the
// most characteristic thing about the sound -- the boxy ring you cannot mix
// through. A feedback delay network cannot produce them; it makes a smooth
// tail by construction. So they are modelled here and rendered as what they
// physically are, a bank of decaying resonances.
//
// For a rigid shoebox the modes are exact:
//
//     f(nx,ny,nz) = (c/2) sqrt( (nx/W)^2 + (ny/H)^2 + (nz/D)^2 )
//
// and each has a standing-wave shape that is a product of cosines. How loudly
// you hear one is that shape sampled where the performer is, times the same
// shape sampled at the mic -- so walking around the room genuinely changes
// which resonances you excite and which you hear, exactly as it does in life.

import { mouthHeight } from './fittings.js';

const C = 343;
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/** The highest a mode is modelled. Shared with the bank's own low-pass. */
export const MODE_TOP_HZ = 140;

export const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

/** MIDI note number for a frequency, as a real number. A4 = 440 = note 69. */
export function noteNumber(freq) {
  return 69 + 12 * Math.log2(Math.max(freq, 1e-6) / 440);
}

/** Frequency of a MIDI note number. */
export function noteFrequency(n) {
  return 440 * Math.pow(2, (n - 69) / 12);
}

/** The nearest note to a frequency, and how far off it is. */
export function noteOf(freq) {
  const n = noteNumber(freq);
  const nearest = Math.round(n);
  return {
    name: NOTE_NAMES[((nearest % 12) + 12) % 12],
    octave: Math.floor(nearest / 12) - 1,
    cents: Math.round((n - nearest) * 100),
    midi: nearest,
  };
}

/** "F#1 +12¢", or "F#1" when it is close enough to call in tune. */
export function noteLabel(freq) {
  const n = noteOf(freq);
  const off = Math.abs(n.cents) < 4 ? '' : ` ${n.cents > 0 ? '+' : '−'}${Math.abs(n.cents)}¢`;
  return `${n.name}${n.octave}${off}`;
}

/**
 * Every mode of the room, strongest first.
 *
 * Only the ones below the Schroeder frequency are worth having: above it they
 * overlap into the diffuse tail the delay network already renders, and doubling
 * them up would just make the same sound twice. A cathedral's Schroeder
 * frequency is around 25 Hz, so it gets none -- which is the right answer, and
 * is precisely why a big room has no note and a booth has an obvious one.
 */
export function roomModes(state, decay, limit = 20) {
  const { w, d, h } = state.dims;
  const s = state.source, m = state.mic;
  // Up to Schroeder, and never above 140 Hz.
  //
  // The ceiling is not physics, it is a seam. The surface model states its
  // numbers in octave bands from 125 Hz up, and the delay network is
  // calibrated against them; modelling modes into that range would be two
  // accounts of the same energy, and sixteen resonator skirts summing
  // coherently an octave above put 6 dB of extra tail at 500 Hz in a small
  // room. Below 140 Hz there is no band for them to argue with.
  const top = Math.min(decay.schroeder * 1.2, MODE_TOP_HZ);
  const nMax = (len) => Math.floor((2 * len * top) / C);
  const out = [];

  for (let nx = 0; nx <= nMax(w); nx++) {
    for (let ny = 0; ny <= nMax(h); ny++) {
      for (let nz = 0; nz <= nMax(d); nz++) {
        if (nx + ny + nz === 0) continue;
        const f = (C / 2) * Math.hypot(nx / w, ny / h, nz / d);
        if (f > top || f < 18) continue;
        // The standing wave, sampled at each end of the path.
        const at = (x, y, z) => Math.cos((nx * Math.PI * x) / w)
                              * Math.cos((ny * Math.PI * y) / h)
                              * Math.cos((nz * Math.PI * z) / d);
        const couple = at(s.x, mouthHeight(s.height), s.z) * at(m.x, m.height, m.z);
        if (Math.abs(couple) < 0.02) continue;
        // Axial modes bounce between one pair of walls; tangential and oblique
        // ones strike more surface per second and die away faster for it.
        const order = (nx > 0 ? 1 : 0) + (ny > 0 ? 1 : 0) + (nz > 0 ? 1 : 0);
        const damping = order === 1 ? 1 : order === 2 ? 0.82 : 0.66;
        out.push({ f, gain: couple, nx, ny, nz, order, rt: rtAt(decay, f) * damping });
      }
    }
  }
  out.sort((a, b) => Math.abs(b.gain) - Math.abs(a.gain) || a.f - b.f);
  return out.slice(0, limit);
}

/** Reverberation time at an arbitrary frequency, from the octave bands. */
function rtAt(decay, f) {
  const bands = [125, 250, 500, 1000, 2000, 4000];
  if (f <= bands[0]) return decay.rt60[0];
  for (let i = 1; i < bands.length; i++) {
    if (f <= bands[i]) {
      const t = Math.log2(f / bands[i - 1]);
      return decay.rt60[i - 1] + (decay.rt60[i] - decay.rt60[i - 1]) * t;
    }
  }
  return decay.rt60[decay.rt60.length - 1];
}

/**
 * The note the room rings at, or null when it does not ring at one.
 *
 * The test is not the frequency, it is whether the room has a modal region at
 * all. Below the Schroeder frequency the modes are separate and you hear them
 * one at a time; above it they overlap into a smooth field. A cathedral's
 * Schroeder frequency is around 27 Hz, so everything separable about it is
 * beneath hearing: its lowest mode happens to sit near a B flat, and saying so
 * would be arithmetic rather than something anyone could listen for.
 */
export const MODAL_FLOOR_HZ = 45;

export function roomNote(state, decay) {
  if (decay.schroeder < MODAL_FLOOR_HZ) return null;
  const modes = roomModes(state, decay, 6);
  if (!modes.length) return null;
  return { f: modes[0].f, label: noteLabel(modes[0].f), mode: modes[0] };
}

/**
 * The size that would put the room's note on this pitch class.
 *
 * Mode frequencies go as 1/length and the size control scales every dimension
 * together, so this is exact: to raise the note by a ratio, shrink the room by
 * it. Occupants keep their relative positions when the room is scaled, so the
 * mode shapes -- and with them which mode is the strongest -- do not change.
 * Returns null when no octave of that note is reachable within the preset's
 * size range.
 */
export function scaleForNote(state, decay, pitchClass, range) {
  const note = roomNote(state, decay);
  if (!note) return null;
  const [lo, hi] = range;
  const here = noteNumber(note.f);
  let best = null;
  // Every octave of the wanted pitch class, near or far.
  for (let midi = pitchClass; midi < 132; midi += 12) {
    const wanted = noteFrequency(midi);
    const scale = state.scale * (note.f / wanted);
    if (scale < lo - 1e-9 || scale > hi + 1e-9) continue;
    const cost = Math.abs(midi - here);
    if (!best || cost < best.cost) best = { scale: clamp(scale, lo, hi), midi, cost };
  }
  return best;
}
