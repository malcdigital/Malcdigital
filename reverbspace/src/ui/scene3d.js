// The room, drawn in perspective and dragged around directly.
//
// Everything on screen is the same geometry the acoustics model uses: the rays
// are the real first-order reflection paths, the lobe is the real polar
// pattern, and the panels are the real treated area.

import { MATERIALS, TREATMENTS } from '../core/materials.js';
import { PRESETS_BY_ID } from '../core/presets.js';
import { MICS_BY_ID, polarGain } from '../core/mics.js';
import { reflectionPaths, SPEED_OF_SOUND } from '../core/acoustics.js';

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const lerp = (a, b, t) => a + (b - a) * t;

/** Orbit camera with a pinhole projection, plus the inverse ray for picking. */
class Camera {
  constructor() {
    this.yaw = -0.62;
    this.pitch = 0.52;
    this.distance = 22;
    this.target = { x: 0, y: 0, z: 0 };
    this.focal = 700;
    this.cx = 0;
    this.cy = 0;
  }

  update(w, h) {
    this.cx = w / 2;
    this.cy = h / 2;
    const cp = Math.cos(this.pitch);
    this.eye = {
      x: this.target.x + this.distance * cp * Math.sin(this.yaw),
      y: this.target.y + this.distance * Math.sin(this.pitch),
      z: this.target.z + this.distance * cp * Math.cos(this.yaw),
    };
    const f = norm(sub(this.target, this.eye));
    const r = norm(cross(f, { x: 0, y: 1, z: 0 }));
    const u = cross(r, f);
    this.f = f; this.r = r; this.u = u;
  }

  project(p) {
    const v = sub(p, this.eye);
    const z = dot(v, this.f);
    if (z <= 0.05) return null;
    return {
      x: this.cx + (this.focal * dot(v, this.r)) / z,
      y: this.cy - (this.focal * dot(v, this.u)) / z,
      z,
    };
  }

  /** World-space ray through a screen pixel. */
  ray(px, py) {
    const a = (px - this.cx) / this.focal;
    const b = -(py - this.cy) / this.focal;
    return norm({
      x: this.f.x + this.r.x * a + this.u.x * b,
      y: this.f.y + this.r.y * a + this.u.y * b,
      z: this.f.z + this.r.z * a + this.u.z * b,
    });
  }

  /** Where that ray crosses a horizontal plane. */
  onPlane(px, py, height) {
    const d = this.ray(px, py);
    if (Math.abs(d.y) < 1e-6) return null;
    const t = (height - this.eye.y) / d.y;
    if (t <= 0) return null;
    return { x: this.eye.x + d.x * t, y: height, z: this.eye.z + d.z * t };
  }
}

const sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });
const dot = (a, b) => a.x * b.x + a.y * b.y + a.z * b.z;
const cross = (a, b) => ({
  x: a.y * b.z - a.z * b.y,
  y: a.z * b.x - a.x * b.z,
  z: a.x * b.y - a.y * b.x,
});
const norm = (v) => {
  const l = Math.hypot(v.x, v.y, v.z) || 1;
  return { x: v.x / l, y: v.y / l, z: v.z / l };
};

const HANDLE_R = 13;

