// Median frame time for one preset, plus a screenshot of it.
//   node tools/frame-time.mjs studio
//
// Headless Chromium rasterises on the CPU, so the absolute number means
// nothing -- it is four to five hundred milliseconds for a frame a GPU draws
// in one. Use it to compare a change against the same run before it.
import { chromium } from 'playwright';
import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
function findChrome() {
  const root = '/opt/pw-browsers';
  for (const d of readdirSync(root)) {
    if (d.startsWith('chromium-')) { const e = join(root, d, 'chrome-linux', 'chrome'); if (existsSync(e)) return e; }
  }
}
const preset = process.argv[2];
const b = await chromium.launch({ executablePath: findChrome(), args: ['--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
p.on('pageerror', (e) => console.log('PAGEERROR', e.message));
p.on('crash', () => console.log('PAGE CRASHED'));
await p.goto('http://localhost:8123/index.html', { waitUntil: 'networkidle' });
await p.waitForTimeout(800);
await p.mouse.click(500, 400);
await p.waitForTimeout(900);
await p.click(`.preset[data-id="${preset}"]`);
await p.waitForTimeout(1200);
// Keep the scene moving so the render loop actually runs, and time real frames.
const ms = await p.evaluate(() => new Promise((res) => {
  const rs = window.reverbspace.scene;
  const times = [];
  let last = performance.now();
  let n = 0;
  const tick = () => {
    rs.cam.yaw += 0.006;
    const now = performance.now();
    if (n++ > 5) times.push(now - last);
    last = now;
    if (n < 70) requestAnimationFrame(tick);
    else { times.sort((a, b) => a - b); res(times[Math.floor(times.length / 2)]); }
  };
  requestAnimationFrame(tick);
}));
console.log(`${preset.padEnd(10)} median frame ${ms.toFixed(1)} ms`);
await p.screenshot({ path: `shots/P-${preset}.png` });
await b.close();
