// One close-up per microphone model, so each can be judged against the thing
// it is meant to be.   node tools/mic-shots.mjs
import { chromium } from 'playwright';
import { existsSync, readdirSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

function findChrome() {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || '/opt/pw-browsers';
  for (const d of readdirSync(root)) {
    if (d.startsWith('chromium-')) {
      const e = join(root, d, 'chrome-linux', 'chrome');
      if (existsSync(e)) return e;
    }
  }
}
mkdirSync('shots', { recursive: true });
const BASE = process.env.BASE_URL || 'http://localhost:8123/index.html';
const b = await chromium.launch({ executablePath: findChrome(), args: ['--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage({ viewport: { width: 820, height: 700 } });
p.on('pageerror', (e) => console.log('PAGEERROR', e.message));
await p.goto(BASE, { waitUntil: 'networkidle' });
await p.waitForTimeout(800);
await p.mouse.click(300, 300);
await p.waitForTimeout(900);

for (const id of ['ldc', 'sdc', 'dynamic', 'ribbon', 'shotgun', 'xy']) {
  await p.selectOption('#mic-type', id);
  await p.waitForTimeout(500);
  await p.evaluate(() => {
    const rs = window.reverbspace, s = rs.state;
    // Three-quarters and slightly above. Head-on, an SM7B is a black disc and
    // a shotgun is a dot -- the length is the whole of what tells them apart.
    s.source.x = 3.7; s.source.z = 4.0;
    s.mic.x = 3.5; s.mic.z = 3.05; s.mic.height = 1.42;
    s.mic.aimAtSource = false;
    s.mic.azimuth = Math.PI * 0.72;
    rs.scene.cam.eyeAt = { x: 3.7, y: 1.5, z: 4.0 };
    rs.scene.cam.yaw = Math.PI * 1.06; rs.scene.cam.pitch = -0.12;
    rs.scene.cam.fov = 26;       // a long lens: these are small objects
    rs.scene.onChange('mic');
  });
  await p.waitForTimeout(700);
  await p.screenshot({ path: `shots/M-${id}.png` });
  console.log('captured', id);
}
await b.close();
