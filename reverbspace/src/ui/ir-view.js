// The two read-outs under the room: what the mic receives over time, and how
// long each band takes to die away. Both are drawn straight from the model, so
// they move the instant anything in the room moves.

import { BANDS } from '../core/materials.js';

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const FLOOR_DB = -60;

function prepare(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, rect.width, rect.height);
  return { g, w: rect.width, h: rect.height };
}

const mono = '10px ui-monospace, SFMono-Regular, Menlo, monospace';

/**
 * Echogram: the direct sound, every early reflection at its true arrival time,
 * and the diffuse tail's envelope. This is the picture of the room's response.
 */
export function drawEchogram(canvas, response, accent) {
  const { g, w, h } = prepare(canvas);
  const pad = { l: 34, r: 10, t: 12, b: 20 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;

  const early = response.early;
  const lastEarly = early.length ? early[early.length - 1].delay : 0.05;
  const spanMs = clamp(Math.max(lastEarly, response.decay.mixingTime * 2.2) * 1000 * 1.15, 40, 600);

  const amp = (bands) => {
    let s = 0;
    for (const v of bands) s += Math.abs(v);
    return s / bands.length;
  };
  const peak = Math.max(amp(response.direct.left), ...early.map((t) => amp(t.left)), 1e-9);
  const toDb = (v) => 20 * Math.log10(Math.max(v, 1e-9) / peak);
  const x = (ms) => pad.l + (ms / spanMs) * plotW;
  const y = (dB) => pad.t + plotH * clamp(dB / FLOOR_DB, 0, 1);

  // Grid.
  g.strokeStyle = 'rgba(255,255,255,0.07)';
  g.fillStyle = 'rgba(255,255,255,0.32)';
  g.font = mono;
  g.lineWidth = 1;
  for (let dB = 0; dB >= FLOOR_DB; dB -= 20) {
    const yy = y(dB);
    g.beginPath(); g.moveTo(pad.l, yy); g.lineTo(w - pad.r, yy); g.stroke();
    g.fillText(`${dB}`, 8, yy + 3);
  }
  const msStep = spanMs > 300 ? 100 : spanMs > 120 ? 50 : 10;
  for (let ms = 0; ms <= spanMs; ms += msStep) {
    const xx = x(ms);
    g.strokeStyle = 'rgba(255,255,255,0.05)';
    g.beginPath(); g.moveTo(xx, pad.t); g.lineTo(xx, pad.t + plotH); g.stroke();
    g.fillText(`${ms}`, xx - 6, h - 6);
  }
  g.fillStyle = 'rgba(255,255,255,0.28)';
  g.fillText('ms', w - pad.r - 14, h - 6);

  // Diffuse tail envelope, starting where the reflections stop being countable.
  const rt = response.decay.midRt;
  const lateDb = toDb(amp(response.late.left));
  const onsetMs = Math.max(response.decay.mixingTime * 1000, early.length ? early[0].delay * 1000 : 0);
  g.beginPath();
  g.moveTo(x(onsetMs), y(0));
  let started = false;
  for (let ms = onsetMs; ms <= spanMs; ms += spanMs / 220) {
    const dB = lateDb - (60 * (ms - onsetMs)) / (rt * 1000);
    const yy = y(dB);
    if (!started) { g.moveTo(x(ms), yy); started = true; } else g.lineTo(x(ms), yy);
  }
  g.lineTo(x(spanMs), pad.t + plotH);
  g.lineTo(x(onsetMs), pad.t + plotH);
  g.closePath();
  const grad = g.createLinearGradient(0, pad.t, 0, pad.t + plotH);
  grad.addColorStop(0, hexA(accent, 0.32));
  grad.addColorStop(1, hexA(accent, 0.03));
  g.fillStyle = grad;
  g.fill();

  // Early reflections.
  for (const t of early) {
    const ms = t.delay * 1000;
    if (ms > spanMs) continue;
    const dB = toDb(amp(t.left));
    if (dB < FLOOR_DB) continue;
    g.strokeStyle = t.order === 1 ? hexA(accent, 0.95) : `rgba(255,255,255,${0.5 - t.order * 0.09})`;
    g.lineWidth = t.order === 1 ? 2 : 1;
    g.beginPath();
    g.moveTo(x(ms), pad.t + plotH);
    g.lineTo(x(ms), y(dB));
    g.stroke();
  }

  // Direct sound.
  const dMs = response.direct.delay * 1000;
  g.strokeStyle = '#ffffff';
  g.lineWidth = 2.5;
  g.beginPath();
  g.moveTo(x(dMs), pad.t + plotH);
  g.lineTo(x(dMs), y(0));
  g.stroke();

  g.fillStyle = 'rgba(255,255,255,0.75)';
  g.font = mono;
  g.fillText('direct', x(dMs) + 4, pad.t + 9);
  const gapMs = response.firstReflectionGap * 1000;
  if (gapMs > 0.4 && early.length) {
    g.fillStyle = hexA(accent, 0.8);
    g.fillText(`+${gapMs.toFixed(1)} ms to 1st reflection`, x(dMs) + 4, pad.t + 22);
  }
}

/** Reverberation time per octave band, which is the shape of the room's decay. */
export function drawDecay(canvas, response, accent) {
  const { g, w, h } = prepare(canvas);
  const pad = { l: 34, r: 10, t: 12, b: 20 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const rt = response.decay.rt60;
  const top = Math.max(0.6, Math.ceil(Math.max(...rt) * 1.15 * 2) / 2);

  g.strokeStyle = 'rgba(255,255,255,0.07)';
  g.fillStyle = 'rgba(255,255,255,0.32)';
  g.font = mono;
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const v = (top * i) / ticks;
    const yy = pad.t + plotH * (1 - i / ticks);
    g.beginPath(); g.moveTo(pad.l, yy); g.lineTo(w - pad.r, yy); g.stroke();
    g.fillText(top >= 4 ? v.toFixed(0) : v.toFixed(1), 6, yy + 3);
  }

  const bw = plotW / BANDS.length;
  for (let i = 0; i < BANDS.length; i++) {
    const v = rt[i];
    const bh = plotH * clamp(v / top, 0, 1);
    const x = pad.l + i * bw + bw * 0.18;
    const bwi = bw * 0.64;
    const grad = g.createLinearGradient(0, pad.t + plotH - bh, 0, pad.t + plotH);
    grad.addColorStop(0, hexA(accent, 0.95));
    grad.addColorStop(1, hexA(accent, 0.30));
    g.fillStyle = grad;
    g.fillRect(x, pad.t + plotH - bh, bwi, bh);

    g.fillStyle = 'rgba(255,255,255,0.8)';
    g.font = mono;
    const label = v >= 10 ? v.toFixed(0) : v.toFixed(v < 1 ? 2 : 1);
    g.fillText(label, x + bwi / 2 - 8, pad.t + plotH - bh - 4);

    g.fillStyle = 'rgba(255,255,255,0.4)';
    const hz = BANDS[i] >= 1000 ? `${BANDS[i] / 1000}k` : `${BANDS[i]}`;
    g.fillText(hz, x + bwi / 2 - 6, h - 6);
  }
  g.fillStyle = 'rgba(255,255,255,0.28)';
  g.fillText('s', 6, pad.t - 2);
}

function hexA(hex, a) {
  const s = hex.replace('#', '');
  const n = parseInt(s.length === 3 ? s.split('').map((c) => c + c).join('') : s, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
