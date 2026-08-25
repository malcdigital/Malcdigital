// The claim this plugin makes is that moving things in the room changes the
// sound the way the room says it should. These tests hold the DSP to the
// numbers the acoustics model produces.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  makeState, analyze, setScale, setMicDistance, clampOccupants,
} from '../src/core/acoustics.js';
import { designReverb } from '../src/dsp/designer.js';
import { ReverbEngine } from '../src/dsp/reverb-engine.js';
import { FS, bandGain, impulseL, decayTime, energy, db } from './helpers.mjs';

const PRESETS = ['studio', 'hall', 'cathedral', 'theater'];

/** Build an engine, optionally stripping paths to isolate one of them. */
function build(state, mutate = () => {}) {
  const response = analyze(state);
  const design = designReverb(response, FS);
  mutate(design, response);
  const engine = new ReverbEngine(FS);
  engine.setDesign(design);
  engine.setControls({ mix: 1, output: 1 });
  return { engine, design, response };
}

const directOnly = (d) => { d.early = []; d.late.gainL = 0; d.late.gainR = 0; };
const lateOnly = (d) => { d.early = []; d.direct.gainL = 0; d.direct.gainR = 0; };
/** Flatten the shared EQ so a band measurement sees only the path under test. */
const flat = (d) => {
  d.micToneDb = d.micToneDb.map(() => 0);
  d.proximityDb = d.proximityDb.map(() => 0);
  d.direct.low = 1; d.direct.high = 1;
  d.late.low = 1; d.late.high = 1;
};

test('every preset renders a finite, decaying, non-silent tail', () => {
  for (const id of PRESETS) {
    const { engine, design } = build(makeState(id));
    const ir = impulseL(engine, Math.min(20, design.meta.rt60[3] * 1.5 + 0.5));
    assert.ok(ir.every(Number.isFinite), `${id}: produced a non-finite sample`);
    assert.ok(energy(ir) > 0, `${id}: rendered silence`);
    // The last tenth must be quieter than the first tenth, or it is not decaying.
    const chunk = Math.floor(ir.length / 10);
    const head = energy(ir.subarray(0, chunk));
    const tail = energy(ir.subarray(ir.length - chunk));
    assert.ok(tail < head * 0.05, `${id}: tail is not decaying (head ${head}, tail ${tail})`);
  }
});

test('rendered reverberation time matches the room model within 15%', () => {
  for (const id of PRESETS) {
    const { engine, design } = build(makeState(id), (d) => { flat(d); lateOnly(d); });
    const target = design.meta.rt60[3];
    const measured = decayTime(impulseL(engine, Math.min(30, target * 2 + 1)), -5, -35);
    const ratio = measured / target;
    assert.ok(ratio > 0.85 && ratio < 1.15,
      `${id}: RT60 target ${target.toFixed(2)}s, rendered ${measured.toFixed(2)}s`);
  }
});

test('a bigger room decays for longer, and treatment shortens it', () => {
  for (const id of PRESETS) {
    const small = analyze(setScale(makeState(id), 0.5)).decay.midRt;
    const big = analyze(setScale(makeState(id), 1.6)).decay.midRt;
    assert.ok(big > small * 1.3, `${id}: scaling up did not lengthen the tail`);

    const bare = makeState(id);
    bare.treatment = { stage: 0, type: 'rockwool' };
    const treated = makeState(id);
    treated.treatment = { stage: 6, type: 'rockwool' };
    assert.ok(analyze(treated).decay.midRt < analyze(bare).decay.midRt * 0.75,
      `${id}: soundproofing did not shorten the tail`);
  }
});

test('the diffuse tail sits where the diffuse-field equation puts it', () => {
  // Measured in one-octave bands, which is where the model states its numbers.
  // Broadband would be dominated by the top two octaves, where the network
  // rolls off. This is also what pins designer.js's FDN_ENERGY: if that drifts,
  // every rendered tail is the wrong level and this test says so.
  const cases = PRESETS.map((id) => [id, 1]);
  cases.push(['hall', 0.5], ['hall', 1.7], ['studio', 0.5], ['studio', 1.7]);
  for (const [id, scale] of cases) {
    const state = setScale(makeState(id), scale);
    const { engine, response } = build(state, (d) => { flat(d); lateOnly(d); });
    const rt = analyze(state).decay.rt60[3];
    for (const [hz, band] of [[500, 2], [1000, 3], [2000, 4]]) {
      const { engine: e } = build(state, (d) => { flat(d); lateOnly(d); });
      const measured = bandGain(e, hz, 4, Math.min(14, rt * 2));
      const target = Math.abs(response.late.left[band]);
      const errDb = db(measured) - db(target);
      assert.ok(Math.abs(errDb) < 2.0,
        `${id}@${scale} at ${hz}Hz: tail level off by ${errDb.toFixed(2)} dB`);
    }
  }
});

