// Turns a room analysis into ready-to-run DSP coefficients: a tap list for the
// early reflections, and delay lengths plus feedback filters for the tail.
//
// Everything a filter needs is worked out here, once per parameter change, so
// the per-sample code in reverb-engine.js stays a tight loop.

import { BANDS } from '../core/materials.js';
import { primeAtMost, onePole, onePoleMag } from './filters.js';
import { roomModes } from '../core/modes.js';

const LOW_SHELF_HZ = 250;
const HIGH_SHELF_HZ = 3000;
const LINES = 16;
const MAX_MODES = 16;
// Calibrated against the tail-level test: enough ring to hear the room's note,
// not so much that the low band overshoots the diffuse field it belongs to.
const MODE_LEVEL = 9.0;

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/**
 * Energy of the delay network's impulse response, per channel, normalised as
 *
 *     sum(h^2) = FDN_ENERGY * (tau * fs) / sum(lineLengths)
 *
 * which is what falls out of the diffuse-field picture: the network holds
 * energy decaying as exp(-2t/tau), spread over sum(lineLengths) stored
 * samples, and the output taps a unit-norm slice of it every sample. That
 * argument predicts 0.5; the shortfall is high-frequency loss in the damping
 * filters and in the modulated lines' interpolation.
 *
 * Measured in one-octave bands at 500/1k/2k -- where a tail is actually
 * judged -- rather than broadband, since white noise carries half its power
 * above 12 kHz and would weight the measurement almost entirely on the part of
 * the spectrum the network rolls off. It holds to about +/-0.6 dB from a vocal
 * booth to a scaled-up cathedral. tests/engine.test.js re-measures it, so the
 * tail level cannot silently drift off the room model.
 */
export const FDN_ENERGY = 0.416;

/**
 * Reduce a six-band gain vector to a broadband gain plus two first-order
 * shelves. Keeps the sign, so a figure-8's rear lobe stays polarity-inverted.
 */
export function fitBands(bands) {
  let ref = bands[3];
  if (Math.abs(ref) < 1e-9) {
    // Nulled at 1 kHz (a pattern null): fall back to whichever band is loudest.
    let best = 0;
    for (let i = 0; i < bands.length; i++) if (Math.abs(bands[i]) > Math.abs(bands[best])) best = i;
    ref = bands[best];
  }
  if (Math.abs(ref) < 1e-12) return { gain: 0, low: 1, high: 1 };
  const mag = Math.abs(ref);
  return {
    gain: ref,
    low: clamp(Math.abs(bands[0]) / mag, 0.02, 8),
    high: clamp(Math.abs(bands[5]) / mag, 0.02, 8),
  };
}

/**
 * The room's discrete resonances, as a bank of two-pole resonators.
 *
 * A feedback delay network makes a smooth tail by construction -- that is the
 * whole point of one -- so it cannot produce the separate, audible modes a
 * small room has below its Schroeder frequency. Those are the boxy ring you
 * cannot mix your way out of, and they are most of why a booth sounds like a
 * booth. Each one is rendered as what it is: a resonance at the mode's own
 * frequency, decaying at the reverberation time for that frequency, at the
 * level the standing wave reaches between the performer and the mic.
 *
 * All-pole, normalised to unit peak gain. The obvious form -- a zero at DC and
 * one at Nyquist -- turns out to be wrong here: those zeros lift the skirt by
 * 6 dB an octave, leaving only 6 dB of roll-off above resonance instead of 12,
 * and sixteen such skirts sum coherently three octaves up. That put three
 * decibels of extra tail at 500 Hz in a room whose highest mode is at 171.
 * DC is dealt with once, on the sum, rather than sixteen times.
 */
function designModes(response, fs, level) {
  const modes = roomModes(response.state, response.decay, MAX_MODES);
  if (!modes.length) return [];
  // Share the level out over however many are ringing, so a room with twenty
  // modes does not come out twenty times louder than a room with two.
  const spread = level * MODE_LEVEL / Math.sqrt(modes.length);
  return modes.map((m) => {
    // A resonance that decays 60 dB in rt has this half-power bandwidth.
    const bw = clamp(2.2 / m.rt, 0.4, 60);
    const r = Math.exp((-Math.PI * bw) / fs);
    const w = (2 * Math.PI * m.f) / fs;
    return {
      a1: 2 * r * Math.cos(w),
      a2: -(r * r),
      b0: (1 - r) * Math.sqrt(1 - 2 * r * Math.cos(2 * w) + r * r) * m.gain * spread,
      freq: m.f,
    };
  });
}

/** Sign patterns for feeding and tapping the delay network. */
function hadamardRow(row, n) {
  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    let bits = row & i, parity = 0;
    while (bits) { parity ^= bits & 1; bits >>= 1; }
    out[i] = parity ? -1 : 1;
  }
  return out;
}

/**
 * @param {object} response  output of acoustics.analyze()
 * @param {number} sampleRate
 * @param {object} opts      player-facing controls layered on top of the physics
 */
