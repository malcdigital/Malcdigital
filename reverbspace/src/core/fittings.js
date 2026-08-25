// Where a room's fixed features are: the control-room window, the door, the
// patch panel, the sconces, the line of the roof.
//
// This used to live inside the geometry builder, which meant the treatment
// planner could not see it -- and treatment that cannot see a window hangs
// itself across the glass. Both read it from here now, so they agree.

import { PRESETS_BY_ID } from './presets.js';

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/** Where the control-room window sits, or null for a room that has none. */
export function windowOpening(preset, w, h) {
  if (preset.id !== 'studio' && preset.id !== 'theater') return null;
  const cw = clamp(w * 0.26, 1.3, 2.9);
  const cy = clamp(h * 0.46, 1.1, 1.75);
  return { x0: w / 2 - cw / 2, x1: w / 2 + cw / 2, y0: cy - 0.48, y1: cy + 0.48 };
}

/** How many wall sconces a run of this length carries. */
export const sconcesPer = (len) => clamp(Math.round(len / 4.2), 1, 8);

/** Every fitting, in one place, derived only from the room's dimensions. */
export function fittings(state) {
  const p = PRESETS_BY_ID[state.presetId];
  const { w, d, h } = state.dims;
  // A gable rises this far above the mean height and the eaves drop as far
  // below, so the volume matches the flat ceiling the decay is computed from.
  const rise = p.pitch ? p.pitch * (w / p.dims.w) : 0;
  return {
    rise,
    eaves: h - rise,
    ridge: h + rise,
    win: windowOpening(p, w, h),
    doorZ: clamp(d * 0.24, 0.6, d - 1.2),
    doorH: Math.min(2.05, h - 0.1),
    patchZ: clamp(d * 0.24 + 0.9, 0.5, d - 0.6),
    hookY: clamp(h * 0.42, 1.1, 1.9),
    lampY: clamp((h - rise) * 0.58, 1.4, 5.0),
  };
}