test('the direct sound arrives at the level the inverse-square law predicts', () => {
  const state = makeState('hall');
  for (const metres of [0.5, 1, 2, 4, 8]) {
    setMicDistance(state, metres);
    const { engine, response } = build(state, (d) => { flat(d); directOnly(d); });
    const measured = bandGain(engine, 1000, 2, 0.3);
    const target = Math.abs(response.direct.left[3]);
    const errDb = db(measured) - db(target);
    assert.ok(Math.abs(errDb) < 1.0,
      `at ${metres}m: direct level off by ${errDb.toFixed(2)} dB`);
  }
});

test('backing away from the mic buries the performer in the room', () => {
  const state = makeState('hall');
  let previous = Infinity;
  for (const metres of [0.5, 1, 2, 4, 8, 14]) {
    setMicDistance(state, metres);
    const r = analyze(state);
    const drr = db(r.direct.left[3]) - db(r.late.left[3]);
    assert.ok(drr < previous - 2,
      `stepping out to ${metres}m did not drop the direct-to-reverberant ratio`);
    previous = drr;
  }
});

test('a tighter polar pattern rejects more of the room', () => {
  const state = makeState('hall');
  setMicDistance(state, 3);
  const drrFor = (id) => {
    state.mic.id = id;
    const r = analyze(state);
    return db(r.direct.left[3]) - db(r.late.left[3]);
  };
  const omni = drrFor('sdc');
  const cardioid = drrFor('ldc');
  const shotgun = drrFor('shotgun');
  assert.ok(cardioid > omni + 3, 'a cardioid should hear less room than an omni');
  assert.ok(shotgun > cardioid + 3, 'a shotgun should hear less room than a cardioid');
});

test('closing in on a gradient mic lifts the low end, and an omni ignores it', () => {
  const state = makeState('studio');
  state.mic.id = 'dynamic';
  setMicDistance(state, 0.12);
  const close = analyze(state).proximity[0];
  setMicDistance(state, 3);
  const far = analyze(state).proximity[0];
  assert.ok(close > far + 6, `proximity did not build up close in (${close} vs ${far})`);

  state.mic.id = 'sdc';
  setMicDistance(state, 0.12);
  assert.equal(analyze(state).proximity[0], 0, 'an omni has no proximity effect');
});

test('parameter changes do not click, crack or blow up', () => {
  const state = makeState('hall');
  const { engine } = build(state);
  const N = 128;
  const a = new Float32Array(N), b = new Float32Array(N);
  const oL = new Float32Array(N), oR = new Float32Array(N);
  let phase = 0, worst = 0;
  let prev = 0;

  for (let block = 0; block < 400; block++) {
    for (let i = 0; i < N; i++) {
      const v = Math.sin(phase) * 0.3;
      phase += (2 * Math.PI * 220) / FS;
      a[i] = v; b[i] = v;
    }
    // Yank the room around underneath the audio.
    if (block % 8 === 0) {
      setScale(state, 0.5 + ((block / 8) % 6) * 0.25);
      setMicDistance(state, 0.4 + ((block / 8) % 5) * 2);
      state.mic.id = ['sdc', 'ldc', 'ribbon', 'shotgun', 'xy'][(block / 8) % 5 | 0];
      state.treatment.stage = (block / 8) % 7;
      clampOccupants(state);
      engine.setDesign(designReverb(analyze(state), FS));
    }
    engine.process(a, b, oL, oR, N);
    for (let i = 0; i < N; i++) {
      assert.ok(Number.isFinite(oL[i]) && Number.isFinite(oR[i]), 'engine produced a non-finite sample');
      assert.ok(Math.abs(oL[i]) <= 1.001, `engine exceeded full scale: ${oL[i]}`);
      const jump = Math.abs(oL[i] - prev);
      if (jump > worst) worst = jump;
      prev = oL[i];
    }
  }
  // A 220 Hz sine moves at most ~0.03 per sample at this level; anything an
  // order of magnitude past that is a discontinuity, i.e. an audible click.
  assert.ok(worst < 0.3, `sample-to-sample jump of ${worst.toFixed(3)} suggests a click`);
});

test('bypass passes audio through untouched', () => {
  const { engine } = build(makeState('cathedral'));
  engine.setControls({ bypass: true });
  const N = 64;
  const a = new Float32Array(N), b = new Float32Array(N);
  const oL = new Float32Array(N), oR = new Float32Array(N);
  for (let i = 0; i < N; i++) { a[i] = Math.sin(i * 0.1) * 0.5; b[i] = -a[i]; }
  engine.process(a, b, oL, oR, N);
  for (let i = 0; i < N; i++) {
    assert.equal(oL[i], a[i]);
    assert.equal(oR[i], b[i]);
  }
});