export function designReverb(response, sampleRate, opts = {}) {
  const {
    decayScale = 1,
    predelayMs = 0,
    earlyLevel = 1,
    tailLevel = 1,
    width = 1,
  } = opts;

  const fs = sampleRate;
  const { decay, direct, early, late } = response;

  // --- direct path --------------------------------------------------------
  const dl = fitBands(direct.left);
  const dr = fitBands(direct.right);
  const directDesign = {
    delaySamples: direct.delay * fs,
    gainL: dl.gain,
    gainR: dr.gain,
    low: (dl.low + dr.low) / 2,
    high: (dl.high + dr.high) / 2,
  };

  // --- early reflections --------------------------------------------------
  const predelaySamples = Math.max(0, predelayMs) * 0.001 * fs;
  const earlyDesign = early.map((tap) => {
    const l = fitBands(tap.left);
    const r = fitBands(tap.right);
    const mid = (l.gain + r.gain) / 2;
    return {
      delaySamples: tap.delay * fs + predelaySamples,
      gainL: (mid + (l.gain - mid) * width) * earlyLevel,
      gainR: (mid + (r.gain - mid) * width) * earlyLevel,
      low: (l.low + r.low) / 2,
      high: (l.high + r.high) / 2,
      order: tap.order,
    };
  });

  // --- the tail -----------------------------------------------------------
  const rt60 = decay.rt60.map((t) => clamp(t * decayScale, 0.05, 40));
  // Quantised in 2% steps: dragging the size slider should not re-tune the
  // delay lines sixty times a second.
  const tMfp = Math.exp(Math.round(Math.log(decay.meanFreePath / 343) * 50) / 50);
  const tMin = clamp(tMfp * 0.42, 0.0045, 0.085);
  const tMax = clamp(tMfp * 1.75, tMin * 2.2, 0.185);

  // How much of each shelf is still active at the 1 kHz reference.
  const lowAt1k = onePoleMag(onePole(LOW_SHELF_HZ, fs), 1000, fs);
  const highAt1k = onePoleMag(onePole(HIGH_SHELF_HZ, fs), 1000, fs);

  const inSigns = hadamardRow(1, LINES);
  const outLSigns = hadamardRow(2, LINES);
  const outRSigns = hadamardRow(5, LINES);
  const norm = 1 / Math.sqrt(LINES);

  const lines = [];
  for (let i = 0; i < LINES; i++) {
    const t = tMin * Math.pow(tMax / tMin, i / (LINES - 1));
    const length = primeAtMost(t * fs);
    const gainFor = (band) => Math.pow(10, (-3 * length) / (fs * rt60[band]));
    const gMidRaw = gainFor(3);
    const lowRatio = clamp(gainFor(0) / gMidRaw, 0.05, 20);
    const highRatio = clamp(gainFor(5) / gMidRaw, 0.02, 4);
    // The shelves are first-order, so their skirts still tilt 1 kHz. Divide
    // that bleed back out, or the mid-band tail comes up short of the room's
    // actual reverberation time.
    const bleed = (1 + (lowRatio - 1) * lowAt1k) * (1 + (highRatio - 1) * (1 - highAt1k));
    // The shelves multiply the mid gain, so cap on the loudest band or the
    // network will not decay.
    const peak = Math.max(1, lowRatio, highRatio);
    const gMid = Math.min(gMidRaw / bleed, 0.9995 / peak);
    lines.push({
      length,
      gMid,
      lowRatio,
      highRatio,
      modDepth: clamp(fs * 0.00006 * (1 + tMfp * 6), 1.5, 14),
      modRate: 0.09 + (i * 0.037) % 0.54,
      modPhase: (i * 2.39996) % (Math.PI * 2),
      inGain: inSigns[i] * norm,
      outL: outLSigns[i] * norm,
      outR: outRSigns[i] * norm,
    });
  }

  // Input diffusion, scaled with the room so a small booth does not get a
  // cathedral's smear.
  const sizeScale = clamp(tMfp / 0.02, 0.3, 3.2);
  const scatter = response.surfaces.walls.scatter;
  const apCoef = clamp(0.55 + scatter * 0.28, 0.4, 0.78);
  const diffusers = [4.7, 3.6, 12.7, 9.3].map((ms) => ({
    length: primeAtMost(ms * 0.001 * sizeScale * fs),
    coef: apCoef,
  }));

  // Level the tail so its steady-state gain matches the diffuse field the room
  // model predicts. FDN_ENERGY is the measured energy constant of the network
  // (see tests/engine.test.js, which fails if it drifts).
  const lateFit = fitBands(late.left);
  const tau = rt60[3] / 6.907755;
  const sumL = lines.reduce((acc, l) => acc + l.length, 0);
  const scale = lateFit.gain / Math.sqrt((FDN_ENERGY * tau * fs) / sumL);
  const lateDelay = Math.min(early.length ? early[0].delay : decay.mixingTime, decay.mixingTime);

  return {
    sampleRate: fs,
    direct: directDesign,
    early: earlyDesign,
    late: {
      predelaySamples: Math.max(0, lateDelay * fs + predelaySamples),
      lines,
      diffusers,
      gainL: scale * tailLevel,
      gainR: scale * tailLevel,
      low: lateFit.low,
      high: lateFit.high,
      // Hand the bottom to the modes. Well below the Schroeder frequency the
      // field is not diffuse and the delay network has no business pretending
      // otherwise; leaving both in would just sum two accounts of the same
      // energy. Kept under the lowest octave band the surface model describes,
      // so this only clears the region the band model never reached.
      highPassHz: response.decay.schroeder > 40 ? clamp(response.decay.schroeder * 0.55, 20, 75) : 0,
      width,
    },
    modes: designModes(response, fs, tailLevel * scale),
    micToneDb: response.micTone.slice(),
    proximityDb: response.proximity.slice(),
    shelfHz: { low: LOW_SHELF_HZ, high: HIGH_SHELF_HZ },
    bands: BANDS.slice(),
    meta: {
      rt60,
      tapCount: earlyDesign.length,
      maxDelaySeconds: Math.max(
        directDesign.delaySamples,
        ...earlyDesign.map((t) => t.delaySamples),
        predelaySamples + lateDelay * fs,
      ) / fs,
    },
  };
}

