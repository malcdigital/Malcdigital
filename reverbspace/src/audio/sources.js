// Test signals, synthesised so the plugin has something to play with no assets
// to ship. Transients on purpose: a reverb only shows itself on transients.

const TAU = Math.PI * 2;

function noise(seed) {
  let s = seed >>> 0;
  return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) / 4294967296) * 2 - 1; };
}

/** One-pole bandpass-ish shaping, enough to give each hit its own colour. */
function shape(buf, lowCut, highCut, fs) {
  const a = Math.exp((-TAU * highCut) / fs);
  const b = Math.exp((-TAU * lowCut) / fs);
  let lp = 0, hp = 0;
  for (let i = 0; i < buf.length; i++) {
    lp += (1 - a) * (buf[i] - lp);
    hp += (1 - b) * (lp - hp);
    buf[i] = lp - hp;
  }
}

function clap(ctx) {
  const fs = ctx.sampleRate;
  const buf = ctx.createBuffer(1, Math.round(fs * 0.5), fs);
  const d = buf.getChannelData(0);
  const rnd = noise(7);
  // Three slaps a few milliseconds apart, the way two hands actually sound.
  for (const [offset, level] of [[0, 0.6], [0.011, 0.8], [0.024, 1.0]]) {
    const start = Math.round(offset * fs);
    const len = Math.round(fs * (level === 1 ? 0.16 : 0.03));
    for (let i = 0; i < len && start + i < d.length; i++) {
      d[start + i] += rnd() * level * Math.exp((-i / fs) * (level === 1 ? 34 : 220));
    }
  }
  shape(d, 420, 6000, fs);
  return buf;
}

function snare(ctx) {
  const fs = ctx.sampleRate;
  const buf = ctx.createBuffer(1, Math.round(fs * 0.6), fs);
  const d = buf.getChannelData(0);
  const rnd = noise(31);
  for (let i = 0; i < d.length; i++) {
    const t = i / fs;
    const env = Math.exp(-t * 19);
    d[i] = (rnd() * 0.7 + Math.sin(TAU * 185 * t) * 0.5 + Math.sin(TAU * 331 * t) * 0.25) * env;
  }
  shape(d, 180, 8000, fs);
  return buf;
}

function pluck(ctx) {
  const fs = ctx.sampleRate;
  const buf = ctx.createBuffer(1, Math.round(fs * 1.6), fs);
  const d = buf.getChannelData(0);
  // Karplus-Strong: a plucked string is a noise burst chasing its own tail.
  const f0 = 196;
  const len = Math.round(fs / f0);
  const line = new Float32Array(len);
  const rnd = noise(97);
  for (let i = 0; i < len; i++) line[i] = rnd();
  let p = 0, last = 0;
  for (let i = 0; i < d.length; i++) {
    const v = line[p];
    const next = (v + last) * 0.5 * 0.9965;
    line[p] = next;
    last = v;
    p = (p + 1) % len;
    d[i] = v * Math.exp(-i / fs * 0.9);
  }
  shape(d, 90, 9000, fs);
  return buf;
}

function voice(ctx) {
  const fs = ctx.sampleRate;
  const buf = ctx.createBuffer(1, Math.round(fs * 0.9), fs);
  const d = buf.getChannelData(0);
  // A sung "ah": a glottal buzz through three formants.
  const f0 = 155;
  const formants = [[720, 1.0], [1240, 0.5], [2560, 0.22]];
  for (let i = 0; i < d.length; i++) {
    const t = i / fs;
    const env = Math.min(1, t * 22) * Math.exp(-Math.max(0, t - 0.35) * 7);
    let v = 0;
    for (let h = 1; h < 30; h++) {
      const f = f0 * h;
      if (f > fs * 0.45) break;
      let amp = 1 / h;
      for (const [cf, w] of formants) amp += (w * 0.5) / (1 + Math.pow((f - cf) / 110, 2));
      v += Math.sin(TAU * f * t + h) * amp;
    }
    d[i] = v * env * 0.05;
  }
  return buf;
}

function loop(ctx) {
  const fs = ctx.sampleRate;
  const bpm = 96;
  const beat = 60 / bpm;
  const bars = 2;
  const buf = ctx.createBuffer(1, Math.round(fs * beat * 4 * bars), fs);
  const d = buf.getChannelData(0);
  const rnd = noise(13);
  const add = (at, fn, len) => {
    const s = Math.round(at * fs);
    for (let i = 0; i < len && s + i < d.length; i++) d[s + i] += fn(i / fs, i);
  };
  const kick = (t) => Math.sin(TAU * (58 + 90 * Math.exp(-t * 40)) * t) * Math.exp(-t * 9);
  const hat = (t) => rnd() * Math.exp(-t * 130) * 0.25;
  const snr = (t) => (rnd() * 0.7 + Math.sin(TAU * 190 * t) * 0.4) * Math.exp(-t * 22);
  for (let bar = 0; bar < bars; bar++) {
    const b0 = bar * beat * 4;
    add(b0, kick, fs * 0.4);
    add(b0 + beat * 1.5, kick, fs * 0.4);
    add(b0 + beat, snr, fs * 0.4);
    add(b0 + beat * 3, snr, fs * 0.4);
    for (let e = 0; e < 8; e++) add(b0 + e * beat * 0.5, hat, fs * 0.08);
  }
  let peak = 0;
  for (const v of d) peak = Math.max(peak, Math.abs(v));
  if (peak > 0) for (let i = 0; i < d.length; i++) d[i] /= peak * 1.2;
  return buf;
}

export const TEST_SOURCES = [
  { id: 'clap', name: 'Clap', build: clap, loops: false, blurb: 'One transient. The cleanest way to hear a room.' },
  { id: 'snare', name: 'Snare', build: snare, loops: false, blurb: 'Broadband hit with a bit of body.' },
  { id: 'pluck', name: 'Pluck', build: pluck, loops: false, blurb: 'Sustained tone, shows the tail under a note.' },
  { id: 'voice', name: 'Voice', build: voice, loops: false, blurb: 'Where proximity effect and mic tone show up.' },
  { id: 'loop', name: 'Drum loop', build: loop, loops: true, blurb: 'Continuous, for judging the wash.' },
];

/** Build every test buffer once, on the context that will play them. */
export function buildTestSources(ctx) {
  const out = new Map();
  for (const s of TEST_SOURCES) out.set(s.id, s.build(ctx));
  return out;
}
