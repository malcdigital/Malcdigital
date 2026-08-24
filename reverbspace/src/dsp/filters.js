// Filter primitives and the design maths that turns per-band targets into
// coefficients. Pure arithmetic, no audio-graph objects, so it ports.

const TAU = Math.PI * 2;

/** One-pole lowpass coefficient with unity DC gain: y += (1-a)*(x - y). */
export function onePole(fc, fs) {
  const a = Math.exp(-TAU * Math.max(1, Math.min(fc, fs * 0.49)) / fs);
  return Math.max(0, Math.min(a, 0.9999));
}

/** Magnitude of a one-pole lowpass (1-a)/(1 - a z^-1) at frequency f. */
export function onePoleMag(a, f, fs) {
  const w = (TAU * f) / fs;
  const re = 1 - a * Math.cos(w);
  const im = a * Math.sin(w);
  return (1 - a) / Math.hypot(re, im);
}

/**
 * Find the one-pole cutoff whose response at fRef is `ratio` (0..1).
 * Bisection: monotonic in a, so it always converges.
 */
export function dampingCoefFor(ratio, fRef, fs) {
  const r = Math.max(1e-4, Math.min(ratio, 0.9999));
  let lo = 0, hi = 0.99999;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    if (onePoleMag(mid, fRef, fs) > r) lo = mid; else hi = mid;
  }
  return (lo + hi) / 2;
}

/**
 * A first-order shelf built from a one-pole: H = 1 + (gain-1)*LP for a low
 * shelf, or 1 + (gain-1)*(1-LP) for a high shelf. Unity in the other half of
 * the spectrum, which is what makes shelves stackable without book-keeping.
 */
export function makeShelf(kind, gain, fc, fs) {
  return { a: onePole(fc, fs), k: gain - 1, high: kind === 'high', z: 0 };
}

export function resetShelf(s) { s.z = 0; }

export function runShelf(s, x) {
  s.z += (1 - s.a) * (x - s.z);
  return s.high ? x + s.k * (x - s.z) : x + s.k * s.z;
}

// --- biquads ---------------------------------------------------------------

/** RBJ peaking EQ. Returns normalised coefficients plus its own state. */
export function peakingBiquad(freq, gainDb, q, fs) {
  const A = Math.pow(10, gainDb / 40);
  const w0 = (TAU * Math.min(freq, fs * 0.45)) / fs;
  const alpha = Math.sin(w0) / (2 * q);
  const cw = Math.cos(w0);
  const a0 = 1 + alpha / A;
  return {
    b0: (1 + alpha * A) / a0,
    b1: (-2 * cw) / a0,
    b2: (1 - alpha * A) / a0,
    a1: (-2 * cw) / a0,
    a2: (1 - alpha / A) / a0,
    x1: 0, x2: 0, y1: 0, y2: 0,
  };
}

export function resetBiquad(b) { b.x1 = b.x2 = b.y1 = b.y2 = 0; }

export function runBiquad(b, x) {
  const y = b.b0 * x + b.b1 * b.x1 + b.b2 * b.x2 - b.a1 * b.y1 - b.a2 * b.y2;
  b.x2 = b.x1; b.x1 = x;
  b.y2 = b.y1; b.y1 = y;
  return y;
}

/** Magnitude response of a biquad at f, in dB. */
export function biquadMagDb(b, f, fs) {
  const w = (TAU * f) / fs;
  const cw = Math.cos(w), sw = Math.sin(w);
  const c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
  const nr = b.b0 + b.b1 * cw + b.b2 * c2;
  const ni = -(b.b1 * sw + b.b2 * s2);
  const dr = 1 + b.a1 * cw + b.a2 * c2;
  const di = -(b.a1 * sw + b.a2 * s2);
  return 20 * Math.log10(Math.hypot(nr, ni) / Math.max(1e-12, Math.hypot(dr, di)));
}

/**
 * Fit a cascade of peaking filters to a per-band dB target. Neighbouring bands
 * bleed into each other, so nudge the gains a few times until the cascade
 * actually measures what was asked for at the band centres.
 */
export function designBandEQ(freqs, targetDb, fs, q = 1.2, iterations = 6) {
  const gains = targetDb.slice();
  let filters = [];
  for (let it = 0; it < iterations; it++) {
    filters = freqs.map((f, i) => peakingBiquad(f, gains[i], q, fs));
    for (let i = 0; i < freqs.length; i++) {
      let achieved = 0;
      for (const b of filters) achieved += biquadMagDb(b, freqs[i], fs);
      gains[i] += (targetDb[i] - achieved) * 0.8;
      gains[i] = Math.max(-40, Math.min(40, gains[i]));
    }
  }
  return freqs.map((f, i) => peakingBiquad(f, gains[i], q, fs));
}

/** Largest prime <= n, used to keep delay-line lengths mutually incommensurate. */
export function primeAtMost(n) {
  let v = Math.max(2, Math.floor(n));
  const isPrime = (x) => {
    if (x < 2) return false;
    if (x % 2 === 0) return x === 2;
    for (let i = 3; i * i <= x; i += 2) if (x % i === 0) return false;
    return true;
  };
  while (v > 2 && !isPrime(v)) v--;
  return v;
}
