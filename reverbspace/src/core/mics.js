// Microphone models: polar pattern, on-axis tone, off-axis colouration and
// proximity effect. All of it feeds the per-reflection gains in acoustics.js.

import { BANDS } from './materials.js';

const cos = Math.cos;

/** Signed polar responses. Negative means rear lobe (opposite polarity). */
export const PATTERNS = {
  omni:          { name: 'Omni',           q: 1.0,  gradient: 0.0, f: () => 1 },
  cardioid:      { name: 'Cardioid',       q: 3.0,  gradient: 1.0, f: (t) => 0.5 + 0.5 * cos(t) },
  supercardioid: { name: 'Supercardioid',  q: 3.9,  gradient: 1.0, f: (t) => 0.37 + 0.63 * cos(t) },
  figure8:       { name: 'Figure-8',       q: 3.0,  gradient: 1.0, f: (t) => cos(t) },
  lobar:         { name: 'Lobar',          q: 8.0,  gradient: 0.8,
                   f: (t) => (0.25 + 0.75 * cos(t)) * (0.35 + 0.65 * Math.pow(0.5 + 0.5 * cos(t), 3)) },
};

/**
 * @typedef {Object} MicModel
 * @property {string} id
 * @property {string} name
 * @property {string} blurb
 * @property {string} pattern        key into PATTERNS
 * @property {number[]} tone         on-axis dB per BANDS entry
 * @property {number} offAxisDamping 0..1 extra HF loss as sources move off-axis
 * @property {number} spread         degrees between capsules (0 = mono)
 * @property {number} maxProximity   dB of low-end lift the capsule will allow
 */

/** @type {MicModel[]} */
export const MICS = [
  {
    id: 'ldc',
    name: 'Large condenser',
    blurb: 'Cardioid, flattering top end. The default vocal mic.',
    pattern: 'cardioid',
    tone: [-1, 0, 0, 1, 3, 4],
    offAxisDamping: 0.35,
    spread: 0,
    maxProximity: 9,
  },
  {
    id: 'sdc',
    name: 'Small condenser',
    blurb: 'Omni capsule. Hears the whole room, honestly.',
    pattern: 'omni',
    tone: [0, 0, 0, 0, 1, 2],
    offAxisDamping: 0.12,
    spread: 0,
    maxProximity: 0,
  },
  {
    id: 'dynamic',
    name: 'Dynamic',
    blurb: 'Cardioid, presence bump, soft top. Rejects the room.',
    pattern: 'cardioid',
    tone: [-4, -2, 0, 2, 5, 1],
    offAxisDamping: 0.5,
    spread: 0,
    maxProximity: 12,
  },
  {
    id: 'ribbon',
    name: 'Ribbon',
    blurb: 'Figure-8. Dark, and it hears just as much behind it.',
    pattern: 'figure8',
    tone: [2, 1, 0, -1, -4, -9],
    offAxisDamping: 0.2,
    spread: 0,
    maxProximity: 10,
  },
  {
    id: 'shotgun',
    name: 'Shotgun',
    blurb: 'Lobar. Tight beam, thin off-axis, very little room.',
    pattern: 'lobar',
    tone: [-6, -3, 0, 2, 3, 0],
    offAxisDamping: 0.7,
    spread: 0,
    maxProximity: 6,
  },
  {
    id: 'xy',
    name: 'XY stereo pair',
    blurb: 'Two cardioids at 90 degrees. The room arrives in stereo.',
    pattern: 'cardioid',
    tone: [-1, 0, 0, 1, 2, 3],
    offAxisDamping: 0.3,
    spread: 90,
    maxProximity: 8,
  },
];

export const MICS_BY_ID = Object.fromEntries(MICS.map((m) => [m.id, m]));

/** Polar gain (signed) for a mic at off-axis angle theta, in radians. */
export function polarGain(mic, theta) {
  return PATTERNS[mic.pattern].f(theta);
}

/**
 * Proximity effect for a pressure-gradient capsule: a first-order gradient mic
 * lifts the low end as 1/(w*d) starts to rival 1/c. Omnis get nothing.
 * Returns per-band dB.
 */
export function proximityCurve(mic, distance, c = 343) {
  const grad = PATTERNS[mic.pattern].gradient;
  const out = new Array(BANDS.length).fill(0);
  if (grad <= 0 || mic.maxProximity <= 0) return out;
  const d = Math.max(0.05, distance);
  for (let i = 0; i < BANDS.length; i++) {
    const w = 2 * Math.PI * BANDS[i];
    const lift = 20 * Math.log10(Math.sqrt(1 + Math.pow(c / (w * d), 2)));
    out[i] = Math.min(lift * grad, mic.maxProximity);
  }
  return out;
}

/** Directivity factor Q, used for the direct-to-reverberant balance. */
export function directivityFactor(mic) {
  return PATTERNS[mic.pattern].q;
}