export class RoomScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.cam = new Camera();
    this.state = null;
    this.response = null;
    this.paths = [];
    this.dpr = 1;

    this.showRays = true;
    this.slowMotion = 55;      // reflections are milliseconds; slow them to watch
    this.rayClock = 0;
    this.ripples = [];

    this.drag = null;
    this.hover = null;
    this.onChange = () => {};

    this.bind();
  }

  setState(state, response) {
    this.state = state;
    this.response = response;
    this.paths = reflectionPaths(response);
    const { w, d, h } = state.dims;
    this.cam.target = { x: w / 2, y: h * 0.35, z: d / 2 };
    if (!this.framed) this.frame();
    this.needsFit = this.needsFit || !this.fitted;
    this.fitted = true;
  }

  /** Ask for a re-fit; the fit itself needs the viewport, so it runs at draw. */
  frame() {
    this.framed = true;
    this.needsFit = true;
  }

  /**
   * Pull the camera to where the room fills the stage. Projected size goes as
   * 1/distance, so scaling distance by (fill / target) converges in a couple of
   * passes whatever the room's shape or the window's aspect.
   */
  fit(W, H) {
    const { w, d, h } = this.state.dims;
    const corners = [];
    for (const x of [0, w]) for (const y of [0, h]) for (const z of [0, d]) corners.push({ x, y, z });
    this.cam.distance = Math.max(w, d, h) * 1.6 + 3;
    for (let pass = 0; pass < 6; pass++) {
      this.cam.update(W, H);
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, seen = 0;
      for (const c of corners) {
        const p = this.cam.project(c);
        if (!p) continue;
        seen++;
        if (p.x < minX) minX = p.x;
        if (p.x > maxX) maxX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.y > maxY) maxY = p.y;
      }
      if (seen < 8) { this.cam.distance *= 1.3; continue; }
      const fill = Math.max((maxX - minX) / W, (maxY - minY) / H);
      if (Math.abs(fill - 0.82) < 0.015) break;
      this.cam.distance = clamp(this.cam.distance * (fill / 0.82), 2.5, 600);
    }
    this.needsFit = false;
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.max(1, Math.round(rect.width * this.dpr));
    this.canvas.height = Math.max(1, Math.round(rect.height * this.dpr));
    this.w = rect.width;
    this.h = rect.height;
  }

  // ---------------------------------------------------------------- picking

  screenOf(p) { return this.cam.project(p); }

  get sourcePoint() {
    const s = this.state.source;
    return { x: s.x, y: s.height, z: s.z };
  }

  get micPoint() {
    const m = this.state.mic;
    return { x: m.x, y: m.height, z: m.z };
  }

  /** Wall grips sit on the floor at the middle of each wall. */
  wallGrips() {
    const { w, d } = this.state.dims;
    return [
      { id: 'z0', p: { x: w / 2, y: 0, z: 0 }, axis: 'z', side: 0 },
      { id: 'z1', p: { x: w / 2, y: 0, z: d }, axis: 'z', side: 1 },
      { id: 'x0', p: { x: 0, y: 0, z: d / 2 }, axis: 'x', side: 0 },
      { id: 'x1', p: { x: w, y: 0, z: d / 2 }, axis: 'x', side: 1 },
    ];
  }

  hitTest(px, py) {
    const targets = [
      { id: 'mic', p: this.micPoint },
      { id: 'source', p: this.sourcePoint },
    ];
    for (const g of this.wallGrips()) targets.push({ id: 'wall:' + g.id, p: g.p, grip: g });
    let best = null;
    for (const t of targets) {
      const s = this.screenOf(t.p);
      if (!s) continue;
      const dist = Math.hypot(s.x - px, s.y - py);
      if (dist < HANDLE_R + 6 && (!best || dist < best.dist)) best = { ...t, dist };
    }
    return best;
  }

  bind() {
    const c = this.canvas;
    const pos = (e) => {
      const r = c.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    c.addEventListener('pointerdown', (e) => {
      if (!this.state) return;
      const { x, y } = pos(e);
      const hit = this.hitTest(x, y);
      c.setPointerCapture(e.pointerId);
      if (hit) {
        this.drag = { kind: hit.id, grip: hit.grip, last: { x, y } };
      } else {
        this.drag = { kind: 'orbit', last: { x, y } };
      }
      e.preventDefault();
    });

    c.addEventListener('pointermove', (e) => {
      if (!this.state) return;
      const { x, y } = pos(e);
      if (!this.drag) {
        const hit = this.hitTest(x, y);
        this.hover = hit ? hit.id : null;
        c.style.cursor = hit ? 'grab' : 'move';
        return;
      }
      c.style.cursor = 'grabbing';

      if (this.drag.kind === 'orbit') {
        const dx = x - this.drag.last.x;
        const dy = y - this.drag.last.y;
        this.cam.yaw -= dx * 0.007;
        this.cam.pitch = clamp(this.cam.pitch + dy * 0.006, -0.15, 1.35);
      } else if (this.drag.kind === 'source' || this.drag.kind === 'mic') {
        const o = this.drag.kind === 'source' ? this.state.source : this.state.mic;
        const p = this.cam.onPlane(x, y, o.height);
        if (p) { o.x = p.x; o.z = p.z; this.onChange(this.drag.kind); }
      } else if (this.drag.kind.startsWith('wall:')) {
        this.dragWall(this.drag.grip, x, y);
      }
      this.drag.last = { x, y };
      e.preventDefault();
    });

    const end = (e) => {
      if (this.drag) { this.drag = null; c.style.cursor = 'move'; this.onChange('end'); }
      if (e.pointerId !== undefined && c.hasPointerCapture?.(e.pointerId)) c.releasePointerCapture(e.pointerId);
    };
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);

    c.addEventListener('wheel', (e) => {
      this.cam.distance = clamp(this.cam.distance * (1 + Math.sign(e.deltaY) * 0.09), 2.5, 400);
      e.preventDefault();
    }, { passive: false });
  }

  /** Move one wall, keeping everything else where it was in the room. */
  dragWall(grip, px, py) {
    const p = this.cam.onPlane(px, py, 0);
    if (!p) return;
    const st = this.state;
    const { w, d } = st.dims;
    const MIN = 1.6;
    if (grip.axis === 'x') {
      if (grip.side === 1) {
        st.dims.w = Math.max(MIN, p.x);
      } else {
        const shift = clamp(p.x, -200, w - MIN);
        st.dims.w = w - shift;
        st.source.x -= shift;
        st.mic.x -= shift;
      }
    } else if (grip.side === 1) {
      st.dims.d = Math.max(MIN, p.z);
    } else {
      const shift = clamp(p.z, -200, d - MIN);
      st.dims.d = d - shift;
      st.source.z -= shift;
      st.mic.z -= shift;
    }
    this.onChange('dims');
  }

  /** Kick off a floor ripple, called when a transient is played. */
  ping() {
    this.ripples.push({ t: 0, at: { ...this.sourcePoint } });
    this.rayClock = 0;
  }

  // ---------------------------------------------------------------- drawing

  render(dtMs) {
    if (!this.state) return;
    const g = this.ctx;
    const { w: W, h: H } = this;
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.clearRect(0, 0, W, H);

    const preset = PRESETS_BY_ID[this.state.presetId];
    const accent = preset.palette;

    // Backdrop.
    const bg = g.createRadialGradient(W * 0.5, H * 0.42, 10, W * 0.5, H * 0.5, Math.max(W, H) * 0.8);
    bg.addColorStop(0, '#161a22');
    bg.addColorStop(1, '#0a0c11');
    g.fillStyle = bg;
    g.fillRect(0, 0, W, H);

    if (this.needsFit) this.fit(W, H);
    this.cam.update(W, H);
    const { w, d, h } = this.state.dims;

    this.rayClock += dtMs / 1000;
    for (const r of this.ripples) r.t += dtMs / 1000;
    this.ripples = this.ripples.filter((r) => r.t < 2.2);

    this.drawWalls(g, w, d, h, accent);
    this.drawFloor(g, w, d, accent);
    this.drawSeating(g, w, d, preset);
    if (this.showRays) this.drawRays(g, accent);
    this.drawRipples(g, w, d);
    this.drawMicLobe(g, accent);
    this.drawFigures(g, accent);
    this.drawEdges(g, w, d, h);
    this.drawGrips(g);
    this.drawScaleBar(g, w, d, h);
  }

  /** Only the walls facing away from the camera, so the room stays open. */
  drawWalls(g, w, d, h, accent) {
    const cov = clamp(this.state.treatment.coverage, 0, 1);
    const treat = TREATMENTS[this.state.treatment.type] || TREATMENTS.rockwool;
    const preset = PRESETS_BY_ID[this.state.presetId];
    const wallMat = MATERIALS[preset.surfaces.walls];

    const faces = [
      { n: { x: 0, y: 0, z: -1 }, pts: [{ x: 0, y: 0, z: 0 }, { x: w, y: 0, z: 0 }, { x: w, y: h, z: 0 }, { x: 0, y: h, z: 0 }] },
      { n: { x: 0, y: 0, z: 1 }, pts: [{ x: 0, y: 0, z: d }, { x: w, y: 0, z: d }, { x: w, y: h, z: d }, { x: 0, y: h, z: d }] },
      { n: { x: -1, y: 0, z: 0 }, pts: [{ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: d }, { x: 0, y: h, z: d }, { x: 0, y: h, z: 0 }] },
      { n: { x: 1, y: 0, z: 0 }, pts: [{ x: w, y: 0, z: 0 }, { x: w, y: 0, z: d }, { x: w, y: h, z: d }, { x: w, y: h, z: 0 }] },
    ];

    for (const face of faces) {
      // The outward normal points away from the eye on the far side of the box.
      const centre = face.pts.reduce((a, p) => ({ x: a.x + p.x / 4, y: a.y + p.y / 4, z: a.z + p.z / 4 }), { x: 0, y: 0, z: 0 });
      if (dot(face.n, sub(centre, this.cam.eye)) < 0) continue;

      const poly = face.pts.map((p) => this.cam.project(p));
      if (poly.some((p) => !p)) continue;

      g.beginPath();
      g.moveTo(poly[0].x, poly[0].y);
      for (let i = 1; i < poly.length; i++) g.lineTo(poly[i].x, poly[i].y);
      g.closePath();
      g.fillStyle = shade(wallMat.colour, 0.30);
      g.fill();
      g.strokeStyle = 'rgba(255,255,255,0.09)';
      g.lineWidth = 1;
      g.stroke();

      if (cov > 0.02) this.drawPanels(g, face, cov, treat, w, d, h);
    }
  }

  /** Treatment tiles, laid out over the fraction of the wall actually covered. */
  drawPanels(g, face, cov, treat, w, d, h) {
    const horizontal = face.n.z !== 0 ? w : d;
    const cols = Math.max(2, Math.round(horizontal / 1.6));
    const rows = Math.max(2, Math.round(h / 1.5));
    const total = cols * rows;
    const want = Math.round(total * clamp(cov, 0, 0.95));
    if (want <= 0) return;

    // Deterministic scatter: the same coverage always draws the same panels.
    const order = [];
    for (let i = 0; i < total; i++) order.push(i);
    let seed = 12345;
    for (let i = total - 1; i > 0; i--) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      const j = seed % (i + 1);
      [order[i], order[j]] = [order[j], order[i]];
    }

    const base = face.pts[0];
    const along = face.n.z !== 0 ? 'x' : 'z';
    const gap = 0.13;

    g.fillStyle = hexA(treat.colour, 0.82);
    g.strokeStyle = 'rgba(0,0,0,0.35)';
    g.lineWidth = 1;
    for (let k = 0; k < want; k++) {
      const idx = order[k];
      const c = idx % cols, r = (idx / cols) | 0;
      const a0 = (c / cols) * horizontal + gap;
      const a1 = ((c + 1) / cols) * horizontal - gap;
      const y0 = (r / rows) * h + gap;
      const y1 = ((r + 1) / rows) * h - gap;
      const quad = [[a0, y0], [a1, y0], [a1, y1], [a0, y1]].map(([a, y]) => {
        const p = { x: base.x, y, z: base.z };
        p[along] = a;
        return this.cam.project(p);
      });
      if (quad.some((p) => !p)) continue;
      g.beginPath();
      g.moveTo(quad[0].x, quad[0].y);
      for (let i = 1; i < 4; i++) g.lineTo(quad[i].x, quad[i].y);
      g.closePath();
      g.fill();
      g.stroke();
    }
  }

  drawFloor(g, w, d, accent) {
    const preset = PRESETS_BY_ID[this.state.presetId];
    const mat = MATERIALS[preset.surfaces.floor];
    const quad = [{ x: 0, y: 0, z: 0 }, { x: w, y: 0, z: 0 }, { x: w, y: 0, z: d }, { x: 0, y: 0, z: d }]
      .map((p) => this.cam.project(p));
    if (quad.some((p) => !p)) return;
    g.beginPath();
    g.moveTo(quad[0].x, quad[0].y);
    for (let i = 1; i < 4; i++) g.lineTo(quad[i].x, quad[i].y);
    g.closePath();
    g.fillStyle = shade(mat.colour, 0.34);
    g.fill();

    // A one-metre grid, so size reads as a real dimension rather than a number.
    g.strokeStyle = 'rgba(255,255,255,0.055)';
    g.lineWidth = 1;
    const step = w > 40 || d > 40 ? 5 : 1;
    g.beginPath();
    for (let x = 0; x <= w + 1e-6; x += step) {
      const a = this.cam.project({ x: Math.min(x, w), y: 0, z: 0 });
      const b = this.cam.project({ x: Math.min(x, w), y: 0, z: d });
      if (a && b) { g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); }
    }
    for (let z = 0; z <= d + 1e-6; z += step) {
      const a = this.cam.project({ x: 0, y: 0, z: Math.min(z, d) });
      const b = this.cam.project({ x: w, y: 0, z: Math.min(z, d) });
      if (a && b) { g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); }
    }
    g.stroke();
  }

  drawSeating(g, w, d, preset) {
    if (!preset.seating) return;
    const rows = clamp(Math.round(d * preset.seating.coverage / 1.1), 3, 26);
    const cols = clamp(Math.round(w / 1.1), 4, 30);
    const z0 = d * (1 - preset.seating.coverage);
    const mat = MATERIALS[preset.seating.material];
    g.fillStyle = shade(mat.colour, 0.7);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = ((c + 0.5) / cols) * w;
        const z = z0 + ((r + 0.5) / rows) * (d - z0);
        const p = this.cam.project({ x, y: 0.42, z });
        if (!p) continue;
        const s = clamp((this.cam.focal / p.z) * 0.2, 0.6, 9);
        g.fillRect(p.x - s / 2, p.y - s, s, s * 1.35);
      }
    }
  }

  /** The real first-order paths, with a pulse running along each at scaled speed. */
  drawRays(g, accent) {
    const src = this.sourcePoint;
    const mic = this.micPoint;
    const maxDelay = this.paths.length
      ? Math.max(this.response.direct.delay, ...this.paths.map((p) => p.delay))
      : this.response.direct.delay;
    const cycle = maxDelay * this.slowMotion + 0.75;
    const t = this.rayClock % cycle;
    const scaled = t / this.slowMotion;   // "sound time" this frame is showing

    const peak = Math.max(this.response.direct.left[3], ...this.paths.map((p) => p.amp), 1e-6);

    // Direct path.
    this.drawRay(g, [src, mic], this.response.direct.delay, scaled,
      Math.abs(this.response.direct.left[3]) / peak, '#ffffff', 2.2);

    for (const p of this.paths) {
      const colour = p.surface === 'ceiling' ? '#7fd6ff' : p.surface === 'floor' ? '#ffc46b' : accent;
      this.drawRay(g, [src, p.hit, mic], p.delay, scaled, p.amp / peak, colour, 1.6);
    }
  }

  drawRay(g, pts, delay, scaled, strength, colour, width) {
    const proj = pts.map((p) => this.cam.project(p));
    if (proj.some((p) => !p)) return;

    const alpha = clamp(0.10 + strength * 0.45, 0.06, 0.6);
    g.strokeStyle = hexA(colour, alpha);
    g.lineWidth = width;
    g.setLineDash(pts.length > 2 ? [5, 6] : []);
    g.beginPath();
    g.moveTo(proj[0].x, proj[0].y);
    for (let i = 1; i < proj.length; i++) g.lineTo(proj[i].x, proj[i].y);
    g.stroke();
    g.setLineDash([]);

    // Bounce marker.
    if (pts.length > 2) {
      g.fillStyle = hexA(colour, alpha + 0.15);
      g.beginPath();
      g.arc(proj[1].x, proj[1].y, 3, 0, Math.PI * 2);
      g.fill();
    }

    // The wavefront itself, at however far sound has travelled this cycle.
    const travelled = scaled * SPEED_OF_SOUND;
    let total = 0;
    const segs = [];
    for (let i = 1; i < pts.length; i++) {
      const len = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y, pts[i].z - pts[i - 1].z);
      segs.push(len);
      total += len;
    }
    if (travelled <= 0 || travelled > total) return;

    let run = travelled;
    let seg = 0;
    while (seg < segs.length && run > segs[seg]) { run -= segs[seg]; seg++; }
    if (seg >= segs.length) return;
    const f = run / segs[seg];
    const a = pts[seg], b = pts[seg + 1];
    const here = this.cam.project({
      x: lerp(a.x, b.x, f), y: lerp(a.y, b.y, f), z: lerp(a.z, b.z, f),
    });
    if (!here) return;
    const r = clamp(3 + strength * 5, 2.5, 9);
    const glow = g.createRadialGradient(here.x, here.y, 0, here.x, here.y, r * 2.6);
    glow.addColorStop(0, hexA(colour, 0.95));
    glow.addColorStop(1, hexA(colour, 0));
    g.fillStyle = glow;
    g.beginPath();
    g.arc(here.x, here.y, r * 2.6, 0, Math.PI * 2);
    g.fill();
  }

  drawRipples(g, w, d) {
    for (const r of this.ripples) {
      const radius = r.t * SPEED_OF_SOUND / this.slowMotion;
      if (radius > Math.hypot(w, d) * 1.2) continue;
      const alpha = clamp(0.4 * (1 - r.t / 2.2), 0, 0.4);
      g.strokeStyle = `rgba(255,255,255,${alpha})`;
      g.lineWidth = 1.4;
      g.beginPath();
      let started = false;
      for (let a = 0; a <= Math.PI * 2 + 0.01; a += Math.PI / 40) {
        const p = this.cam.project({
          x: r.at.x + Math.cos(a) * radius, y: 0.02, z: r.at.z + Math.sin(a) * radius,
        });
        if (!p) { started = false; continue; }
        if (!started) { g.moveTo(p.x, p.y); started = true; } else g.lineTo(p.x, p.y);
      }
      g.stroke();
    }
  }

  /** The mic's actual polar pattern, swept in the horizontal plane. */
  drawMicLobe(g, accent) {
    const mic = MICS_BY_ID[this.state.mic.id];
    if (!mic) return;
    const m = this.micPoint;
    const az = this.state.mic.azimuth;
    const reach = clamp(Math.min(this.state.dims.w, this.state.dims.d) * 0.22, 0.5, 4.5);
    const spread = ((mic.spread || 0) * Math.PI) / 360;

    for (const side of mic.spread ? [-spread, spread] : [0]) {
      const pts = [];
      for (let i = 0; i <= 72; i++) {
        const th = (i / 72) * Math.PI * 2;
        const r = Math.abs(polarGain(mic, th)) * reach;
        const world = az + side + th;
        pts.push(this.cam.project({
          x: m.x + Math.sin(world) * r,
          y: m.y,
          z: m.z + Math.cos(world) * r,
        }));
      }
      if (pts.some((p) => !p)) continue;
      g.beginPath();
      g.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) g.lineTo(pts[i].x, pts[i].y);
      g.closePath();
      g.fillStyle = hexA(accent, 0.13);
      g.fill();
      g.strokeStyle = hexA(accent, 0.5);
      g.lineWidth = 1.3;
      g.stroke();
    }
  }

  drawFigures(g, accent) {
    const items = [
      { p: this.sourcePoint, kind: 'source' },
      { p: this.micPoint, kind: 'mic' },
    ].sort((a, b) => (this.cam.project(b.p)?.z ?? 0) - (this.cam.project(a.p)?.z ?? 0));

    for (const it of items) {
      const s = this.cam.project(it.p);
      if (!s) continue;
      const base = this.cam.project({ x: it.p.x, y: 0, z: it.p.z });
      const scale = clamp(this.cam.focal / s.z, 6, 300);
      const active = this.hover === it.kind || this.drag?.kind === it.kind;

      // Stand / body line down to the floor, so height reads clearly.
      if (base) {
        g.strokeStyle = 'rgba(255,255,255,0.28)';
        g.lineWidth = 1;
        g.setLineDash([3, 4]);
        g.beginPath();
        g.moveTo(base.x, base.y);
        g.lineTo(s.x, s.y);
        g.stroke();
        g.setLineDash([]);

        g.fillStyle = 'rgba(0,0,0,0.35)';
        g.beginPath();
        g.ellipse(base.x, base.y, scale * 0.055, scale * 0.022, 0, 0, Math.PI * 2);
        g.fill();
      }

      const r = clamp(scale * 0.05, 7, 22);
      if (it.kind === 'source') {
        const glow = g.createRadialGradient(s.x, s.y, 0, s.x, s.y, r * 3.4);
        glow.addColorStop(0, hexA('#ffd98a', 0.5));
        glow.addColorStop(1, hexA('#ffd98a', 0));
        g.fillStyle = glow;
        g.beginPath();
        g.arc(s.x, s.y, r * 3.4, 0, Math.PI * 2);
        g.fill();

        g.fillStyle = '#ffd98a';
        g.beginPath();
        g.arc(s.x, s.y - r * 0.55, r * 0.52, 0, Math.PI * 2);   // head
        g.fill();
        g.beginPath();
        g.moveTo(s.x - r * 0.6, s.y + r * 1.15);
        g.quadraticCurveTo(s.x, s.y - r * 0.25, s.x + r * 0.6, s.y + r * 1.15);
        g.closePath();
        g.fill();
      } else {
        g.fillStyle = '#e9edf5';
        g.strokeStyle = '#11141b';
        g.lineWidth = 1.5;
        g.beginPath();
        g.ellipse(s.x, s.y, r * 0.42, r * 0.62, 0, 0, Math.PI * 2);
        g.fill();
        g.stroke();
        // A stub pointing the way the capsule faces.
        const az = this.state.mic.azimuth;
        const tip = this.cam.project({
          x: this.micPoint.x + Math.sin(az) * 0.45,
          y: this.micPoint.y,
          z: this.micPoint.z + Math.cos(az) * 0.45,
        });
        if (tip) {
          g.strokeStyle = accent;
          g.lineWidth = 2;
          g.beginPath();
          g.moveTo(s.x, s.y);
          g.lineTo(tip.x, tip.y);
          g.stroke();
        }
      }

      if (active) {
        g.strokeStyle = '#ffffff';
        g.lineWidth = 1.5;
        g.beginPath();
        g.arc(s.x, s.y, r * 1.7, 0, Math.PI * 2);
        g.stroke();
      }
    }
  }

  drawEdges(g, w, d, h) {
    const corners = [
      [{ x: 0, y: 0, z: 0 }, { x: w, y: 0, z: 0 }], [{ x: w, y: 0, z: 0 }, { x: w, y: 0, z: d }],
      [{ x: w, y: 0, z: d }, { x: 0, y: 0, z: d }], [{ x: 0, y: 0, z: d }, { x: 0, y: 0, z: 0 }],
      [{ x: 0, y: h, z: 0 }, { x: w, y: h, z: 0 }], [{ x: w, y: h, z: 0 }, { x: w, y: h, z: d }],
      [{ x: w, y: h, z: d }, { x: 0, y: h, z: d }], [{ x: 0, y: h, z: d }, { x: 0, y: h, z: 0 }],
      [{ x: 0, y: 0, z: 0 }, { x: 0, y: h, z: 0 }], [{ x: w, y: 0, z: 0 }, { x: w, y: h, z: 0 }],
      [{ x: w, y: 0, z: d }, { x: w, y: h, z: d }], [{ x: 0, y: 0, z: d }, { x: 0, y: h, z: d }],
    ];
    g.strokeStyle = 'rgba(255,255,255,0.17)';
    g.lineWidth = 1;
    g.beginPath();
    for (const [a, b] of corners) {
      const pa = this.cam.project(a), pb = this.cam.project(b);
      if (pa && pb) { g.moveTo(pa.x, pa.y); g.lineTo(pb.x, pb.y); }
    }
    g.stroke();
  }

  drawGrips(g) {
    for (const grip of this.wallGrips()) {
      const s = this.cam.project(grip.p);
      if (!s) continue;
      const active = this.hover === 'wall:' + grip.id || this.drag?.grip?.id === grip.id;
      g.fillStyle = active ? '#ffffff' : 'rgba(255,255,255,0.4)';
      g.strokeStyle = 'rgba(0,0,0,0.5)';
      g.lineWidth = 1;
      g.beginPath();
      g.arc(s.x, s.y, active ? 7 : 5, 0, Math.PI * 2);
      g.fill();
      g.stroke();
    }
  }

  /** A metre stick, so the room's size is legible without reading the panel. */
  drawScaleBar(g, w, d, h) {
    const a = this.cam.project({ x: 0, y: 0, z: 0 });
    const b = this.cam.project({ x: Math.min(5, w), y: 0, z: 0 });
    g.font = '11px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.fillStyle = 'rgba(255,255,255,0.55)';
    if (a && b) {
      g.strokeStyle = 'rgba(255,255,255,0.4)';
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(a.x, a.y);
      g.lineTo(b.x, b.y);
      g.stroke();
      g.fillText(`${Math.min(5, w).toFixed(0)} m`, (a.x + b.x) / 2 - 10, (a.y + b.y) / 2 + 16);
    }
    g.fillStyle = 'rgba(255,255,255,0.75)';
    g.font = '12px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.fillText(`${w.toFixed(1)} x ${d.toFixed(1)} x ${h.toFixed(1)} m`, 14, 22);
    g.fillStyle = 'rgba(255,255,255,0.45)';
    g.fillText(`${Math.round(w * d * h).toLocaleString()} m3`, 14, 40);
  }
}

// ---------------------------------------------------------------- colours

function hexA(hex, a) {
  const { r, g, b } = parse(hex);
  return `rgba(${r},${g},${b},${a})`;
}

function shade(hex, k) {
  const { r, g, b } = parse(hex);
  return `rgb(${Math.round(r * k)},${Math.round(g * k)},${Math.round(b * k)})`;
}

function parse(hex) {
  const s = hex.replace('#', '');
  const n = parseInt(s.length === 3 ? s.split('').map((c) => c + c).join('') : s, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
