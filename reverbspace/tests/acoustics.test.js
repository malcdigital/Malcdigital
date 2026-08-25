import test from 'node:test';
import assert from 'node:assert/strict';
import {
  makeState, analyze, decayProfile, micDistance, setMicDistance, setScale, aimMic,
} from '../src/core/acoustics.js';
import { PRESETS } from '../src/core/presets.js';
import { BANDS } from '../src/core/materials.js';
import {
  MAX_STAGE, treatmentZones, zoneCoverage, cornerChord, reflectionPointU,
} from '../src/core/treatment.js';
import { fittings, defaultPlacement } from '../src/core/fittings.js';

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
  const rtAt = (stage) => {
    const s = makeState('hall');
    s.treatment = { stage, type: 'rockwool' };
    return decayProfile(s).midRt;
  };
  const bare = rtAt(0), some = rtAt(3), lots = rtAt(6);
  // A mid stage is a handful of panels, and in fifteen thousand cubic metres
  // a handful of panels is a few percent -- which is the right answer, so the
  // magnitude belongs at the top of the plan, not the middle of it. That every
  // single step is a step down is asserted on its own below.
  assert.ok(some < bare, `${bare.toFixed(2)} -> ${some.toFixed(2)}`);
  assert.ok(lots < bare * 0.7, `${bare.toFixed(2)} -> ${lots.toFixed(2)}`);
});

test('every step of the plan is a step down, in every room', () => {
  for (const preset of ['studio', 'hall', 'cathedral', 'theater']) {
    const s = makeState(preset);
    let last = Infinity;
    const seen = [];
    for (let stage = 0; stage <= MAX_STAGE; stage++) {
      s.treatment.stage = stage;
      const rt = decayProfile(s).midRt;
      seen.push(rt.toFixed(2));
      assert.ok(rt < last, `${preset} stage ${stage} did not shorten: ${seen.join(' ')}`);
      last = rt;
    }
  }
});

test('the model measures the treatment that is actually on the walls', () => {
  // The plan is the only source of truth: the coverage the decay is computed
  // from has to be the area of the rectangles the renderer draws, cuts around
  // the window and the door included. Recompute it here the long way.
  const s = makeState('studio');
  for (let stage = 0; stage <= MAX_STAGE; stage++) {
    s.treatment.stage = stage;
    const plan = treatmentZones(s);
    const { w, d, h } = s.dims;
    let area = 0;
    for (const wall of plan.zones) for (const r of wall) area += (r.u1 - r.u0) * (r.v1 - r.v0);
    if (plan.corners) area += 4 * cornerChord(s) * Math.min(fittings(s).eaves - 0.05, h);
    assert.ok(Math.abs(zoneCoverage(s).wall - area / (2 * (w + d) * h)) < 1e-9,
      `stage ${stage}`);
  }
});

test('a panel whose spot is taken slides to where it fits', () => {
  // This studio's left-wall reflection point lands on the door, with a patch
  // panel and a sconce either side of it. The step still has to place a panel.
  const s = makeState('studio');
  s.treatment = { stage: 1, type: 'rockwool' };
  const plan = treatmentZones(s);
  assert.ok(plan.zones[2].length > 0, 'nothing placed on the wall with the door');
  assert.ok(plan.zones[3].length > 0, 'nothing placed on the far side wall');
  const ideal = reflectionPointU(s, 2);
  const covers = plan.zones[2].some((r) => r.u0 <= ideal && r.u1 >= ideal);
  assert.ok(!covers, 'the door is clear');
});

test('panels are screwed to the wall and stay there', () => {
  // The treatment is installed for the room's working position, not for
  // wherever you have wandered to. Panels that slid along the wall as you
  // dragged the mic looked like a rendering fault, and were not true either:
  // where the reflection lands now is what the ray overlay is for.
  const s = makeState('studio');
  s.treatment.stage = 2;
  const before = JSON.stringify(treatmentZones(s).zones);
  s.source.z += 1.4;
  s.mic.z += 1.4;
  s.source.x -= 1.1;
  s.mic.x -= 0.6;
  assert.equal(JSON.stringify(treatmentZones(s).zones), before);
});

test('the reflection point is the one for the working position', () => {
  // Mirror the performer in the far wall, draw a line to the mic, and see
  // where it crosses. Worked out here the long way, from the defaults.
  const s = makeState('studio');
  const { source, mic } = defaultPlacement(s);
  const { w } = s.dims;
  const t = (w - source.x) / ((w - source.x) + (w - mic.x));
  assert.ok(Math.abs(reflectionPointU(s, 3) - (source.z + (mic.z - source.z) * t)) < 1e-9);
});

test('foam eats the top end; rockwool takes the bass with it', () => {
  const profile = (type) => {
    const s = makeState('hall');
    s.treatment = { stage: 6, type };
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
  s.treatment = { stage: 6, type: 'diffusion' };
  const diffused = analyze(s);
  const s2 = makeState('hall');
  s2.treatment = { stage: 6, type: 'rockwool' };
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
