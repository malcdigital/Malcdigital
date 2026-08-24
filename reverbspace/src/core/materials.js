// Absorption coefficients per octave band. Pure data + math: no browser APIs in
// this directory, so the whole acoustics layer ports straight to C++.

export const BANDS = [125, 250, 500, 1000, 2000, 4000];

// Air attenuation coefficient m (per metre), ~20 C / 50% RH. Used in the 4mV
// term of the Eyring equation and for per-tap high-frequency loss over distance.
export const AIR_M = [0.0001, 0.0002, 0.0004, 0.0010, 0.0027, 0.0072];

/**
 * @typedef {Object} Material
 * @property {string} name
 * @property {number[]} alpha  absorption coefficient per BANDS entry
 * @property {string} colour   base colour for the room renderer
 * @property {string} pattern  how the renderer lays the surface out
 * @property {number} grain    how much plank-to-plank colour variation
 */

/** @type {Record<string, Material>} */
export const MATERIALS = {
  stone:        { name: 'Cut stone',         alpha: [0.02, 0.02, 0.03, 0.03, 0.04, 0.05], colour: '#8d8b84', pattern: 'blocks', grain: 0.1 },
  brick:        { name: 'Bare brick',        alpha: [0.03, 0.03, 0.03, 0.04, 0.05, 0.07], colour: '#8f6f5e', pattern: 'bricks', grain: 0.14 },
  plaster:      { name: 'Plaster',           alpha: [0.14, 0.10, 0.06, 0.05, 0.04, 0.03], colour: '#c8c2b6', pattern: 'smooth', grain: 0.03 },
  drywall:      { name: 'Plasterboard',      alpha: [0.29, 0.10, 0.05, 0.04, 0.07, 0.09], colour: '#cfcabf', pattern: 'smooth', grain: 0.03 },
  woodPanel:    { name: 'Wood panelling',    alpha: [0.28, 0.22, 0.17, 0.09, 0.10, 0.11], colour: '#a0724a', pattern: 'planks', grain: 0.16 },
  woodFloor:    { name: 'Wood floor',        alpha: [0.15, 0.11, 0.10, 0.07, 0.06, 0.07], colour: '#96693f', pattern: 'planks', grain: 0.13 },
  marble:       { name: 'Marble floor',      alpha: [0.01, 0.01, 0.01, 0.01, 0.02, 0.02], colour: '#b9b5ad', pattern: 'tiles', grain: 0.07 },
  carpet:       { name: 'Carpet',            alpha: [0.02, 0.06, 0.14, 0.37, 0.60, 0.65], colour: '#5c5148', pattern: 'smooth', grain: 0.05 },
  glass:        { name: 'Glazing',           alpha: [0.35, 0.25, 0.18, 0.12, 0.07, 0.04], colour: '#7fa6b5', pattern: 'smooth', grain: 0.02 },
  seatsEmpty:   { name: 'Empty seating',     alpha: [0.19, 0.37, 0.56, 0.67, 0.61, 0.59], colour: '#6b3f46', pattern: 'smooth', grain: 0.06 },
  seatsFull:    { name: 'Occupied seating',  alpha: [0.39, 0.57, 0.80, 0.94, 0.92, 0.87], colour: '#7a4a52', pattern: 'smooth', grain: 0.06 },
  pews:         { name: 'Wooden pews',       alpha: [0.10, 0.09, 0.08, 0.12, 0.14, 0.16], colour: '#7b5a3a', pattern: 'planks', grain: 0.1 },
};

/** Treatment the user can hang on the walls, in increasing broadband strength. */
export const TREATMENTS = {
  foam:      { name: 'Foam tiles',      alpha: [0.10, 0.30, 0.70, 0.90, 0.95, 0.95], colour: '#4a5364',
               blurb: 'Kills highs, leaves the low end alone.' },
  rockwool:  { name: 'Rockwool + traps', alpha: [0.45, 0.75, 0.95, 0.98, 0.95, 0.90], colour: '#c4b89c',
               blurb: 'Broadband. Takes the bass down with everything else.' },
  drapes:    { name: 'Heavy drapes',    alpha: [0.14, 0.35, 0.55, 0.72, 0.70, 0.65], colour: '#6b3442',
               blurb: 'Soft mid/high damping, keeps some air.' },
  diffusion: { name: 'Diffusers',       alpha: [0.10, 0.15, 0.20, 0.22, 0.20, 0.18], colour: '#9a8a6a',
               blurb: 'Scatters instead of absorbing. Keeps the tail long but smooths it.' },
};

/** Amplitude (not energy) reflection coefficient for an absorption coefficient. */
export function reflectance(alpha) {
  return Math.sqrt(Math.max(0, 1 - alpha));
}

/** Blend two per-band coefficient vectors: (1-t)*a + t*b. */
export function blendAlpha(a, b, t) {
  const out = new Array(BANDS.length);
  for (let i = 0; i < BANDS.length; i++) out[i] = a[i] * (1 - t) + b[i] * t;
  return out;
}

/**
 * How much of a reflection each treatment scatters rather than absorbs.
 * Diffusers barely absorb, but they break up specular reflections, which
 * pushes energy out of the discrete early taps and into the diffuse tail.
 */
export const TREATMENT_SCATTER = { foam: 0.10, rockwool: 0.15, drapes: 0.20, diffusion: 0.90 };
