// Offline measurement rig. The engine is plain arithmetic over typed arrays,
// so the whole DSP layer can be driven and measured without a browser.

export const FS = 48000;

/** Deterministic noise, so a failing test fails the same way twice. */
export function rng(seed = 1234567) {
  let s = seed >>> 0;
  return () => {
    s ^= s << 13; s ^= s >>> 17; s ^= s << 5;
    return ((s >>> 0) / 4294967296) * 2 - 1;
  };
}

/** Constant-skirt bandpass, used to measure gains where the room model states them. */
export function bandpass(f0, q, fs = FS) {
  const w = (2 * Math.PI * f0) / fs;
  const alpha = Math.sin(w) / (2 * q);
  const b0 = alpha, b1 = 0, b2 = -alpha;
  const a0 = 1 + alpha, a1 = -2 * Math.cos(w), a2 = 1 - alpha;
  return { b0: b0 / a0, b1: b1 / a0, b2: b2 / a0, a1: a1 / a0, a2: a2 / a0, z1: 0, z2: 0 };
}

export function runBp(f, x) {
  const y = f.b0 * x + f.z1;
  f.z1 = f.b1 * x - f.a1 * y + f.z2;
  f.z2 = f.b2 * x - f.a2 * y;
  return y;
}

/**
 * Broadband power gain of the engine over a one-octave band at f0, measured by
 * driving it with band-limited noise and comparing settled RMS in and out.
 * Kept well below the output soft-clip so the measurement stays linear.
 */
export function bandGain(engine, f0, seconds, settle, amp = 0.02) {
  const r = rng();
  const bp1 = bandpass(f0, 1.2), bp2 = bandpass(f0, 1.2);
  const N = 256;
  const a = new Float32Array(N), b = new Float32Array(N);
  const oL = new Float32Array(N), oR = new Float32Array(N);
  const total = Math.round(FS * (seconds + settle));
  const skip = Math.round(FS * settle);
  let n = 0, accIn = 0, accOut = 0;
  while (n < total) {
    for (let i = 0; i < N; i++) {
      const v = runBp(bp2, runBp(bp1, r())) * amp;
      a[i] = v; b[i] = v;
    }
    engine.process(a, b, oL, oR, N);
    for (let i = 0; i < N; i++, n++) {
      if (n >= skip) { accIn += a[i] * a[i]; accOut += oL[i] * oL[i]; }
    }
  }
  return Math.sqrt(accOut / Math.max(accIn, 1e-30));
}

/** Impulse response of the left channel. */
export function impulseL(engine, seconds) {
  const n = Math.round(FS * seconds);
  const N = 128;
  const a = new Float32Array(N), b = new Float32Array(N);
  const oL = new Float32Array(N), oR = new Float32Array(N);
  const out = new Float32Array(n);
  let w = 0, first = true;
  while (w < n) {
    a.fill(0); b.fill(0);
    if (first) { a[0] = 1; b[0] = 1; first = false; }
    engine.process(a, b, oL, oR, N);
    for (let i = 0; i < N && w < n; i++, w++) out[w] = oL[i];
  }
  return out;
}

/** Schroeder-integrated decay time, extrapolated to 60 dB from a mid window. */
export function decayTime(ir, loDb = -5, hiDb = -35, fs = FS) {
  let acc = 0;
  const sch = new Float64Array(ir.length);
  for (let i = ir.length - 1; i >= 0; i--) { acc += ir[i] * ir[i]; sch[i] = acc; }
  if (acc <= 0) return NaN;
  const db = (i) => 10 * Math.log10(Math.max(sch[i] / acc, 1e-30));
  let a = -1, b = -1;
  for (let i = 0; i < sch.length; i++) {
    if (a < 0 && db(i) <= loDb) a = i;
    if (db(i) <= hiDb) { b = i; break; }
  }
  if (a < 0 || b < 0) return NaN;
  return ((b - a) / fs) * (60 / Math.abs(hiDb - loDb));
}

export const energy = (x) => { let s = 0; for (const v of x) s += v * v; return s; };
export const db = (x) => 20 * Math.log10(Math.max(Math.abs(x), 1e-30));
