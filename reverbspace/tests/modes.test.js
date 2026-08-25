import test from 'node:test';
import assert from 'node:assert/strict';
import { makeState, decayProfile, setScale } from '../src/core/acoustics.js';
import {
  roomModes, roomNote, scaleForNote, noteOf, noteFrequency, noteNumber,
} from '../src/core/modes.js';
import { PRESETS_BY_ID } from '../src/core/presets.js';

const C = 343;
const modesOf = (s) => roomModes(s, decayProfile(s), 40);

test('mode frequencies are the closed form for a shoebox', () => {
  const s = makeState('studio');
  const { w, d, h } = s.dims;
  for (const m of modesOf(s)) {
    const want = (C / 2) * Math.hypot(m.nx / w, m.ny / h, m.nz / d);
    assert.ok(Math.abs(m.f - want) < 1e-9, `(${m.nx},${m.ny},${m.nz}) ${m.f} vs ${want}`);
  }
});

test('halving the room puts every mode an octave up', () => {
  const big = makeState('studio');
  const small = setScale(makeState('studio'), 0.5);
  const key = (m) => `${m.nx},${m.ny},${m.nz}`;
  const table = new Map(modesOf(big).map((m) => [key(m), m.f]));
  let checked = 0;
  for (const m of modesOf(small)) {
    const was = table.get(key(m));
    if (was === undefined) continue;      // the cap lets different modes through
    assert.ok(Math.abs(m.f / was - 2) < 1e-6, `${key(m)}: ${was} -> ${m.f}`);
    checked++;
  }
  assert.ok(checked > 0, 'no shared modes to compare');
});

test('a booth has a note and a cathedral does not', () => {
  const studio = makeState('studio');
  const cathedral = makeState('cathedral');
  const note = roomNote(studio, decayProfile(studio));
  assert.ok(note && note.f > 28, `studio: ${note && note.f}`);
  // Not "no modes" -- a cathedral has thousands. They are below hearing and so
  // close together that no one of them is a pitch, which is the whole reason a
  // big room sounds smooth and a small one sounds boxy.
  assert.equal(roomNote(cathedral, decayProfile(cathedral)), null);
});

test('standing in a mode null does not excite it', () => {
  // The (1,0,0) mode has a pressure node down the middle of the room, so a
  // performer standing there cannot drive it however loud they are.
  const s = makeState('studio');
  s.source.x = s.dims.w / 2;
  s.mic.x = s.dims.w / 2;
  const axial = modesOf(s).filter((m) => m.nx % 2 === 1 && m.ny === 0 && m.nz === 0);
  assert.equal(axial.length, 0, 'odd width modes should be dead at the centre');
  // Step off the centre line and they come back.
  s.source.x = s.dims.w * 0.3;
  s.mic.x = s.dims.w * 0.3;
  assert.ok(modesOf(s).some((m) => m.nx % 2 === 1 && m.ny === 0 && m.nz === 0));
});

test('tuning lands the room note on the key', () => {
  const p = PRESETS_BY_ID.studio;
  for (let pc = 0; pc < 12; pc++) {
    const s = makeState('studio');
    const hit = scaleForNote(s, decayProfile(s), pc, p.sizeRange);
    assert.ok(hit, `no size reaches pitch class ${pc}`);
    setScale(s, hit.scale);
    const note = roomNote(s, decayProfile(s));
    const off = Math.abs(noteNumber(note.f) - hit.midi);
    assert.ok(off < 0.03, `pitch class ${pc}: ${note.label} is ${off.toFixed(2)} semitones off`);
    assert.equal(noteOf(note.f).name, noteOf(noteFrequency(pc + 24)).name);
  }
});

test('tuning only ever changes the size', () => {
  // Which is the honest mechanism, and the reason size moves the pitch at all.
  const s = makeState('studio');
  const before = { x: s.source.x / s.dims.w, z: s.source.z / s.dims.d, stage: s.treatment.stage };
  const hit = scaleForNote(s, decayProfile(s), 2, PRESETS_BY_ID.studio.sizeRange);
  setScale(s, hit.scale);
  assert.ok(Math.abs(s.source.x / s.dims.w - before.x) < 1e-9);
  assert.ok(Math.abs(s.source.z / s.dims.d - before.z) < 1e-9);
  assert.equal(s.treatment.stage, before.stage);
});
