import test from 'node:test';
import assert from 'node:assert/strict';
import {
  makeState, analyze, decayProfile, micDistance, setMicDistance, setScale, aimMic,
} from '../src/core/acoustics.js';
import { PRESETS } from '../src/core/presets.js';
import { BANDS } from '../src/core/materials.js';

const finite = (xs) => xs.every((v) => Number.isFinite(v));

test('every preset analyses to sane, finite numbers', () => {
  for (const p of PRESETS) {
    const r = analyze(makeState(p.id));
    assert.ok(finite(r.decay.rt60), `${p.id} rt60`);
    assert.ok(r.decay.midRt > 0.05 && r.decay.midRt < 20, `${p.id} rt60 ${r.decay.midRt}`);
    assert.ok(r.early.length > 0, `${p.id} has early reflections`);
    for (const t of r.early) {
      assert.ok(Number.isFinite(t.delay) && t.delay > 0);
      assert.ok(finite(t.left) && finite(t.right), `${p.id} tap gains finite`);
    }
    assert.ok(finite(r.late.left) && finite(r.direct.left));
  }
});

test('early reflections arrive in order, and after the direct sound', () => {
  const r = analyze(makeState('hall'));
  for (let i = 1; i < r.early.length; i++) {
    assert.ok(r.early[i].delay >= r.early[i - 1].delay);
  }
  assert.ok(r.early[0].delay > r.direct.delay);
});

test('the four presets are ordered the way the names imply', () => {
  const rt = (id) => decayProfile(makeState(id)).midRt;
  assert.ok(rt('studio') < rt('theater'), 'studio drier than theatre');
  assert.ok(rt('theater') < rt('hall'), 'theatre drier than hall');
  assert.ok(rt('hall') < rt('cathedral'), 'hall drier than cathedral');
});

test('a bigger space rings longer', () => {
  for (const id of ['studio', 'hall', 'cathedral', 'theater']) {
    const small = decayProfile(setScale(makeState(id), 0.6)).midRt;
    const big = decayProfile(setScale(makeState(id), 1.6)).midRt;
    assert.ok(big > small * 1.3, `${id}: ${small.toFixed(2)}s -> ${big.toFixed(2)}s`);
  }
});

test('a bigger space also pushes the first reflection later', () => {
  const gap = (s) => analyze(s).firstReflectionGap;
  assert.ok(gap(setScale(makeState('hall'), 1.8)) > gap(setScale(makeState('hall'), 0.6)));
});

test('treatment shortens the tail, and more of it shortens it further', () => {
  const rtAt = (cov) => {
    const s = makeState('hall');
    s.treatment = { coverage: cov, type: 'rockwool' };
    return decayProfile(s).midRt;
  };
  const bare = rtAt(0), some = rtAt(0.4), lots = rtAt(0.9);
  assert.ok(some < bare * 0.9, `${bare.toFixed(2)} -> ${some.toFixed(2)}`);
  assert.ok(lots < some, `${some.toFixed(2)} -> ${lots.toFixed(2)}`);
});

test('foam eats the top end; rockwool takes the bass with it', () => {
  const profile = (type) => {
    const s = makeState('hall');
    s.treatment = { coverage: 0.8, type };
    return decayProfile(s).rt60;
  };
  const bare = profile('foam').map(() => null);
  const foam = profile('foam');
  const wool = profile('rockwool');
  const lowIdx = 0, highIdx = 4;
  // Foam leaves a much longer low tail relative to its highs than rockwool does.
  assert.ok(foam[lowIdx] / foam[highIdx] > wool[lowIdx] / wool[highIdx],
    `foam tilt ${(foam[lowIdx] / foam[highIdx]).toFixed(2)} vs wool ${(wool[lowIdx] / wool[highIdx]).toFixed(2)}`);
  assert.equal(bare.length, BANDS.length);
});

test('diffusers scatter without killing the tail', () => {
  const s = makeState('hall');
  s.treatment = { coverage: 0.9, type: 'diffusion' };
  const diffused = analyze(s);
  const s2 = makeState('hall');
  s2.treatment = { coverage: 0.9, type: 'rockwool' };
  const absorbed = analyze(s2);
  assert.ok(diffused.decay.midRt > absorbed.decay.midRt * 1.5, 'diffusion keeps the length');
  const sum = (r) => r.early.reduce((a, t) => a + t.left[3] * t.left[3], 0);
  assert.ok(sum(diffused) < sum(absorbed), 'but breaks up the discrete reflections');
});

