// Browser smoke test: does the page actually come up, does the AudioWorklet
// load, and does the room paint? Node's test runner covers the maths; this
// covers the half that only exists in a browser.
//
//   npm install          (playwright is a dev dependency)
//   npm run serve &      (or any static server on :8123)
//   node tests/browser-smoke.mjs

import { chromium } from 'playwright';
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

await page.goto(`${BASE}/index.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(600);
await page.mouse.click(700, 400);
await page.waitForTimeout(1200);

/** How much of the room canvas is actually painted. */
const painted = () => page.evaluate(() => {
  const c = document.querySelector('#room');
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let lit = 0, total = 0;
  for (let i = 0; i < d.length; i += 4000) {
    total++;
    if (d[i] > 14 || d[i + 1] > 14 || d[i + 2] > 14) lit++;
  }
  return lit / total;
});

const worklet = await page.evaluate(async () => {
  const { AudioEngine } = await import('/src/audio/engine.js');
  const e = new AudioEngine();
  try {
    await e.start();
    return { ok: true, sampleRate: e.ctx.sampleRate, node: !!e.node };
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
const rtAt = async (coverage) => page.evaluate((c) => {
  const t = document.querySelector('#treat');
  t.value = String(c);
  t.dispatchEvent(new Event('input', { bubbles: true }));
  return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => {
    r(document.querySelector('#stats dd').textContent);
  })));
}, coverage);
const bare = parseFloat(await rtAt(0));
await page.screenshot({ path: `${SHOTS}/05-studio-untreated.png` });
const treated = parseFloat(await rtAt(0.95));
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

await browser.close();

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
