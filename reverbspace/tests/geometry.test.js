import test from 'node:test';
import assert from 'node:assert/strict';
import { makeState } from '../src/core/acoustics.js';
import { buildRoom } from '../src/ui/gl/room.js';

/** Every vertex of these batches, as {x, y, z}. */
function verts(batches, names) {
  const out = [];
  for (const name of names) {
    const p = batches[name] && batches[name].pos;
    if (!p) continue;
    for (let i = 0; i < p.length; i += 3) out.push({ x: p[i], y: p[i + 1], z: p[i + 2] });
  }
  return out;
}

/** Every triangle of these batches, as three {x, y, z}. */
function tris(batches, names) {
  const out = [];
  for (const name of names) {
    const m = batches[name];
    if (!m || !m.idx.length) continue;
    const at = (k) => ({ x: m.pos[k * 3], y: m.pos[k * 3 + 1], z: m.pos[k * 3 + 2] });
    for (let i = 0; i < m.idx.length; i += 3) {
      out.push([at(m.idx[i]), at(m.idx[i + 1]), at(m.idx[i + 2])]);
    }
  }
  return out;
}

const TREATMENT = ['panels', 'panelsAlt', 'foam', 'diffuser'];

test('nothing on a wall is coplanar with it', () => {
  // Two faces sharing a plane fight over every pixel they share, and that
  // flicker along the edge of a panel is what reads as it clipping through the
  // wall. Absorbers bite a few millimetres into the wall instead, so the face
  // that would have argued is simply behind it.
  for (const type of ['rockwool', 'foam', 'diffusion']) {
    const s = makeState('studio');
    s.treatment = { stage: 6, type };
    const { batches } = buildRoom(s);
    const { w, d } = s.dims;
    const planes = [{ axis: 'x', at: 0 }, { axis: 'x', at: w }, { axis: 'z', at: 0 }, { axis: 'z', at: d }];
    const all = tris(batches, TREATMENT);
    assert.ok(all.length > 0, `${type}: nothing was built to check`);
    for (const t of all) {
      for (const p of planes) {
        // A corner trap meets each of its two walls along an edge, which is
        // fine -- two vertices on a plane cannot fight with it. Three can.
        const on = t.filter((v) => Math.abs(v[p.axis] - p.at) < 1e-4).length;
        assert.ok(on < 3, `${type}: a face lies flat on ${p.axis} = ${p.at}`);
      }
    }
  }
});

test('nothing on a wall pokes out through the other side of it', () => {
  // The bite is a few millimetres, not a few centimetres: an absorber that
  // reaches past the wall shows up in the room next door.
  for (const type of ['rockwool', 'foam', 'diffusion']) {
    const s = makeState('studio');
    s.treatment = { stage: 6, type };
    const { batches } = buildRoom(s);
    const { w, d } = s.dims;
    for (const v of verts(batches, TREATMENT)) {
      assert.ok(v.x > -0.02 && v.x < w + 0.02 && v.z > -0.02 && v.z < d + 0.02,
        `${type}: (${v.x.toFixed(3)}, ${v.z.toFixed(3)}) is outside ${w} x ${d}`);
    }
  }
});

test('foam tiles line up across patches on the same wall', () => {
  // Every patch is laid out on one grid per wall rather than centred inside
  // its own rectangle, so two that meet do not arrive half a tile out of step
  // and leave a stripe of bare wall between them.
  const s = makeState('studio');
  s.treatment = { stage: 6, type: 'foam' };
  const { batches } = buildRoom(s);
  const p = batches.foam.pos;
  const tile = 0.3;
  // The pyramids on the x = 0 wall: their apexes stand proud of the backing.
  const apex = [];
  for (let i = 0; i < p.length; i += 3) {
    if (p[i] > 0.03 && p[i] < 0.09) apex.push({ y: p[i + 1], z: p[i + 2] });
  }
  assert.ok(apex.length > 8, `only ${apex.length} pyramids found`);
  for (const a of apex) {
    const offGrid = Math.abs(((a.y / tile) % 1) - 0.5);
    assert.ok(offGrid < 1e-6, `a tile centre at y = ${a.y.toFixed(4)} is off the grid`);
  }
});
