// Browser smoke test: does the page actually come up, does the AudioWorklet
// load, and does the room paint? Node's test runner covers the maths; this
// covers the half that only exists in a browser.
//
//   npm install          (playwright is a dev dependency)
//   npm run serve &      (or any static server on :8123)
//   node tests/browser-smoke.mjs

import { chromium } from 'playwright';
import { MAX_STAGE } from '../src/core/treatment.js';
import { mkdirSync, existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const BASE = process.env.BASE_URL || 'http://localhost:8123';
const SHOTS = process.env.SHOT_DIR || 'shots';
/** Use whatever Chromium this machine already has rather than downloading one. */
function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || '/opt/pw-browsers';
  if (existsSync(root)) {
    for (const dir of readdirSync(root)) {
      if (!dir.startsWith('chromium-')) continue;
      const exe = join(root, dir, 'chrome-linux', 'chrome');
      if (existsSync(exe)) return exe;
    }
  }
  return undefined;   // let playwright fall back to its own download
}
const CHROME = findChrome();

mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch({
  executablePath: CHROME,
  args: [
    '--autoplay-policy=no-user-gesture-required',
    '--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream',
  ],
});
const page = await browser.newPage({ viewport: { width: 1500, height: 940 } });

const problems = [];
page.on('pageerror', (e) => problems.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') problems.push('console: ' + m.text()); });
page.on('requestfailed', (r) => problems.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));

const PAGE = process.env.PAGE_URL || `${BASE}/index.html`;
await page.goto(PAGE, { waitUntil: 'networkidle' });
await page.waitForTimeout(600);
await page.mouse.click(700, 400);
// Starting audio is asynchronous -- the worklet has to load -- so wait for the
// overlay to actually go rather than guessing how long that takes. Bounded, so
// a page that never starts still fails the check below rather than hanging.
await page.waitForFunction(
  () => document.querySelector('#overlay').classList.contains('gone'),
  null, { timeout: 8000 },
).catch(() => {});
await page.waitForTimeout(400);

/** How much of the room canvas is actually painted. */
const painted = () => page.evaluate(() => {
  // The room is a WebGL canvas, so copy it into a 2D one to read the pixels.
  const c = document.querySelector('#room');
  const tmp = document.createElement('canvas');
  tmp.width = c.width;
  tmp.height = c.height;
  const g = tmp.getContext('2d');
  g.drawImage(c, 0, 0);
  const d = g.getImageData(0, 0, tmp.width, tmp.height).data;
  let lit = 0, total = 0;
  for (let i = 0; i < d.length; i += 4000) {
    total++;
    if (d[i] > 14 || d[i + 1] > 14 || d[i + 2] > 14) lit++;
  }
  return lit / total;
});

const worklet = await page.evaluate(async () => {
  // The app has already started audio from the click above; ask it directly, so
  // this works for the bundled single-file build too.
  const rs = window.reverbspace;
  if (!rs) return { ok: false, error: 'app never booted' };
  try {
    await rs.audio.start();
    return { ok: true, sampleRate: rs.audio.ctx.sampleRate, node: !!rs.audio.node };
  } catch (err) {
    return { ok: false, error: String(err && err.message || err) };
  }
});

const info = await page.evaluate(() => ({
  stats: document.querySelectorAll('#stats dt').length,
  presets: document.querySelectorAll('.preset').length,
  sources: document.querySelectorAll('.src').length,
  overlayGone: document.querySelector('#overlay').classList.contains('gone'),
}));

const results = [];
const check = (name, pass, detail = '') => {
  results.push({ name, pass, detail });
  console.log(`${pass ? 'ok  ' : 'FAIL'}  ${name}${detail ? '  -- ' + detail : ''}`);
};

check('page loads with no errors', problems.length === 0, problems.join(' | '));
check('AudioWorklet module loads (ES imports work inside the worklet)',
  worklet.ok, worklet.ok ? `${worklet.sampleRate} Hz` : worklet.error);