test('walking away from the mic buries you in the room', () => {
  const s = makeState('hall');
  const near = analyze(setMicDistance(s, 0.5)).balance.drrDb;
  const far = analyze(setMicDistance(s, 12)).balance.drrDb;
  assert.ok(far < near - 10, `${near.toFixed(1)}dB -> ${far.toFixed(1)}dB`);
});

test('the diffuse field level does not depend on mic distance', () => {
  const s = makeState('hall');
  const a = analyze(setMicDistance(s, 1)).late.left[3];
  const b = analyze(setMicDistance(s, 9)).late.left[3];
  assert.ok(Math.abs(a - b) < 1e-9, 'reverberant field is uniform across the room');
});

test('a directional mic rejects the room; an omni does not', () => {
  const mk = (id) => {
    const s = makeState('hall');
    s.mic.id = id;
    setMicDistance(s, 3);
    return analyze(s);
  };
  const omni = mk('sdc').balance.drrDb;
  const card = mk('ldc').balance.drrDb;
  const gun = mk('shotgun').balance.drrDb;
  assert.ok(card > omni, `cardioid ${card.toFixed(1)} > omni ${omni.toFixed(1)}`);
  assert.ok(gun > card, `shotgun ${gun.toFixed(1)} > cardioid ${card.toFixed(1)}`);
});

test('close-miking a cardioid lifts the low end; an omni is immune', () => {
  const lift = (id, d) => {
    const s = makeState('studio');
    s.mic.id = id;
    setMicDistance(s, d);
    return analyze(s).proximity[0];
  };
  assert.ok(lift('ldc', 0.12) > 6, 'cardioid at 12cm is bassy');
  assert.ok(lift('ldc', 2.5) < 1, 'and flat by 2.5m');
  assert.equal(lift('sdc', 0.12), 0, 'omni has no proximity effect');
});

test('a figure-8 hears the same off the back as off the front', () => {
  const s = makeState('hall');
  s.mic.id = 'ribbon';
  s.mic.aimAtSource = false;
  setMicDistance(s, 2);
  s.mic.azimuth = Math.atan2(s.source.x - s.mic.x, s.source.z - s.mic.z);
  const front = Math.abs(analyze(s).direct.left[3]);
  s.mic.azimuth += Math.PI;
  const back = Math.abs(analyze(s).direct.left[3]);
  assert.ok(Math.abs(front - back) / front < 0.05, `${front} vs ${back}`);
});

test('turning a cardioid away from the performer dulls and quietens them', () => {
  const s = makeState('studio');
  s.mic.id = 'dynamic';
  s.mic.aimAtSource = false;
  setMicDistance(s, 1.0);
  s.mic.azimuth = Math.atan2(s.source.x - s.mic.x, s.source.z - s.mic.z);
  const on = analyze(s).direct;
  s.mic.azimuth += Math.PI / 2;
  const off = analyze(s).direct;
  assert.ok(Math.abs(off.left[3]) < Math.abs(on.left[3]), 'quieter off-axis');
  const tilt = (dir) => Math.abs(dir.left[5]) / Math.abs(dir.left[1]);
  assert.ok(tilt(off) < tilt(on), 'and duller off-axis');
});

test('a stereo pair decorrelates the early reflections; a mono mic does not', () => {
  const spreadOf = (id) => {
    const s = makeState('hall');
    s.mic.id = id;
    const r = analyze(s);
    return r.early.reduce((a, t) => a + Math.abs(t.left[3] - t.right[3]), 0);
  };
  assert.ok(spreadOf('xy') > 0, 'XY pair has L/R differences');
  assert.ok(spreadOf('ldc') < 1e-12, 'a single capsule does not');
});

test('mic distance round-trips and stays inside the walls', () => {
  const s = makeState('studio');
  for (const d of [0.1, 0.5, 1.5, 3]) {
    setMicDistance(s, d);
    assert.ok(Math.abs(micDistance(s) - Math.hypot(d, s.mic.height - s.source.height)) < 0.35);
    assert.ok(s.mic.x > 0 && s.mic.x < s.dims.w);
    assert.ok(s.mic.z > 0 && s.mic.z < s.dims.d);
  }
  setMicDistance(s, 500);
  assert.ok(s.mic.x <= s.dims.w && s.mic.z <= s.dims.d, 'clamped into the room');
});

test('the mic tracks the performer when told to', () => {
  const s = makeState('studio');
  s.mic.aimAtSource = true;
  s.source.x += 1.5;
  aimMic(s);
  const bearing = Math.atan2(s.source.x - s.mic.x, s.source.z - s.mic.z);
  assert.ok(Math.abs(s.mic.azimuth - bearing) < 1e-9);
});
