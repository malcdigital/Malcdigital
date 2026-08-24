// Screenshot the room from inside, at a few placed viewpoints.
// Needs `npm start` running.   node tools/room-shots.mjs
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
const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
p.on('pageerror', (e) => console.log('PAGEERROR', e.message));
await p.goto(BASE, { waitUntil: 'networkidle' });
await p.waitForTimeout(700);
await p.mouse.click(500, 400);
await p.waitForTimeout(900);

/** Stand somewhere, face a direction, and put the mic that far in front. */
const place = (spec) => p.evaluate(([sx, sz, yaw, pitch, micDist]) => {
  const rs = window.reverbspace;
  rs.state.source.x = sx;
  rs.state.source.z = sz;
  rs.state.mic.x = sx + Math.sin(yaw) * micDist;
  rs.state.mic.z = sz + Math.cos(yaw) * micDist;
  rs.scene.cam.eyeAt = { x: sx, y: rs.state.source.height - 0.1, z: sz };
  rs.scene.cam.yaw = yaw;
  rs.scene.cam.pitch = pitch;
  rs.scene.onChange('source');
}, spec.slice(1));

const shot = async (name, spec) => {
  await p.click(`.preset[data-id="${spec[0]}"]`);
  await p.waitForTimeout(600);
  await place(spec);
  await p.waitForTimeout(700);
  await place(spec);       // again: the preset reset positions on the first pass
  await p.waitForTimeout(500);
  await p.screenshot({ path: `shots/v-${name}.png` });
  console.log('captured', name);
};

await shot('studio-mic', ['studio', 3.7, 4.2, Math.PI, -0.06, 0.9]);
await shot('studio-along', ['studio', 2.2, 4.4, -2.2, 0.02, 1.1]);
await shot('studio-up', ['studio', 3.7, 3.2, 2.6, 0.5, 1.0]);
await shot('studio-floor', ['studio', 3.7, 3.0, 2.4, -0.62, 1.0]);
await shot('hall-inside', ['hall', 13, 30, Math.PI, 0.06, 3]);
await shot('cathedral-inside', ['cathedral', 12, 50, Math.PI, 0.22, 5]);
await b.close();