check('room canvas paints', (await painted()) > 0.25);
check('WebGL renderer came up', await page.evaluate(() => !window.reverbspace.scene.failed),
  await page.evaluate(() => window.reverbspace.scene.failed || ''));
check('stats populate', info.stats >= 8, `${info.stats} rows`);
check('presets and sources render', info.presets === 4 && info.sources >= 5);
check('start overlay dismisses', info.overlayGone);

await page.screenshot({ path: `${SHOTS}/01-studio.png` });

// Each space, with the mic pulled out into the room.
for (const [i, id] of ['hall', 'cathedral', 'theater'].entries()) {
  await page.click(`.preset[data-id="${id}"]`);
  await page.waitForTimeout(500);
  await page.evaluate(() => {
    const d = document.querySelector('#mic-d');
    d.value = String(Math.min(+d.max, 8));
    d.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${SHOTS}/0${i + 2}-${id}.png` });
  check(`${id} renders`, (await painted()) > 0.25);
}

// Treatment should visibly change the walls and shorten the tail.
await page.click('.preset[data-id="studio"]');
await page.waitForTimeout(300);
const rtAt = async (stage) => page.evaluate((c) => {
  const t = document.querySelector('#treat');
  t.value = String(c);
  t.dispatchEvent(new Event('input', { bubbles: true }));
  return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => {
    r(document.querySelector('#stats dd').textContent);
  })));
}, stage);
const bare = parseFloat(await rtAt(0));
await page.screenshot({ path: `${SHOTS}/05-studio-untreated.png` });
const treated = parseFloat(await rtAt(MAX_STAGE));
await page.screenshot({ path: `${SHOTS}/06-studio-treated.png` });
check('soundproofing shortens the tail', treated < bare * 0.8, `${bare}s -> ${treated}s`);

// Dragging the mic across the room must move the numbers, not just the picture.
await page.click('.preset[data-id="hall"]');
await page.waitForTimeout(400);
const readStats = () => page.evaluate(() => {
  const dd = [...document.querySelectorAll('#stats dd')].map((e) => e.textContent);
  return { distance: dd[2], drr: dd[4], firstReflection: dd[5] };
});
const before = await readStats();
const box = await page.locator('#room').boundingBox();
const micAt = await page.evaluate(() => window.reverbspace.screenOf('mic'));
check('the mic is on screen where the scene says it is', !!micAt);
await page.mouse.move(box.x + micAt.x, box.y + micAt.y);
await page.mouse.down();
await page.mouse.move(box.x + micAt.x - 190, box.y + micAt.y + 90, { steps: 24 });
await page.mouse.up();
await page.waitForTimeout(400);
const after = await readStats();
check('dragging in the room changes the acoustics',
  before.distance !== after.distance && before.drr !== after.drr,
  `${before.distance} @ ${before.drr}  ->  ${after.distance} @ ${after.drr}`);
await page.screenshot({ path: `${SHOTS}/07-hall-dragged.png` });

// Mic choice must change how much room is picked up.
const drrFor = async (id) => {
  await page.selectOption('#mic-type', id);
  await page.waitForTimeout(350);
  return (await readStats()).drr;
};
const omni = await drrFor('sdc');
const shotgun = await drrFor('shotgun');
check('a shotgun rejects more room than an omni',
  parseFloat(shotgun) > parseFloat(omni) + 3, `omni ${omni}, shotgun ${shotgun}`);

// The scattering and lens passes are easy to break silently: a uniform that
// stops being uploaded leaves a shader that still compiles and contributes
// nothing. Pin each one down by what it does to the picture.
//
// Two figures, because the two passes show up in different places. Haze is a
// lift in overall brightness and pools under the fittings; a lens takes away
// fine detail on whatever is not at the focus distance. Detail has to be
// measured at native resolution -- scaling a frame down low-passes it harder
// than any lens does, and then sharp and soft measure the same.
await page.click('.preset[data-id="studio"]');
await page.waitForTimeout(600);
const frameAt = (opts) => page.evaluate(async (o) => {
  const rs = window.reverbspace.scene;
  rs.tier = o.tier;
  rs.budget = () => {};        // hold the tier: it would move back within a second
  rs.cam.pitch = o.pitch;
  const s = window.reverbspace.state;
  s.mic.x = s.source.x + Math.sin(rs.cam.yaw) * o.focus;
  s.mic.z = s.source.z + Math.cos(rs.cam.yaw) * o.focus;
  rs.onChange('mic');
  await new Promise((r) => setTimeout(r, 500));

  const c = document.querySelector('#room');
  const read = (sx, sy, sw, sh, dw, dh) => {
    const off = document.createElement('canvas');
    off.width = dw; off.height = dh;
    const g = off.getContext('2d');
    g.drawImage(c, sx, sy, sw, sh, 0, 0, dw, dh);
    return { px: g.getImageData(0, 0, dw, dh).data, w: dw, h: dh };
  };
  const lum = (px, i) => 0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2];

  // A grid rather than one number for the frame: haze is not spread evenly,
  // it collects under the fittings, and an average over the whole picture
  // dilutes a cone that is obvious to look at down to a percent or two.
  const GX = 8, GY = 5, C = 16;
  const whole = read(0, 0, c.width, c.height, GX * C, GY * C);
  const cells = new Array(GX * GY).fill(0);
  for (let y = 0; y < GY * C; y++) {
    for (let x = 0; x < GX * C; x++) {
      cells[Math.floor(y / C) * GX + Math.floor(x / C)]
        += lum(whole.px, (y * GX * C + x) * 4) / (C * C);
    }
  }

  const W = Math.min(360, c.width), H = Math.min(140, c.height);
  const strip = read(Math.round((c.width - W) / 2), Math.round(c.height * 0.12), W, H, W, H);
  let edge = 0, n = 0;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W - 1; x++) {
      const i = (y * W + x) * 4;
      edge += Math.abs(lum(strip.px, i + 4) - lum(strip.px, i));
      n++;
    }
  }
  return { cells, detail: edge / n };
}, opts);

// Level, down the length of the room, with the fittings and the air under
// them in frame. Pointing up at a shade is the wrong test: it shortens every
// view ray to the ceiling and there is nothing left to scatter through.
const noVolume = await frameAt({ tier: 1, focus: 1.0, pitch: 0.05 });
const withVolume = await frameAt({ tier: 2, focus: 1.0, pitch: 0.05 });
// The mean of the six patches that gained most, not the single best one.
// The two frames carry different film grain, and a maximum over forty cells
// picks the tail of that noise as readily as it picks the signal.
const lifts = withVolume.cells
  .map((v, i) => (v - noVolume.cells[i]) / Math.max(noVolume.cells[i], 1))
  .sort((a, b) => b - a);
const lift = lifts.slice(0, 6).reduce((a, b) => a + b, 0) / 6;
check('scattering puts light in the air',
  lift > 0.015, `brightest patches +${(lift * 100).toFixed(1)}%`);

// A mic held close throws the room out; one set back brings it in.
const near = await frameAt({ tier: 2, focus: 0.5, pitch: 0 });
const far = await frameAt({ tier: 2, focus: 4.0, pitch: 0 });
// Six percent, not fifteen: the lens has been stopped a long way down since
// this was written, deliberately, and what is being checked is that focus
// still tracks the mic -- a dead pass reads 1.00, and this reads about 1.11.
check('the lens focuses on the mic, and a close mic softens the room',
  far.detail > near.detail * 1.06,
  `detail ${near.detail.toFixed(2)} at 0.5 m -> ${far.detail.toFixed(2)} at 4 m`);

// Each mic is now modelled as the thing it actually is -- a U 87 basket, an
// SM7B in its yoke, a 250 mm shotgun tube -- so choosing one has to rebuild
// the mesh and not just the maths. The rebuild key left the model out at
// first, and every mic quietly drew as whichever one loaded first.
const micMeshes = {};
for (const id of ['ldc', 'sdc', 'dynamic', 'ribbon', 'shotgun', 'xy']) {
  await page.selectOption('#mic-type', id);
  await page.waitForTimeout(350);
  micMeshes[id] = await page.evaluate(() => window.reverbspace.scene.micBatches
    .reduce((n, b) => n + b.mesh.count, 0));
}
const counts = Object.values(micMeshes);
check('every mic is built as itself',
  new Set(counts).size === counts.length,
  Object.entries(micMeshes).map(([k, v]) => `${k} ${v}`).join(', '));

// Soundproofing goes on in named steps, and each one has to actually change
// the room -- both the picture and the number the decay is computed from.
await page.click('.preset[data-id="studio"]');
await page.waitForTimeout(500);
const atStage = (n) => page.evaluate(async (stage) => {
  const el = document.querySelector('#treat');
  el.value = String(stage);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  await new Promise((r) => setTimeout(r, 320));
  const t = await import('/src/core/treatment.js');
  const s = window.reverbspace.state;
  return {
    label: document.querySelector('#treat-name').textContent,
    cover: t.zoneCoverage(s).wall,
    rects: t.treatmentZones(s).zones.reduce((k, w) => k + w.length, 0),
    rt: parseFloat(document.querySelectorAll('#stats dd')[0].textContent),
  };
}, n);
const steps = [];
for (let i = 0; i <= 6; i++) steps.push(await atStage(i));
check('every step of the plan is named and puts more up',
  steps.every((s2, i) => s2.label && (i === 0 || s2.cover > steps[i - 1].cover - 1e-9))
  && steps[6].cover > steps[1].cover * 3,
  steps.map((s2) => `${s2.label}: ${(s2.cover * 100).toFixed(0)}% / ${s2.rects} panels`).join(' | '));
check('the bare room rings longer than the treated one',
  steps[0].rt > steps[6].rt * 2, `${steps[0].rt}s -> ${steps[6].rt}s`);

// Panels are installed for the room's working position and stay put. Walking
// about must not move a single one of them.
await atStage(2);
const panelsNow = () => page.evaluate(async () => {
  const t = await import('/src/core/treatment.js');
  return JSON.stringify(t.treatmentZones(window.reverbspace.state).zones);
});
const beforeMove = await panelsNow();
await page.evaluate(() => {
  const rs = window.reverbspace;
  rs.state.source.z += 1.2;
  rs.state.source.x -= 0.9;
  rs.state.mic.z += 1.2;
  rs.scene.onChange('source');
});
await page.waitForTimeout(400);
check('walking about does not slide the panels along the wall',
  (await panelsNow()) === beforeMove);

// And putting everyone back has to actually put them back.
const places = () => page.evaluate(() => {
  const s = window.reverbspace.state;
  return [s.source.x, s.source.z, s.mic.x, s.mic.z, s.mic.height].map((v) => v.toFixed(2)).join(',');
});
const moved = await places();
await page.click('#reset-places');
await page.waitForTimeout(400);
const back = await places();
check('the reset puts the performer and the mic back', back !== moved, `${moved} -> ${back}`);

// Stop has to actually stop, and the buttons have to say what is true: a
// disabled Stop while a loop is running is worse than no Stop at all.
await page.click('.src[data-id="loop"]');
await page.evaluate(() => { document.querySelector('#loop').checked = true; });
await page.click('#play');
await page.waitForTimeout(700);
const running = await page.evaluate(() => ({
  playing: window.reverbspace.audio.playing,
  stopEnabled: !document.querySelector('#stop').disabled,
}));
check('a looping test sound plays, and Stop lights up',
  running.playing && running.stopEnabled, JSON.stringify(running));
await page.click('#stop');
await page.waitForTimeout(400);
const stopped = await page.evaluate(() => ({
  playing: window.reverbspace.audio.playing,
  stopEnabled: !document.querySelector('#stop').disabled,
}));
check('Stop stops it, and goes back to dimmed',
  !stopped.playing && !stopped.stopEnabled, JSON.stringify(stopped));

// The room's own resonances, and tuning them to a key. This is the one place
// the size control's effect on pitch is stated out loud, so it has to be true.
await page.click('.preset[data-id="studio"]');
await page.waitForTimeout(500);
const tuneTo = (pc) => page.evaluate(async (v) => {
  const sel = document.querySelector('#key');
  sel.value = String(v);
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  document.querySelector('#tune').click();
  await new Promise((r) => setTimeout(r, 400));
  const m = await import('/src/core/modes.js');
  const rs = window.reverbspace;
  const note = m.roomNote(rs.state, rs.response.decay);
  return { midi: m.noteOf(note.f).midi, f: note.f, scale: rs.state.scale,
           text: document.querySelector('#mode-note').textContent };
}, pc);
const toA = await tuneTo(9);
const toD = await tuneTo(2);
check('tuning the room lands its note on the key',
  toA.midi % 12 === 9 && toD.midi % 12 === 2,
  `A -> ${toA.f.toFixed(1)}Hz @ ${(toA.scale * 100).toFixed(0)}%, `
  + `D -> ${toD.f.toFixed(1)}Hz @ ${(toD.scale * 100).toFixed(0)}%`);
check('tuning works by resizing the room', Math.abs(toA.scale - toD.scale) > 0.02,
  `${toA.scale.toFixed(3)} vs ${toD.scale.toFixed(3)}`);
check('the readout names the note', /Rings at .* Hz/.test(toA.text), toA.text);

// A cathedral has no note to tune, and says so rather than inventing one.
await page.click('.preset[data-id="cathedral"]');
await page.waitForFunction(() => window.reverbspace.state.presetId === 'cathedral'
  && window.reverbspace.response.decay.schroeder < 40, null, { timeout: 4000 }).catch(() => {});
await page.waitForTimeout(400);
const big = await page.evaluate(() => ({
  text: document.querySelector('#mode-note').textContent,
  disabled: document.querySelector('#tune').disabled,
}));
check('a cathedral is too big to ring at a note', big.disabled && /Too big/.test(big.text), big.text);

// Shift keeps you on one axis: walking, that means no diagonal drift.
//
// Driven through walk() with a fixed time step rather than by holding keys for
// a while, because what is being checked is the arithmetic and real elapsed
// frames are not repeatable enough to measure a distance with.
await page.click('.preset[data-id="studio"]');
await page.waitForTimeout(500);
const step = (keys, shift) => page.evaluate(([ks, sh]) => {
  const rs = window.reverbspace.scene;
  const st = window.reverbspace.state;
  rs.cam.mode = 'first';
  rs.cam.yaw = 0;                       // facing straight down +z
  st.source.x = st.dims.w / 2;
  st.source.z = st.dims.d / 2;
  const from = { x: st.source.x, z: st.source.z };
  rs.keys = new Set(ks);
  rs.shift = sh;
  rs.walkAxis = null;
  rs.walk(0.1);
  rs.keys = new Set();
  rs.shift = false;
  return { dx: st.source.x - from.x, dz: st.source.z - from.z };
}, [keys, shift]);

const free = await step(['w', 'd'], false);
const held = await step(['w', 'd'], true);
check('shift walks you straight instead of diagonally',
  Math.abs(free.dx) > 0.05 && Math.abs(held.dx) < 1e-9 && held.dz > 0.05,
  `free (${free.dx.toFixed(3)}, ${free.dz.toFixed(3)}) -> shift (${held.dx.toFixed(3)}, ${held.dz.toFixed(3)})`);

const across = await step(['a'], true);
check('shift across the room still goes across',
  Math.abs(across.dz) < 1e-9 && across.dx < -0.05,
  `(${across.dx.toFixed(3)}, ${across.dz.toFixed(3)})`);

// And the same when dragging on the plan, where the axes are the room's.
const dragTo = (shift, dx, dz) => page.evaluate(([sh, ddx, ddz]) => {
  const rs = window.reverbspace.scene;
  const st = window.reverbspace.state;
  const from = { x: st.dims.w / 2, z: st.dims.d / 2 };
  st.source.x = from.x;
  st.source.z = from.z;
  rs.drag = { kind: 'source', viaMap: true, from: { ...from } };
  rs.shift = sh;
  rs.applyMap({ x: from.x + ddx, z: from.z + ddz });
  rs.drag = null;
  rs.shift = false;
  return { dx: st.source.x - from.x, dz: st.source.z - from.z };
}, [shift, dx, dz]);

const slid = await dragTo(true, 1.2, 0.3);       // mostly across, a little along
check('shift slides you along one wall without drifting toward the other',
  Math.abs(slid.dx - 1.2) < 1e-9 && Math.abs(slid.dz) < 1e-9,
  `(${slid.dx.toFixed(2)}, ${slid.dz.toFixed(2)})`);
const loose = await dragTo(false, 1.2, 0.3);
check('without shift a drag goes where you put it',
  Math.abs(loose.dz - 0.3) < 1e-9, `(${loose.dx.toFixed(2)}, ${loose.dz.toFixed(2)})`);

// Dragging the mic in first person has to move it by roughly what the cursor
// did, and land where you let go -- not shoot off to the far wall.
await page.click('#reset-places');
await page.waitForTimeout(350);
const micDrag = async (dxPx, dyPx) => {
  // Earlier checks leave the camera pointing wherever they needed it, so aim
  // it at the mic before trying to grab the mic.
  await page.evaluate(() => {
    const rs = window.reverbspace;
    rs.scene.setMode('first');
    rs.scene.lookAtMic();
    rs.scene.onChange('mic');
  });
  await page.waitForTimeout(250);
  const box = await page.locator('#room').boundingBox();
  const at = await page.evaluate(() => window.reverbspace.screenOf('mic'));
  if (!at) return { moved: NaN, before: null, after: null, offScreen: true };
  const before = await page.evaluate(() => ({ ...window.reverbspace.state.mic }));
  await page.mouse.move(box.x + at.x, box.y + at.y);
  await page.mouse.down();
  await page.mouse.move(box.x + at.x + dxPx, box.y + at.y + dyPx, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(250);
  const after = await page.evaluate(() => ({ ...window.reverbspace.state.mic }));
  return { moved: Math.hypot(after.x - before.x, after.z - before.z), before, after };
};
const nudge = await micDrag(70, 20);
check('dragging the mic moves it by a sane amount, not to the far wall',
  !nudge.offScreen && nudge.moved > 0.05 && nudge.moved < 1.6,
  nudge.offScreen ? 'the mic was not on screen' : `${nudge.moved.toFixed(2)} m for 70 px`);
// And it must still be where you left it, not clamped against a wall.
const dims = await page.evaluate(() => ({ ...window.reverbspace.state.dims }));
check('the mic ends up inside the room, clear of the walls',
  !!nudge.after && nudge.after.x > 0.25 && nudge.after.x < dims.w - 0.25
  && nudge.after.z > 0.25 && nudge.after.z < dims.d - 0.25,
  nudge.after ? `(${nudge.after.x.toFixed(2)}, ${nudge.after.z.toFixed(2)}) in ${dims.w.toFixed(1)}x${dims.d.toFixed(1)}` : 'off screen');

const one = await step(['w'], false);
check('two keys do not walk you faster than one',
  Math.abs(Math.hypot(free.dx, free.dz) - Math.hypot(one.dx, one.dz)) < 1e-6,
  `diagonal ${Math.hypot(free.dx, free.dz).toFixed(4)} m vs straight ${Math.hypot(one.dx, one.dz).toFixed(4)} m`);

await browser.close();

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
