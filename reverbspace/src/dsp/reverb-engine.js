// The reverb itself. Three parallel paths, all fed from one input delay line:
//
//   direct   - one tap, the performer heard straight, shelved and level-set
//   early    - up to 64 taps, one per image source, panned per capsule
//   late     - a 16-line feedback delay network for the diffuse tail
//
// Plain arithmetic over typed arrays. No Web Audio types appear anywhere in
// this file, which is what makes it portable to a native plugin.

import { onePole, designBandEQ, runBiquad, resetBiquad } from './filters.js';

const LINES = 16;
const FADE_SECONDS = 0.045;   // early/direct crossfade on a parameter change
const DIP_SECONDS = 0.006;    // tail dip when the delay lines are re-tuned

const nextPow2 = (n) => { let v = 1; while (v < n) v <<= 1; return v; };
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/**
 * Read a delay line `delay` samples back, 4-point Lagrange.
 *
 * The direct sound and the early reflections land on arbitrary fractional
 * delays, and linear interpolation loses up to 3 dB of top end at the halfway
 * point -- audible as the performer dulling in and out as they move. There are
 * only ~65 of these taps, so they can afford the cubic. Requires delay >= 2.
 */
function readLagrange(buf, mask, wp, delay) {
  const pos = wp - delay;
  const i = Math.floor(pos);
  const d = pos - i;
  const y0 = buf[(i - 1) & mask], y1 = buf[i & mask];
  const y2 = buf[(i + 1) & mask], y3 = buf[(i + 2) & mask];
  const dm1 = d - 1, dm2 = d - 2, dp1 = d + 1;
  return (-d * dm1 * dm2 / 6) * y0
       + (dp1 * dm1 * dm2 / 2) * y1
       + (-dp1 * d * dm2 / 2) * y2
       + (dp1 * d * dm1 / 6) * y3;
}

/** Read a delay line `delay` samples back from the write pointer, linear. */
function readInterp(buf, mask, wp, delay) {
  const pos = wp - delay;
  const i0 = Math.floor(pos);
  const frac = pos - i0;
  const a = buf[i0 & mask];
  const b = buf[(i0 + 1) & mask];
  return a + (b - a) * frac;
}

/** In-place fast Walsh-Hadamard transform, orthonormalised. */
function hadamard16(s) {
  for (let len = 1; len < LINES; len <<= 1) {
    for (let i = 0; i < LINES; i += len << 1) {
      for (let j = i; j < i + len; j++) {
        const a = s[j], b = s[j + len];
        s[j] = a + b;
        s[j + len] = a - b;
      }
    }
  }
  for (let i = 0; i < LINES; i++) s[i] *= 0.25;
}

function makeTapBank(taps, mask, fs) {
  return taps
    .filter((t) => t.delaySamples < mask - 4 && Number.isFinite(t.gainL))
    .map((t) => ({
      delay: Math.max(2, t.delaySamples),
      gainL: t.gainL,
      gainR: t.gainR,
      lowA: onePole(250, fs),
      highA: onePole(3000, fs),
      lowK: t.low - 1,
      highK: t.high - 1,
      zl: 0,
      zh: 0,
    }));
}

export class ReverbEngine {
  constructor(sampleRate, maxDelaySeconds = 2.0) {
    this.fs = sampleRate;
    this.fadeSamples = Math.max(1, Math.round(FADE_SECONDS * sampleRate));
    this.dipSamples = Math.max(1, Math.round(DIP_SECONDS * sampleRate));

    const n = nextPow2(sampleRate * maxDelaySeconds);
    this.buf = new Float32Array(n);
    this.mask = n - 1;
    this.wp = 0;

    // Early/direct: two banks, crossfaded when the design changes.
    this.bankA = null;
    this.bankB = null;
    this.directA = null;
    this.directB = null;
    this.fade = 1;
    this.fadeStep = 0;

    // Tail.
    this.lines = [];
    this.lineBufs = [];
    this.lineMasks = [];
    this.lineWp = [];
    this.scratch = new Float64Array(LINES);
    this.diffusers = [];
    this.lateDelay = 0;
    this.lateGainL = 0;
    this.lateGainR = 0;
    this.lateLowK = 0;
    this.lateHighK = 0;
    this.shelfLowA = onePole(250, sampleRate);
    this.shelfHighA = onePole(3000, sampleRate);
    this.lateZl = [0, 0];
    this.lateZh = [0, 0];
    // The room's own resonances, below the frequency where they stop
    // overlapping. Mono: a mode is a pressure field and the mic is one point
    // in it, so there is nothing to be wide about.
    this.modes = [];
    this.modeDcX = 0;
    this.modeDcY = 0;
    this.modeLpA = 0;
    this.modeLpZ = [0, 0];
    // One-pole high-pass on the tail, so the delay network stops competing
    // with the modes for the bottom end.
    this.lateHpA = 0;
    this.lateHpX = [0, 0];
    this.lateHpY = [0, 0];
    this.width = 1;

    this.dip = 1;
    this.dipDir = 0;
    this.pendingLines = null;
    this.pendingDesign = null;

    // Output conditioning.
    this.toneL = [];
    this.toneR = [];
    this.proxL = [];
    this.proxR = [];
    this.dcZ = [0, 0];
    this.dcY = [0, 0];

    this.mix = 1;
    this.output = 1;
    this.roomOnly = false;
    this.bypass = false;
    this.ready = false;
    /** Peak absolute output of the last processed block, for the meters. */
    this.peak = 0;
  }

