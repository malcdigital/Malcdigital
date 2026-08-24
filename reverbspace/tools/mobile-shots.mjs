// Screenshot the app at real phone and tablet sizes, sheet closed and open.
// Needs `npm start` running.   node tools/mobile-shots.mjs
import { chromium, devices } from 'playwright';
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
/** A real finger drag: pointer events, not a mouse. */
async function page_drag(p, x0, y0, x1, y1) {
  await p.evaluate(([ax, ay, bx, by]) => {
    // The HUD canvas sits over the WebGL one and is what pointers land on.
    const el = document.querySelector('#room-hud') || document.querySelector('#room');
    const send = (type, x, y, extra = {}) => el.dispatchEvent(new PointerEvent(type, {
      pointerId: 1, pointerType: 'touch', isPrimary: true, bubbles: true, cancelable: true,
      clientX: x, clientY: y, ...extra,
    }));
    const r = el.getBoundingClientRect();
    send('pointerdown', ax, ay);
    for (let i = 1; i <= 10; i++) {
      send('pointermove', ax + (bx - ax) * (i / 10), ay + (by - ay) * (i / 10));
    }
    send('pointerup', bx, by);
    void r;
  }, [x0, y0, x1, y1]);
}

const browser = await chromium.launch({ executablePath: findChrome(), args: ['--autoplay-policy=no-user-gesture-required'] });

const cases = [
  ['phone-portrait', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: Number(process.env.DPR || 1) }],
  ['phone-landscape', { viewport: { width: 844, height: 390 }, isMobile: true, hasTouch: true, deviceScaleFactor: Number(process.env.DPR || 1) }],
  ['tablet', { viewport: { width: 820, height: 1180 }, isMobile: true, hasTouch: true, deviceScaleFactor: Number(process.env.DPR || 1) }],
];

for (const [name, opts] of cases) {
  const ctx = await browser.newContext(opts);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(BASE, { waitUntil: 'networkidle' });
  await p.waitForTimeout(600);
  await p.tap ? await p.tap('#room').catch(() => p.mouse.click(100, 200)) : await p.mouse.click(100, 200);
  await p.waitForTimeout(900);

  const stageShare = await p.evaluate(() => {
    const c = document.querySelector('#room').getBoundingClientRect();
    return { stage: Math.round(c.height), vh: window.innerHeight, pct: Math.round((c.height / window.innerHeight) * 100) };
  });
  await p.screenshot({ path: `shots/m-${name}-closed.png` });

  await p.click('#sheet-handle');
  await p.waitForTimeout(600);
  const openInfo = await p.evaluate(() => ({
    reserved: Math.round(window.reverbspace.scene.reserved),
    visible: Math.round(document.querySelector('#sheet').getBoundingClientRect().top),
  }));
  await p.screenshot({ path: `shots/m-${name}-open.png` });

  // Close it again and check the room responds to touch.
  await p.click('#sheet-handle');
  await p.waitForTimeout(450);
  const before = await p.evaluate(() => ({
    yaw: window.reverbspace.scene.cam.yaw,
    d: window.reverbspace.state.mic.x,
  }));
  const box = await p.locator('#room').boundingBox();
  await p.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  await page_drag(p, box.x + box.width * 0.7, box.y + box.height * 0.45,
                     box.x + box.width * 0.3, box.y + box.height * 0.5);
  await p.waitForTimeout(350);
  const after = await p.evaluate(() => window.reverbspace.scene.cam.yaw);
  const looked = Math.abs(after - before.yaw) > 0.05;
  console.log(`${name.padEnd(16)} touch look: ${looked ? 'ok' : 'FAILED'} (yaw ${before.yaw.toFixed(2)} -> ${after.toFixed(2)})`);

  console.log(`${name.padEnd(16)} room ${stageShare.stage}px of ${stageShare.vh}px (${stageShare.pct}%)`,
    `| open: sheet top ${openInfo.visible}px, reserved ${openInfo.reserved}px`,
    errs.length ? `| ERRORS ${errs.join(';')}` : '');
  await ctx.close();
}
await browser.close();
