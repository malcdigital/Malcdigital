// One frame per step of the treatment plan, from a fixed viewpoint, so the
// placement can be judged as a sequence.   node tools/stage-shots.mjs [type]
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
const type = process.argv[2] || 'rockwool';
mkdirSync('shots', { recursive: true });
const b = await chromium.launch({ executablePath: findChrome(), args: ['--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage({ viewport: { width: 900, height: 640 } });
p.on('pageerror', (e) => console.log('PAGEERROR', e.message));
await p.goto(process.env.BASE_URL || 'http://localhost:8123/index.html', { waitUntil: 'networkidle' });
await p.waitForTimeout(800);
await p.mouse.click(350, 300);
await p.waitForTimeout(900);
await p.selectOption('#treat-type', type);
await p.waitForTimeout(400);

for (let stage = 0; stage <= 6; stage++) {
  await p.evaluate((st) => {
    const el = document.querySelector('#treat');
    el.value = String(st);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, stage);
  await p.waitForTimeout(500);
  const name = await p.evaluate(() => {
    const rs = window.reverbspace;
    // From outside: a placement plan is about the whole room, and four walls
    // at once is the only view that shows whether it looks deliberate.
    rs.scene.setMode('orbit');
    rs.scene.framed = false;
    // From a corner, looking diagonally across: two walls, the ceiling and a
    // corner all in one frame, which is what the plan has to be judged on.
    rs.scene.cam.orbitYaw = -0.7;
    rs.scene.cam.orbitPitch = 0.6;
    rs.scene.onChange('source');
    return document.querySelector('#treat-out').textContent;
  });
  await p.waitForTimeout(600);
  await p.screenshot({ path: `shots/S${stage}-${type}.png` });
  console.log(stage, name);
}
await b.close();