  setControls({ mix, output, roomOnly, bypass, width } = {}) {
    if (mix !== undefined) this.mix = clamp(mix, 0, 1);
    if (output !== undefined) this.output = clamp(output, 0, 4);
    if (roomOnly !== undefined) this.roomOnly = !!roomOnly;
    if (bypass !== undefined) this.bypass = !!bypass;
    if (width !== undefined) this.width = clamp(width, 0, 1.5);
  }

  setDesign(design) {
    // Dragging the mic across the room sends a new design every animation
    // frame, which is faster than the crossfade can finish. Restarting the fade
    // from zero mid-flight snaps the output back to the old bank and clicks, so
    // hold the newest design and take it up once the current one has landed.
    if (this.ready && (this.fadeStep > 0 || this.pendingLines || this.dipDir !== 0)) {
      this.pendingDesign = design;
      return;
    }
    const fs = this.fs;

    // --- early + direct: crossfade into the new tap bank -------------------
    const bank = makeTapBank(design.early, this.mask, fs);
    const direct = {
      delay: Math.max(2, Math.min(design.direct.delaySamples, this.mask - 4)),
      gainL: design.direct.gainL,
      gainR: design.direct.gainR,
      lowA: onePole(250, fs),
      highA: onePole(3000, fs),
      lowK: design.direct.low - 1,
      highK: design.direct.high - 1,
      zl: 0,
      zh: 0,
    };
    if (!this.ready) {
      this.bankA = bank;
      this.directA = direct;
      this.fade = 1;
      this.fadeStep = 0;
    } else {
      this.bankB = bank;
      this.directB = direct;
      this.fade = 0;
      this.fadeStep = 1 / this.fadeSamples;
    }

    // --- tail --------------------------------------------------------------
    const lengths = design.late.lines.map((l) => l.length);
    const retune = this.lines.length !== LINES
      || lengths.some((len, i) => len !== this.lines[i].length);

    if (retune) {
      if (!this.ready) {
        this.applyLines(design.late.lines);
      } else {
        // Dip the tail for a few milliseconds so the read-pointer jump does not
        // click, then swap the lengths in.
        this.pendingLines = design.late.lines;
        this.dipDir = -1;
      }
    } else {
      // Same geometry, different absorption: gains and filters can change in
      // place, inaudibly.
      for (let i = 0; i < LINES; i++) {
        const src = design.late.lines[i];
        Object.assign(this.lines[i], {
          gMid: src.gMid, lowRatio: src.lowRatio, highRatio: src.highRatio,
          modDepth: src.modDepth, inGain: src.inGain, outL: src.outL, outR: src.outR,
        });
      }
    }

    if (this.diffusers.length !== design.late.diffusers.length
        || design.late.diffusers.some((d, i) => this.diffusers[i]?.length !== d.length)) {
      this.diffusers = design.late.diffusers.map((d) => {
        const n = nextPow2(d.length + 4);
        return { buf: new Float32Array(n), mask: n - 1, wp: 0, length: d.length, coef: d.coef };
      });
    } else {
      design.late.diffusers.forEach((d, i) => { this.diffusers[i].coef = d.coef; });
    }

    // Retuning a resonator mid-ring is a click, so each new one keeps the
    // state of whichever old one was nearest in frequency and carries its
    // ring on rather than restarting it.
    const wasRinging = this.modes;
    this.modes = (design.modes || []).map((m) => {
      let near = null, best = Infinity;
      for (const o of wasRinging) {
        const gap = Math.abs(Math.log2(o.freq / m.freq));
        if (gap < best) { best = gap; near = o; }
      }
      const keep = near && best < 0.5;
      return { ...m, z1: keep ? near.z1 : 0, z2: keep ? near.z2 : 0 };
    });

    this.lateDelay = clamp(design.late.predelaySamples, 1, this.mask - 4);
    this.lateGainL = design.late.gainL;
    this.lateGainR = design.late.gainR;
    // The shelf corners are fitted to the room, not fixed: the design says
    // where they go and the engine had been ignoring it.
    this.shelfLowA = onePole(design.shelfHz ? design.shelfHz.low : 250, fs);
    this.shelfHighA = onePole(design.shelfHz ? design.shelfHz.high : 3000, fs);
    this.lateLowK = design.late.low - 1;
    this.lateHighK = design.late.high - 1;
    this.modeLpA = design.modeLowPass || 0;
    const hp = design.late.highPassHz || 0;
    this.lateHpA = hp > 0 ? 1 / (1 + (2 * Math.PI * hp) / fs) : 0;

    // Mic tone across everything the capsule hears; proximity on the direct
    // path only, because that is where the near-field lift actually happens.
    this.toneL = designBandEQ(design.bands, design.micToneDb, fs);
    this.toneR = designBandEQ(design.bands, design.micToneDb, fs);
    this.proxL = designBandEQ(design.bands, design.proximityDb, fs);
    this.proxR = designBandEQ(design.bands, design.proximityDb, fs);

    this.design = design;
    this.ready = true;
  }

