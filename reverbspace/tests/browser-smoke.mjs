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
await page.waitForTimeout(1200);

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
check('the lens focuses on the mic, and a close mic softens the room',
  far.detail > near.detail * 1.15,
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
    label: document.querySelector('#treat-out').textContent,
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

// The panels at the reflection points are placed off the performer and the
// mic, so moving either of them has to move the panels.
await atStage(1);
const panelsNow = () => page.evaluate(async () => {
  const t = await import('/src/core/treatment.js');
  return JSON.stringify(t.treatmentZones(window.reverbspace.state).zones);
});
const beforeMove = await panelsNow();
await page.evaluate(() => {
  const rs = window.reverbspace;
  rs.state.source.z += 1.2;
  rs.state.mic.z += 1.2;
  rs.scene.onChange('source');
});
await page.waitForTimeout(400);
check('the reflection panels follow the performer', (await panelsNow()) !== beforeMove);

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

await browser.close();

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
