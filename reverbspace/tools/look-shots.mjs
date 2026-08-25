// A fixed set of viewpoints for judging the look, so two runs are comparable.
//   node tools/look-shots.mjs [suffix]
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
const tag = process.argv[2] || '';
mkdirSync('shots', { recursive: true });
const BASE = process.env.BASE_URL || 'http://localhost:8123/index.html';
const b = await chromium.launch({ executablePath: findChrome(), args: ['--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage({ viewport: { width: 1000, height: 760 } });
p.on('pageerror', (e) => console.log('PAGEERROR', e.message));
await p.goto(BASE, { waitUntil: 'networkidle' });
await p.waitForTimeout(800);
await p.mouse.click(400, 380);
await p.waitForTimeout(900);

const place = (sx, sy, sz, yaw, pitch, micDist) => p.evaluate(([sx, sy, sz, yaw, pitch, micDist]) => {
  const rs = window.reverbspace;
  rs.state.source.x = sx; rs.state.source.z = sz;
  rs.state.mic.x = sx + Math.sin(yaw) * micDist;
  rs.state.mic.z = sz + Math.cos(yaw) * micDist;
  rs.scene.cam.eyeAt = { x: sx, y: sy, z: sz };
  rs.scene.cam.yaw = yaw; rs.scene.cam.pitch = pitch;
  rs.scene.onChange('source');
}, [sx, sy, sz, yaw, pitch, micDist]);

const shots = [
  ['floor',  3.6, 1.5, 3.0,  2.40, -0.55, 1.0],   // raking light down the boards
  ['gear',   5.0, 1.5, 3.5,  1.40, -0.22, 1.1],   // piano, guitar, chrome
  ['deep',   3.4, 1.5, 5.0,  3.14,  0.02, 1.2],   // the length of the room
  ['lamp',   3.7, 1.5, 3.2,  2.60,  0.42, 1.0],   // straight at a pendant
  ['mic',    3.7, 1.5, 4.2,  3.14, -0.06, 0.6],   // mic close, wall far
];
for (const [name, ...spec] of shots) {
  await place(...spec);
  await p.waitForTimeout(600);
  await place(...spec);
  await p.waitForTimeout(500);
  await p.screenshot({ path: `shots/L-${name}${tag}.png` });
  console.log('captured', name);
}
// And the same room from outside, where the lens focuses on its middle.
await p.click('.viewmode [data-mode="orbit"]').catch(() => p.click('text=From outside'));
await p.waitForTimeout(1400);
await p.screenshot({ path: `shots/L-orbit${tag}.png` });
console.log('captured orbit');

await b.close();