  applyLines(lineDesigns) {
    const grow = this.lines.length !== LINES;
    if (grow) {
      this.lines = [];
      this.lineBufs = [];
      this.lineMasks = [];
      this.lineWp = [];
    }
    for (let i = 0; i < LINES; i++) {
      const src = lineDesigns[i];
      const need = nextPow2(src.length + Math.ceil(src.modDepth) + 8);
      if (!this.lineBufs[i] || this.lineBufs[i].length < need) {
        this.lineBufs[i] = new Float32Array(need);
        this.lineMasks[i] = need - 1;
        this.lineWp[i] = 0;
      }
      const prev = this.lines[i];
      this.lines[i] = {
        ...src,
        zl: prev ? prev.zl : 0,
        zh: prev ? prev.zh : 0,
        osc: prev ? prev.osc : Math.cos(src.modPhase),
        oscQ: prev ? prev.oscQ : Math.sin(src.modPhase),
        ca: Math.cos((2 * Math.PI * src.modRate) / this.fs),
        sa: Math.sin((2 * Math.PI * src.modRate) / this.fs),
      };
    }
  }

  reset() {
    this.buf.fill(0);
    this.wp = 0;
    for (const b of this.lineBufs) b?.fill(0);
    for (const l of this.lines) { l.zl = 0; l.zh = 0; }
    for (const d of this.diffusers) d.buf.fill(0);
    for (const bank of [this.bankA, this.bankB]) {
      if (bank) for (const t of bank) { t.zl = 0; t.zh = 0; }
    }
    for (const d of [this.directA, this.directB]) if (d) { d.zl = 0; d.zh = 0; }
    for (const b of [...this.toneL, ...this.toneR, ...this.proxL, ...this.proxR]) resetBiquad(b);
    this.lateZl = [0, 0];
    this.lateZh = [0, 0];
    for (const m of this.modes) { m.z1 = 0; m.z2 = 0; }
    this.modeDcX = 0;
    this.modeDcY = 0;
    this.modeLpZ = [0, 0];
    this.lateHpX = [0, 0];
    this.lateHpY = [0, 0];
    this.dcZ = [0, 0];
    this.dcY = [0, 0];
    this.peak = 0;
  }

  /**
   * Run one tap bank plus its direct tap. Writes [earlyL, earlyR, directL,
   * directR] into `out` -- the direct sound stays separate so the proximity
   * lift can be applied to it alone.
   */
  renderTaps(bank, direct, out) {
    const { buf, mask, wp } = this;
    let l = 0, r = 0;

    out[2] = 0;
    out[3] = 0;
    if (direct && !this.roomOnly) {
      let v = readLagrange(buf, mask, wp, direct.delay);
      direct.zl += (1 - direct.lowA) * (v - direct.zl);
      v += direct.lowK * direct.zl;
      direct.zh += (1 - direct.highA) * (v - direct.zh);
      v += direct.highK * (v - direct.zh);
      out[2] = v * direct.gainL;
      out[3] = v * direct.gainR;
    }
    for (let i = 0; i < bank.length; i++) {
      const t = bank[i];
      let v = readLagrange(buf, mask, wp, t.delay);
      t.zl += (1 - t.lowA) * (v - t.zl);
      v += t.lowK * t.zl;
      t.zh += (1 - t.highA) * (v - t.zh);
      v += t.highK * (v - t.zh);
      l += v * t.gainL;
      r += v * t.gainR;
    }
    out[0] = l;
    out[1] = r;
  }

