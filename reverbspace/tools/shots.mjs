// Capture reference screenshots of each space, from both cameras.
// Needs `npm start` running.  node tools/shots.mjs
import { chromium } from 'playwright';
import { existsSync, readdirSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
function findChrome() {
  const root = '/opt/pw-browsers';
  for (const d of readdirSync(root)) {
    if (d.startsWith('chromium-')) {
      const e = join(root, d, 'chrome-linux', 'chrome');
      if (existsSync(e)) return e;
    }
  }
}
mkdirSync('shots', { recursive: true });
const b = await chromium.launch({ executablePath: findChrome(), args: ['--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage({ viewport: { width: 1500, height: 940 } });
await p.goto(process.env.BASE_URL || 'http://localhost:8123/index.html', { waitUntil: 'networkidle' });
await p.waitForTimeout(700);
await p.mouse.click(700, 400);
await p.waitForTimeout(900);

const look = (yawDeg, pitchDeg) => p.evaluate(([y, pi]) => {
  window.reverbspace.scene.cam.yaw = y * Math.PI / 180;
  window.reverbspace.scene.cam.pitch = pi * Math.PI / 180;
}, [yawDeg, pitchDeg]);

const shot = async (name, ms = 450) => { await p.waitForTimeout(ms); await p.screenshot({ path: `shots/${name}.png` }); };

await shot('fp-studio-ahead');
await look(180, 22); await shot('fp-studio-up');
await p.click('#view-orbit'); await shot('orbit-studio', 700);
await p.click('#view-first');
await p.click('.preset[data-id="cathedral"]'); await p.waitForTimeout(500);
await look(0, 14); await shot('fp-cathedral');
await p.click('.preset[data-id="hall"]'); await p.waitForTimeout(500);
await look(0, 6); await shot('fp-hall');
await b.close();
console.log('shots written');