  process(inL, inR, outL, outR, n) {
    if (this.pendingDesign && this.fadeStep === 0 && !this.pendingLines && this.dipDir === 0) {
      const queued = this.pendingDesign;
      this.pendingDesign = null;
      this.setDesign(queued);
    }
    if (!this.ready || this.bypass) {
      for (let i = 0; i < n; i++) { outL[i] = inL[i]; outR[i] = inR[i]; }
      return;
    }
    const { buf, mask, scratch } = this;
    const a = [0, 0, 0, 0], b = [0, 0, 0, 0];
    const dry = 1 - this.mix;
    const wet = this.mix * this.output;
    const dcA = 1 - 20 / this.fs;
    let peak = 0;

    for (let i = 0; i < n; i++) {
      const xl = inL[i], xr = inR[i];
      // The performer is one point source in the room, so the room hears a sum.
      const x = (xl + xr) * 0.5;

      this.wp = (this.wp + 1) & mask;
      buf[this.wp] = x;

      // --- early + direct, crossfaded ------------------------------------
      this.renderTaps(this.bankA, this.directA, a);
      let el = a[0], er = a[1], dl = a[2], dr = a[3];
      if (this.fadeStep > 0 && this.bankB) {
        this.renderTaps(this.bankB, this.directB, b);
        const f = this.fade;
        el = a[0] * (1 - f) + b[0] * f;
        er = a[1] * (1 - f) + b[1] * f;
        dl = a[2] * (1 - f) + b[2] * f;
        dr = a[3] * (1 - f) + b[3] * f;
        this.fade += this.fadeStep;
        if (this.fade >= 1) {
          this.bankA = this.bankB; this.directA = this.directB;
          this.bankB = null; this.directB = null;
          this.fade = 1; this.fadeStep = 0;
        }
      }

      // --- tail ------------------------------------------------------------
      let ll = 0, lr = 0;
      if (this.lines.length === LINES) {
        let li = readInterp(buf, mask, this.wp, this.lateDelay);
        for (let d = 0; d < this.diffusers.length; d++) {
          const ap = this.diffusers[d];
          ap.wp = (ap.wp + 1) & ap.mask;
          const delayed = ap.buf[(ap.wp - ap.length) & ap.mask];
          const v = li - ap.coef * delayed;
          ap.buf[ap.wp] = v;
          li = delayed + ap.coef * v;
        }

        for (let k = 0; k < LINES; k++) {
          const ln = this.lines[k];
          const lb = this.lineBufs[k], lm = this.lineMasks[k];
          const delay = clamp(ln.length + ln.osc * ln.modDepth, 2, lm - 2);
          let v = readInterp(lb, lm, this.lineWp[k], delay);

          // Feedback shaping: broadband gain, then a low and a high shelf whose
          // ratios come straight from the per-band reverberation times.
          ln.zl += (1 - this.shelfLowA) * (v - ln.zl);
          v += (ln.lowRatio - 1) * ln.zl;
          ln.zh += (1 - this.shelfHighA) * (v - ln.zh);
          v += (ln.highRatio - 1) * (v - ln.zh);
          v *= ln.gMid;

          scratch[k] = v;
          ll += v * ln.outL;
          lr += v * ln.outR;

          const c = ln.osc, s = ln.oscQ;
          ln.osc = c * ln.ca - s * ln.sa;
          ln.oscQ = s * ln.ca + c * ln.sa;
        }

        hadamard16(scratch);

        for (let k = 0; k < LINES; k++) {
          const ln = this.lines[k];
          const lm = this.lineMasks[k];
          this.lineWp[k] = (this.lineWp[k] + 1) & lm;
          this.lineBufs[k][this.lineWp[k]] = scratch[k] + li * ln.inGain;
        }

        // Tail tone, then the dip that covers a delay-line re-tune.
        this.lateZl[0] += (1 - this.shelfLowA) * (ll - this.lateZl[0]);
        ll += this.lateLowK * this.lateZl[0];
        this.lateZh[0] += (1 - this.shelfHighA) * (ll - this.lateZh[0]);
        ll += this.lateHighK * (ll - this.lateZh[0]);
        this.lateZl[1] += (1 - this.shelfLowA) * (lr - this.lateZl[1]);
        lr += this.lateLowK * this.lateZl[1];
        this.lateZh[1] += (1 - this.shelfHighA) * (lr - this.lateZh[1]);
        lr += this.lateHighK * (lr - this.lateZh[1]);

        if (this.lateHpA > 0) {
          const yl = this.lateHpA * (this.lateHpY[0] + ll - this.lateHpX[0]);
          const yr = this.lateHpA * (this.lateHpY[1] + lr - this.lateHpX[1]);
          this.lateHpX[0] = ll; this.lateHpX[1] = lr;
          this.lateHpY[0] = yl; this.lateHpY[1] = yr;
          ll = yl; lr = yr;
        }

        ll *= this.lateGainL * this.dip;
        lr *= this.lateGainR * this.dip;
      }

      // --- the room's own modes --------------------------------------------
      // Excited straight off the source: a standing wave starts ringing when
      // the sound reaches it, not after the field has gone diffuse.
      if (this.modes.length) {
        let mo = 0;
        for (let k = 0; k < this.modes.length; k++) {
          const md = this.modes[k];
          const y = md.b0 * x + md.a1 * md.z1 + md.a2 * md.z2;
          md.z2 = md.z1;
          md.z1 = y;
          mo += y;
        }
        // One shared DC blocker for the whole bank: an all-pole resonator has
        // a little gain left at nothing per second, and sixteen of them would
        // otherwise walk the tail off centre.
        const dcOut = 0.999 * (this.modeDcY + mo - this.modeDcX);
        this.modeDcX = mo;
        this.modeDcY = dcOut;
        // Two poles just above the highest mode, so the bank's skirts stop
        // where the delay network's own account of the room begins.
        this.modeLpZ[0] += (1 - this.modeLpA) * (dcOut - this.modeLpZ[0]);
        this.modeLpZ[1] += (1 - this.modeLpA) * (this.modeLpZ[0] - this.modeLpZ[1]);
        mo = this.modeLpZ[1] * this.dip;
        ll += mo;
        lr += mo;
      }


      if (this.dipDir !== 0) {
        this.dip += this.dipDir / this.dipSamples;
        if (this.dip <= 0) {
          this.dip = 0;
          if (this.pendingLines) { this.applyLines(this.pendingLines); this.pendingLines = null; }
          this.dipDir = 1;
        } else if (this.dip >= 1) {
          this.dip = 1;
          this.dipDir = 0;
        }
      }

      // --- capsule tone, width, mix ---------------------------------------
      // The room is what widens; the direct sound sits where the capsules put
      // it, so only the reflections get the width control.
      let rl = el + ll;
      let rr = er + lr;
      const mid = (rl + rr) * 0.5;
      rl = mid + (rl - mid) * this.width;
      rr = mid + (rr - mid) * this.width;

      // Proximity lift belongs to the direct path alone.
      for (let k = 0; k < this.proxL.length; k++) {
        dl = runBiquad(this.proxL[k], dl);
        dr = runBiquad(this.proxR[k], dr);
      }

      let wl = dl + rl;
      let wr = dr + rr;
      for (let k = 0; k < this.toneL.length; k++) wl = runBiquad(this.toneL[k], wl);
      for (let k = 0; k < this.toneR.length; k++) wr = runBiquad(this.toneR[k], wr);

      // DC blockers: a feedback network will happily accumulate offset.
      const yl = wl - this.dcZ[0] + dcA * this.dcY[0];
      this.dcZ[0] = wl; this.dcY[0] = yl; wl = yl;
      const yr = wr - this.dcZ[1] + dcA * this.dcY[1];
      this.dcZ[1] = wr; this.dcY[1] = yr; wr = yr;

      let ol = xl * dry + wl * wet;
      let or_ = xr * dry + wr * wet;

      // Safety net, so a wild parameter cannot hurt anyone.
      if (ol > 0.98 || ol < -0.98) ol = Math.tanh(ol);
      if (or_ > 0.98 || or_ < -0.98) or_ = Math.tanh(or_);

      outL[i] = ol;
      outR[i] = or_;
      const m = Math.abs(ol) > Math.abs(or_) ? Math.abs(ol) : Math.abs(or_);
      if (m > peak) peak = m;
    }
    this.peak = peak;
  }
}
