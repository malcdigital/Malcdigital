// The room, seen from where you are standing in it.
//
// Two cameras over one renderer: first person, with your eyes at the
// performer's head and the mic in front of you, and an outside orbit view for
// placing things. Everything drawn is the geometry the acoustics model uses --
// the rays are the real reflection paths, the lobe is the real polar pattern,
// and the panels on the walls and ceiling are the real treated area.

import { MATERIALS, TREATMENTS } from '../core/materials.js';
import { PRESETS_BY_ID } from '../core/presets.js';
import { MICS_BY_ID, polarGain } from '../core/mics.js';
import { reflectionPaths, SPEED_OF_SOUND } from '../core/acoustics.js';

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const lerp = (a, b, t) => a + (b - a) * t;
const NEAR = 0.08;

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

/** Stable pseudo-random in [0,1) from a pair of integers. */
function hash2(a, b) {
  let n = (a * 374761393 + b * 668265263) | 0;
  n = (n ^ (n >> 13)) * 1274126177;
  return ((n ^ (n >> 16)) >>> 0) / 4294967296;
}

// -------------------------------------------------------------------- camera

class Camera {
  constructor() {
    this.mode = 'first';
    this.yaw = 0;
    this.pitch = 0;
    this.orbitYaw = -0.62;
    this.orbitPitch = 0.52;
    this.distance = 22;
    this.target = { x: 0, y: 0, z: 0 };
    this.eyeAt = { x: 0, y: 1.6, z: 0 };
    this.fov = 74;
    this.orbitFov = 52;
    /** Pixels to lift the vanishing point by, when something covers the bottom. */
    this.bias = 0;
  }

  update(w, h) {
    this.cx = w / 2;
    this.cy = h / 2 - this.bias;
    const fov = this.mode === 'first' ? this.fov : this.orbitFov;
    // Size the lens off the long edge. Driving it from the width alone gives a
    // portrait phone a ~100 degree vertical field, which bends the room.
    this.focal = (Math.max(w, h) / 2) / Math.tan((fov * Math.PI) / 360);

    if (this.mode === 'first') {
      this.eye = { ...this.eyeAt };
      const cp = Math.cos(this.pitch);
      this.f = norm({ x: Math.sin(this.yaw) * cp, y: Math.sin(this.pitch), z: Math.cos(this.yaw) * cp });
    } else {
      const cp = Math.cos(this.orbitPitch);
      this.eye = {
        x: this.target.x + this.distance * cp * Math.sin(this.orbitYaw),
        y: this.target.y + this.distance * Math.sin(this.orbitPitch),
        z: this.target.z + this.distance * cp * Math.cos(this.orbitYaw),
      };
      this.f = norm(sub(this.target, this.eye));
    }
    this.r = norm(cross(this.f, { x: 0, y: 1, z: 0 }));
    this.u = cross(this.r, this.f);
  }

  toCam(p) {
    const v = sub(p, this.eye);
    return { x: dot(v, this.r), y: dot(v, this.u), z: dot(v, this.f) };
  }

  fromCam(c) {
    return { x: this.cx + (this.focal * c.x) / c.z, y: this.cy - (this.focal * c.y) / c.z };
  }

  project(p) {
    const c = this.toCam(p);
    if (c.z <= NEAR) return null;
    const s = this.fromCam(c);
    s.z = c.z;
    return s;
  }

  /**
   * Clip a polygon against the near plane, then project.
   *
   * Standing inside the room means walls routinely straddle the camera; without
   * this they would vanish the moment one corner slipped behind the eye.
   */
  poly(pts) {
    const cam = pts.map((p) => this.toCam(p));
    const out = [];
    for (let i = 0; i < cam.length; i++) {
      const a = cam[i], b = cam[(i + 1) % cam.length];
      const ain = a.z >= NEAR, bin = b.z >= NEAR;
      if (ain) out.push(a);
      if (ain !== bin) {
        const t = (NEAR - a.z) / (b.z - a.z);
        out.push({ x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t), z: NEAR });
      }
    }
    if (out.length < 3) return null;
    let depth = 0;
    for (const c of out) depth += c.z;
    const screen = out.map((c) => this.fromCam(c));
    screen.depth = depth / out.length;
    return screen;
  }

  ray(px, py) {
    const a = (px - this.cx) / this.focal;
    const b = -(py - this.cy) / this.focal;
    return norm({
      x: this.f.x + this.r.x * a + this.u.x * b,
      y: this.f.y + this.r.y * a + this.u.y * b,
      z: this.f.z + this.r.z * a + this.u.z * b,
    });
  }

  onPlane(px, py, height) {
    const d = this.ray(px, py);
    if (Math.abs(d.y) < 1e-6) return null;
    const t = (height - this.eye.y) / d.y;
    if (t <= 0) return null;
    return { x: this.eye.x + d.x * t, y: height, z: this.eye.z + d.z * t };
  }
}

// -------------------------------------------------------------------- colour

function parse(hex) {
  const s = hex.replace('#', '');
  const n = parseInt(s.length === 3 ? s.split('').map((c) => c + c).join('') : s, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
function hexA(hex, a) {
  const { r, g, b } = parse(hex);
  return `rgba(${r},${g},${b},${a})`;
}
const FOG = { r: 9, g: 11, b: 16 };

/** Material colour at a given brightness, faded into the dark by distance. */
function shade(rgb, mul, fog) {
  const r = rgb.r * mul, g = rgb.g * mul, b = rgb.b * mul;
  return `rgb(${Math.round(lerp(r, FOG.r, fog))},${Math.round(lerp(g, FOG.g, fog))},${Math.round(lerp(b, FOG.b, fog))})`;
}

const LIGHT = norm({ x: 0.3, y: 1, z: 0.25 });

/** Quads forming a tube from a to b: enough to read as a mic body or a stand. */
function tubeQuads(a, b, r, sides = 10) {
  const ax = norm(sub(b, a));
  const helper = Math.abs(ax.y) > 0.9 ? { x: 1, y: 0, z: 0 } : { x: 0, y: 1, z: 0 };
  const u = norm(cross(ax, helper));
  const v = cross(ax, u);
  const ring = (p) => {
    const out = [];
    for (let i = 0; i < sides; i++) {
      const t = (i / sides) * Math.PI * 2;
      const c = Math.cos(t) * r, sn = Math.sin(t) * r;
      out.push({
        x: p.x + u.x * c + v.x * sn,
        y: p.y + u.y * c + v.y * sn,
        z: p.z + u.z * c + v.z * sn,
      });
    }
    return out;
  };
  const A = ring(a), B = ring(b);
  const quads = [];
  for (let i = 0; i < sides; i++) {
    const j = (i + 1) % sides;
    quads.push([A[i], A[j], B[j], B[i]]);
  }
  return { quads, capA: A, capB: B };
}

/** The six faces of an axis-aligned box. */
function boxQuads(a, b) {
  const P = (x, y, z) => ({ x, y, z });
  const [x0, x1] = [Math.min(a.x, b.x), Math.max(a.x, b.x)];
  const [y0, y1] = [Math.min(a.y, b.y), Math.max(a.y, b.y)];
  const [z0, z1] = [Math.min(a.z, b.z), Math.max(a.z, b.z)];
  return [
    [P(x0, y0, z0), P(x1, y0, z0), P(x1, y1, z0), P(x0, y1, z0)],
    [P(x1, y0, z1), P(x0, y0, z1), P(x0, y1, z1), P(x1, y1, z1)],
    [P(x0, y0, z1), P(x0, y0, z0), P(x0, y1, z0), P(x0, y1, z1)],
    [P(x1, y0, z0), P(x1, y0, z1), P(x1, y1, z1), P(x1, y1, z0)],
    [P(x0, y0, z1), P(x1, y0, z1), P(x1, y0, z0), P(x0, y0, z0)],
    [P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)],
  ];
}

/**
 * Nudge a coplanar decoration off its wall.
 *
 * Sorting by depth cannot separate two things in the same plane: blocks at the
 * near end of a wall sort in front of a window at the far end and chew holes in
 * it. Standing the decoration slightly proud of the surface makes the depth
 * order true rather than fudged.
 */
function proud(pts, n, dist) {
  return pts.map((p) => ({ x: p.x + n.x * dist, y: p.y + n.y * dist, z: p.z + n.z * dist }));
}

const HANDLE_R = 15;
const EYE_DROP = 0.10;        // mouth height to eye height
const WALK = 3.2;             // metres per second

export class RoomScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.cam = new Camera();
    this.state = null;
    this.response = null;
    this.paths = [];
    this.dpr = 1;
    this.w = 1;
    this.h = 1;

    /** Height at the bottom of the canvas that something else is covering. */
    this.reserved = 0;
    this.showRays = true;
    this.slowMotion = 55;
    this.rayClock = 0;
    this.ripples = [];
    this.keys = new Set();

    this.drag = null;
    this.hover = null;
    this.onChange = () => {};
    this.onModeChange = () => {};

    this.bind();
  }

  get mode() { return this.cam.mode; }

  setMode(mode) {
    this.cam.mode = mode;
    if (mode === 'first') this.lookAtMic();
    else this.needsFit = true;
    this.onModeChange(mode);
  }

  setState(state, response) {
    this.state = state;
    this.response = response;
    this.paths = reflectionPaths(response);
    const { w, d, h } = state.dims;
    this.cam.target = { x: w / 2, y: h * 0.35, z: d / 2 };
    this.cam.eyeAt = { x: state.source.x, y: Math.max(0.3, state.source.height - EYE_DROP), z: state.source.z };
    if (!this.framed) { this.framed = true; this.needsFit = true; this.lookAtMic(); }
  }

  /** Point the first-person camera at the mic. */
  lookAtMic() {
    if (!this.state) return;
    const m = this.micPoint;
    const e = this.cam.eyeAt;
    const dx = m.x - e.x, dz = m.z - e.z, dy = m.y - e.y;
    const flat = Math.hypot(dx, dz);
    this.cam.yaw = Math.atan2(dx, dz);
    this.cam.pitch = clamp(Math.atan2(dy, Math.max(flat, 0.1)), -0.9, 0.9);
  }

  frame() { this.framed = true; this.needsFit = true; }

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
        minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
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

  get sourcePoint() {
    const s = this.state.source;
    return { x: s.x, y: s.height, z: s.z };
  }

  get micPoint() {
    const m = this.state.mic;
    return { x: m.x, y: m.height, z: m.z };
  }

  screenOf(p) { return this.cam.project(p); }

  ping() {
    this.ripples.push({ t: 0, at: { ...this.sourcePoint } });
    this.rayClock = 0;
  }

  // ------------------------------------------------------------ room surfaces

  faces() {
    const p = PRESETS_BY_ID[this.state.presetId];
    const { w, d, h } = this.state.dims;
    const wall = MATERIALS[p.surfaces.walls];
    // `n` is the inward normal and `mid` the face centre; together they decide
    // whether a surface is drawn. Standing inside, the eye is on the inward
    // side of all six. From outside, the near walls and the ceiling fail the
    // test and drop away, so the room stays open to look into.
    return [
      { id: 'floor', kind: 'floor', mat: MATERIALS[p.surfaces.floor], light: 1.0,
        n: { x: 0, y: 1, z: 0 }, mid: { x: w / 2, y: 0, z: d / 2 },
        uLen: w, vLen: d, at: (u, v) => ({ x: u, y: 0, z: v }) },
      { id: 'ceiling', kind: 'ceiling', mat: MATERIALS[p.surfaces.ceiling], light: 0.84,
        n: { x: 0, y: -1, z: 0 }, mid: { x: w / 2, y: h, z: d / 2 },
        uLen: w, vLen: d, at: (u, v) => ({ x: u, y: h, z: v }) },
      { id: 'z0', kind: 'wall', mat: wall, light: 0.78, axis: 'z', side: 0,
        n: { x: 0, y: 0, z: 1 }, mid: { x: w / 2, y: h / 2, z: 0 },
        uLen: w, vLen: h, at: (u, v) => ({ x: u, y: v, z: 0 }) },
      { id: 'z1', kind: 'wall', mat: wall, light: 0.70, axis: 'z', side: 1,
        n: { x: 0, y: 0, z: -1 }, mid: { x: w / 2, y: h / 2, z: d },
        uLen: w, vLen: h, at: (u, v) => ({ x: w - u, y: v, z: d }) },
      { id: 'x0', kind: 'wall', mat: wall, light: 0.90, axis: 'x', side: 0,
        n: { x: 1, y: 0, z: 0 }, mid: { x: 0, y: h / 2, z: d / 2 },
        uLen: d, vLen: h, at: (u, v) => ({ x: 0, y: v, z: d - u }) },
      { id: 'x1', kind: 'wall', mat: wall, light: 0.86, axis: 'x', side: 1,
        n: { x: -1, y: 0, z: 0 }, mid: { x: w, y: h / 2, z: d / 2 },
        uLen: d, vLen: h, at: (u, v) => ({ x: w, y: v, z: u }) },
    ];
  }

  /** True when the eye is on the room side of a surface. */
  visible(face) {
    return dot(face.n, sub(this.cam.eye, face.mid)) > 0;
  }

  /**
   * Sort key shared by everything on one wall: the wall's farthest corner.
   *
   * A wall is one flat plane whose own pieces never overlap each other, but its
   * depth can span the length of the room. Sorting its blocks individually puts
   * near blocks in front of far windows and eats holes in them. Keying the
   * whole wall on its farthest point puts it behind everything standing in
   * front of it, and `sub` then orders the wall's own layers.
   */
  faceKey(face) {
    let far = 0;
    for (const [u, v] of [[0, 0], [face.uLen, 0], [face.uLen, face.vLen], [0, face.vLen]]) {
      const c = this.cam.toCam(face.at(u, v));
      if (c.z > far) far = c.z;
    }
    return far;
  }

  /** Break a face into the strips its material is actually made of. */
  strips(face) {
    const pattern = face.mat.pattern || 'smooth';
    const out = [];
    const push = (u0, v0, u1, v1, seed) => out.push({ u0, v0, u1, v1, seed });

    if (pattern === 'planks') {
      // Boards run up the walls and down the length of a floor.
      const along = face.kind === 'wall' ? 'u' : 'v';
      const width = face.kind === 'wall' ? 0.24 : 0.16;
      if (along === 'u') {
        const n = Math.max(2, Math.round(face.uLen / width));
        for (let i = 0; i < n; i++) {
          push((i / n) * face.uLen, 0, ((i + 1) / n) * face.uLen, face.vLen, i);
        }
      } else {
        const n = Math.max(2, Math.round(face.uLen / width));
        const boardLen = 2.4;
        for (let i = 0; i < n; i++) {
          const u0 = (i / n) * face.uLen, u1 = ((i + 1) / n) * face.uLen;
          const offset = hash2(i, 7) * boardLen;
          for (let v = -offset; v < face.vLen; v += boardLen) {
            push(u0, Math.max(0, v), u1, Math.min(face.vLen, v + boardLen), i * 31 + Math.round(v));
          }
        }
      }
    } else if (pattern === 'blocks' || pattern === 'bricks') {
      const rowH = pattern === 'bricks' ? 0.085 : 0.52;
      const blockW = pattern === 'bricks' ? 0.22 : 1.15;
      const rows = clamp(Math.round(face.vLen / rowH), 2, 90);
      for (let r = 0; r < rows; r++) {
        const v0 = (r / rows) * face.vLen, v1 = ((r + 1) / rows) * face.vLen;
        const offset = (r % 2) * blockW * 0.5;
        for (let u = -offset; u < face.uLen; u += blockW) {
          push(Math.max(0, u), v0, Math.min(face.uLen, u + blockW), v1, r * 53 + Math.round(u));
        }
      }
    } else if (pattern === 'tiles') {
      const size = 1.05;
      const nu = clamp(Math.round(face.uLen / size), 1, 70);
      const nv = clamp(Math.round(face.vLen / size), 1, 70);
      for (let i = 0; i < nu; i++) {
        for (let j = 0; j < nv; j++) {
          push((i / nu) * face.uLen, (j / nv) * face.vLen,
               ((i + 1) / nu) * face.uLen, ((j + 1) / nv) * face.vLen, i * 17 + j);
        }
      }
    } else {
      push(0, 0, face.uLen, face.vLen, 1);
    }
    return out;
  }

  drawFace(g, face, list) {
    if (!this.visible(face)) return;
    const rgb = parse(face.mat.colour);
    const grain = face.mat.grain ?? 0.06;
    const seam = face.mat.pattern === 'smooth' ? null : 'rgba(0,0,0,0.20)';
    // Walls sort as one unit; floors and ceilings stay per-strip so that things
    // standing on them interleave correctly.
    const wallKey = face.kind === 'wall' ? this.faceKey(face) : null;
    for (const s of this.strips(face)) {
      const quad = [
        face.at(s.u0, s.v0), face.at(s.u1, s.v0),
        face.at(s.u1, s.v1), face.at(s.u0, s.v1),
      ];
      const poly = this.cam.poly(quad);
      if (!poly) continue;
      const vary = 1 + (hash2(s.seed, face.id.charCodeAt(0)) - 0.5) * grain * 2;
      const fog = this.fogAt(poly.depth);
      list.push({
        z: wallKey ?? poly.depth,
        sub: 0,
        draw: () => {
          g.fillStyle = shade(rgb, face.light * vary, fog);
          fillPoly(g, poly);
          if (seam) {
            g.strokeStyle = seam;
            g.lineWidth = 0.7;
            g.stroke();
          }
        },
      });
    }
  }

  fogAt(depth) {
    const { w, d } = this.state.dims;
    const far = Math.max(18, Math.hypot(w, d) * 1.1);
    return clamp(1 - Math.exp(-depth / far), 0, 0.88);
  }

  // ------------------------------------------------------------- acoustic kit

  /**
   * Treatment on the walls, as slabs standing off the surface, and suspended
   * over the room as clouds. The count is the coverage the model is using.
   */
  drawTreatment(g, list) {
    const cov = clamp(this.state.treatment.coverage, 0, 1);
    if (cov < 0.02) return;
    const treat = TREATMENTS[this.state.treatment.type] || TREATMENTS.rockwool;
    const rgb = parse(treat.colour);
    const { w, d, h } = this.state.dims;

    for (const face of this.faces()) {
      if (face.kind !== 'wall') continue;
      // Panel-sized panels, and a bounded grid so a cathedral wall does not
      // ask for three thousand of them.
      const cols = clamp(Math.round(face.uLen / clamp(face.uLen / 12, 0.8, 3.2)), 3, 16);
      const rows = clamp(Math.round(face.vLen / clamp(face.vLen / 6, 0.8, 3.2)), 2, 10);
      const total = cols * rows;
      const want = Math.round(total * clamp(cov, 0, 0.92));
      const order = shuffled(total, face.id.charCodeAt(1) || 3);
      const wallKey = this.faceKey(face);
      const off = 0.07;
      const nrm = face.id[0] === 'z'
        ? { x: 0, y: 0, z: face.side === 0 ? off : -off }
        : { x: face.side === 0 ? off : -off, y: 0, z: 0 };

      for (let k = 0; k < want; k++) {
        const idx = order[k];
        const c = idx % cols, r = (idx / cols) | 0;
        const pad = Math.min(0.14, face.uLen / cols * 0.12);
        const u0 = (c / cols) * face.uLen + pad, u1 = ((c + 1) / cols) * face.uLen - pad;
        const v0 = (r / rows) * face.vLen + pad, v1 = ((r + 1) / rows) * face.vLen - pad;
        if (u1 <= u0 || v1 <= v0) continue;
        const quad = [[u0, v0], [u1, v0], [u1, v1], [u0, v1]]
          .map(([u, v]) => { const p = face.at(u, v); return { x: p.x + nrm.x, y: p.y + nrm.y, z: p.z + nrm.z }; });
        const poly = this.cam.poly(quad);
        if (!poly) continue;
        const fog = this.fogAt(poly.depth);
        const vary = 1 + (hash2(idx, 11) - 0.5) * 0.18;
        list.push({
          z: wallKey,
          sub: 1,
          draw: () => {
            g.fillStyle = shade(rgb, 1.0 * vary, fog);
            fillPoly(g, poly);
            g.strokeStyle = 'rgba(0,0,0,0.32)';
            g.lineWidth = 1;
            g.stroke();
          },
        });
      }
    }

    // Clouds: horizontal absorbers hung under the ceiling.
    const clouds = Math.round(clamp(cov, 0, 1) * clamp((w * d) / 2.6, 4, 44));
    const cw = clamp(Math.min(w, d) * 0.16, 0.8, 2.2);
    const cd = cw * 0.62;
    for (let i = 0; i < clouds; i++) {
      const rx = hash2(i, 101), rz = hash2(i, 211), rd = hash2(i, 307);
      const cx = lerp(cw, w - cw, rx);
      const cz = lerp(cd, d - cd, rz);
      const drop = lerp(0.22, 0.85, rd) * clamp(h / 3.2, 0.6, 2.4);
      const y = h - drop;
      if (y < this.state.source.height + 0.35) continue;
      const rot = (hash2(i, 401) - 0.5) * 0.9;
      const ca = Math.cos(rot), sa = Math.sin(rot);
      const corners = [[-cw / 2, -cd / 2], [cw / 2, -cd / 2], [cw / 2, cd / 2], [-cw / 2, cd / 2]]
        .map(([a, b]) => ({ x: cx + a * ca - b * sa, y, z: cz + a * sa + b * ca }));
      const under = this.cam.poly(corners);
      const top = this.cam.poly(corners.map((p) => ({ ...p, y: y + 0.1 })));
      // A shadow on the floor, so a cloud reads as hanging rather than lying
      // there -- from above, with the ceiling culled away, nothing else says
      // which of the two it is.
      const shadow = this.cam.poly(corners.map((p) => ({
        x: cx + (p.x - cx) * 1.15, y: 0.015, z: cz + (p.z - cz) * 1.15,
      })));
      if (!under) continue;
      const fog = this.fogAt(under.depth);
      const vary = 1 + (hash2(i, 13) - 0.5) * 0.22;
      // Chains up to the ceiling.
      const chains = [corners[0], corners[2]].map((p) => this.cam.poly([
        { ...p, y: y + 0.1 }, { ...p, y: h }, { x: p.x + 0.02, y: h, z: p.z },
      ]));
      if (shadow) {
        list.push({
          z: shadow.depth,
          draw: () => {
            g.fillStyle = `rgba(0,0,0,${0.16 + drop * 0.06})`;
            fillPoly(g, shadow);
          },
        });
      }
      list.push({
        z: under.depth,
        draw: () => {
          for (const ch of chains) {
            if (!ch) continue;
            g.strokeStyle = 'rgba(255,255,255,0.22)';
            g.lineWidth = 1;
            g.beginPath();
            g.moveTo(ch[0].x, ch[0].y);
            g.lineTo(ch[1].x, ch[1].y);
            g.stroke();
          }
          if (top) { g.fillStyle = shade(rgb, 1.15 * vary, fog); fillPoly(g, top); }
          g.fillStyle = shade(rgb, 0.72 * vary, fog);
          fillPoly(g, under);
          g.strokeStyle = 'rgba(0,0,0,0.3)';
          g.lineWidth = 1;
          g.stroke();
        },
      });
    }
  }

  /** Exposed beams, where the ceiling is timber. They break up the plank field. */
  drawBeams(g, list) {
    const preset = PRESETS_BY_ID[this.state.presetId];
    const mat = MATERIALS[preset.surfaces.ceiling];
    if (!mat || mat.pattern !== 'planks') return;
    if (!this.visible(this.faces().find((f) => f.id === 'ceiling'))) return;
    const { w, d, h } = this.state.dims;
    const n = clamp(Math.round(d / 2.2), 2, 14);
    const depth = clamp(h * 0.06, 0.1, 0.35);
    const rgb = parse(mat.colour);
    for (let i = 0; i < n; i++) {
      const z = ((i + 0.5) / n) * d;
      this.solid(g, list,
        boxQuads({ x: 0, y: h - depth, z: z - depth * 0.45 }, { x: w, y: h, z: z + depth * 0.45 }),
        rgb, { mul: 0.82, bias: -0.01 });
    }
  }

  /** Sconces, a control-room window, a door: what tells you the scale of a room. */
  drawFixtures(g, list) {
    const { w, d, h } = this.state.dims;
    const preset = PRESETS_BY_ID[this.state.presetId];

    for (const face of this.faces()) {
      if (face.kind !== 'wall' || !this.visible(face)) continue;
      const n = clamp(Math.round(face.uLen / 4.5), 1, 10);
      const wallKey = this.faceKey(face);
      const y = clamp(h * 0.55, 1.5, 4.2);
      for (let i = 0; i < n; i++) {
        const u = ((i + 0.5) / n) * face.uLen;
        const quad = proud([[u - 0.16, y - 0.16], [u + 0.16, y - 0.16], [u + 0.16, y + 0.16], [u - 0.16, y + 0.16]]
          .map(([a, b]) => face.at(a, b)), face.n, 0.06);
        const poly = this.cam.poly(quad);
        if (!poly) continue;
        const centre = poly.reduce((acc, p) => ({ x: acc.x + p.x / poly.length, y: acc.y + p.y / poly.length }), { x: 0, y: 0 });
        const size = Math.max(14, (this.cam.focal / poly.depth) * 0.9);
        list.push({
          z: wallKey,
          sub: 3,
          draw: () => {
            const glow = g.createRadialGradient(centre.x, centre.y, 0, centre.x, centre.y, size);
            glow.addColorStop(0, 'rgba(255,214,150,0.42)');
            glow.addColorStop(1, 'rgba(255,214,150,0)');
            g.fillStyle = glow;
            g.beginPath();
            g.arc(centre.x, centre.y, size, 0, Math.PI * 2);
            g.fill();
            g.fillStyle = 'rgba(255,232,190,0.92)';
            fillPoly(g, poly);
          },
        });
      }
    }

    // A window into the control room, on the wall you start out facing.
    if (preset.id === 'studio' || preset.id === 'theater') {
      const face = this.faces().find((f) => f.id === 'z0');
      if (this.visible(face)) {
      const cw = clamp(face.uLen * 0.22, 1.2, 2.6);
      const u = face.uLen * 0.5, y = clamp(h * 0.42, 1.0, 1.6);
      const quad = proud([[u - cw / 2, y - 0.45], [u + cw / 2, y - 0.45],
                          [u + cw / 2, y + 0.45], [u - cw / 2, y + 0.45]]
        .map(([a, b]) => face.at(a, b)), face.n, 0.05);
      const poly = this.cam.poly(quad);
      if (poly) {
        list.push({
          z: this.faceKey(face),
          sub: 2,
          draw: () => {
            g.fillStyle = 'rgba(58,50,38,0.96)';
            fillPoly(g, poly);
            g.fillStyle = 'rgba(255,206,138,0.20)';
            g.fill();
            g.strokeStyle = 'rgba(20,14,8,0.85)';
            g.lineWidth = 3;
            g.stroke();
          },
        });
      }
      }
    }

    // Stained glass, where the model says the walls are part glazing.
    if (preset.wallBlend && preset.wallBlend.material === 'glass') {
      const glass = parse(MATERIALS.glass.colour);
      for (const face of this.faces()) {
        if (face.kind !== 'wall' || face.axis !== 'x' || !this.visible(face)) continue;
        const n = clamp(Math.round(face.uLen / 9), 2, 9);
        for (let i = 0; i < n; i++) {
          const u = ((i + 0.5) / n) * face.uLen;
          const ww = clamp(face.uLen / n * 0.3, 0.8, 3);
          const y0 = h * 0.32, y1 = h * 0.78;
          const quad = proud([[u - ww, y0], [u + ww, y0], [u + ww, y1], [u - ww, y1]]
            .map(([a, b]) => face.at(a, b)), face.n, 0.05);
          const poly = this.cam.poly(quad);
          if (!poly) continue;
          const fog = this.fogAt(poly.depth);
          list.push({
            z: this.faceKey(face),
            sub: 2,
            draw: () => {
              g.fillStyle = shade(glass, 1.5, fog * 0.5);
              fillPoly(g, poly);
              g.strokeStyle = 'rgba(0,0,0,0.5)';
              g.lineWidth = 2;
              g.stroke();
            },
          });
        }
      }
    }

    // A door, so a wall has something human-sized on it.
    const dFace = this.faces().find((f) => f.id === 'x0');
    if (!this.visible(dFace)) return;
    const dq = [[dFace.uLen * 0.24 - 0.45, 0], [dFace.uLen * 0.24 + 0.45, 0],
                [dFace.uLen * 0.24 + 0.45, 2.05], [dFace.uLen * 0.24 - 0.45, 2.05]]
      .map(([a, b]) => dFace.at(a, Math.min(b, h - 0.05)));
    const dp = this.cam.poly(proud(dq, dFace.n, 0.05));
    if (dp) {
      const fog = this.fogAt(dp.depth);
      list.push({
        z: this.faceKey(dFace),
        sub: 2,
        draw: () => {
          g.fillStyle = shade({ r: 108, g: 74, b: 44 }, 0.9, fog);
          fillPoly(g, dp);
          g.strokeStyle = 'rgba(0,0,0,0.5)';
          g.lineWidth = 2;
          g.stroke();
        },
      });
    }
  }

  /**
   * A solid, so it holds up at the fifteen centimetres a vocal mic actually
   * sits at: foot, column, boom, body and grille, all real geometry, shaded by
   * facing and depth like everything else in the room.
   */
  solid(g, list, quads, rgb, opts = {}) {
    const bias = opts.bias || 0;
    for (const quad of quads) {
      const n = norm(cross(sub(quad[1], quad[0]), sub(quad[2], quad[0])));
      const centre = quad.reduce((a, p) => ({
        x: a.x + p.x / quad.length, y: a.y + p.y / quad.length, z: a.z + p.z / quad.length,
      }), { x: 0, y: 0, z: 0 });
      if (!opts.twoSided && dot(n, sub(this.cam.eye, centre)) <= 0) continue;
      const poly = this.cam.poly(quad);
      if (!poly) continue;
      const fog = this.fogAt(poly.depth);
      const lambert = 0.42 + 0.58 * Math.max(0, Math.abs(dot(n, LIGHT)));
      list.push({
        z: poly.depth + bias,
        draw: () => { g.fillStyle = shade(rgb, lambert * (opts.mul || 1), fog); fillPoly(g, poly); },
      });
    }
  }

  drawMic(g, list) {
    const mic = MICS_BY_ID[this.state.mic.id];
    const m = this.micPoint;
    const az = this.state.mic.azimuth;
    const active = this.hover === 'mic' || this.drag?.kind === 'mic';
    const fwd = { x: Math.sin(az), y: 0, z: Math.cos(az) };

    const STEEL = { r: 46, g: 51, b: 62 };
    const BODY = active ? { r: 232, g: 238, b: 250 } : { r: 176, g: 184, b: 199 };
    const GRILLE = { r: 108, g: 116, b: 132 };

    // Tripod foot.
    for (let i = 0; i < 3; i++) {
      const a = az + (i / 3) * Math.PI * 2;
      const toe = { x: m.x + Math.sin(a) * 0.3, y: 0.015, z: m.z + Math.cos(a) * 0.3 };
      this.solid(g, list, tubeQuads({ x: m.x, y: 0.05, z: m.z }, toe, 0.016, 6).quads, STEEL);
    }
    // Column up to just under the capsule, then a short boom back to it.
    const neck = { x: m.x, y: Math.max(0.1, m.y - 0.22), z: m.z };
    this.solid(g, list, tubeQuads({ x: m.x, y: 0.04, z: m.z }, neck, 0.018, 8).quads, STEEL);
    const bodyBack = {
      x: m.x - fwd.x * 0.055, y: m.y, z: m.z - fwd.z * 0.055,
    };
    this.solid(g, list, tubeQuads(neck, bodyBack, 0.013, 6).quads, STEEL);

    // Capsule: body then grille, pointing the way the mic is aimed.
    const bodyFront = { x: m.x + fwd.x * 0.045, y: m.y, z: m.z + fwd.z * 0.045 };
    const body = tubeQuads(bodyBack, bodyFront, 0.027, 12);
    this.solid(g, list, body.quads, BODY, { bias: -0.004 });
    const grilleFront = { x: m.x + fwd.x * 0.105, y: m.y, z: m.z + fwd.z * 0.105 };
    const grille = tubeQuads(bodyFront, grilleFront, 0.033, 12);
    this.solid(g, list, grille.quads, GRILLE, { bias: -0.006 });
    // The grille, as a mesh rather than a disc -- aimed at you, this is most of
    // what you see of the mic, and a flat circle reads as a blob.
    const cap = this.cam.poly(grille.capB);
    if (cap) {
      const fog = this.fogAt(cap.depth);
      const centre = cap.reduce((a, pt) => ({ x: a.x + pt.x / cap.length, y: a.y + pt.y / cap.length }),
        { x: 0, y: 0 });
      list.push({
        z: cap.depth - 0.008,
        draw: () => {
          g.fillStyle = shade(GRILLE, 0.92, fog);
          fillPoly(g, cap);
          g.save();
          g.clip();
          g.strokeStyle = 'rgba(20,24,32,0.55)';
          g.lineWidth = 1;
          for (const k of [0.72, 0.45, 0.2]) {
            g.beginPath();
            cap.forEach((pt, i) => {
              const x = centre.x + (pt.x - centre.x) * k, y = centre.y + (pt.y - centre.y) * k;
              i ? g.lineTo(x, y) : g.moveTo(x, y);
            });
            g.closePath();
            g.stroke();
          }
          for (let i = 0; i < cap.length; i += 2) {
            g.beginPath();
            g.moveTo(centre.x, centre.y);
            g.lineTo(cap[i].x, cap[i].y);
            g.stroke();
          }
          g.restore();
          g.strokeStyle = shade(BODY, 0.7, fog);
          g.lineWidth = 2;
          fillPoly(g, cap, true);
          g.stroke();
        },
      });
    }

    // Shock-mount cradle: the detail that makes it read as a studio mic even
    // when you are staring straight down the grille.
    const cradleAt = { x: m.x - fwd.x * 0.02, y: m.y, z: m.z - fwd.z * 0.02 };
    const cradle = [];
    for (let i = 0; i < 16; i++) {
      const th = (i / 16) * Math.PI * 2;
      cradle.push({
        x: cradleAt.x + Math.cos(th) * 0.072 * Math.cos(az + Math.PI / 2),
        y: cradleAt.y + Math.sin(th) * 0.072,
        z: cradleAt.z + Math.cos(th) * 0.072 * Math.sin(az + Math.PI / 2),
      });
    }
    const ring = this.cam.poly(cradle);
    if (ring) {
      const fog = this.fogAt(ring.depth);
      list.push({
        z: ring.depth + 0.002,
        draw: () => {
          g.strokeStyle = shade(STEEL, 1.9, fog);
          g.lineWidth = Math.max(1.5, (this.cam.focal / ring.depth) * 0.008);
          fillPoly(g, ring, true);
          g.stroke();
        },
      });
    }

    // The polar pattern it is listening through, swept at capsule height.
    const reach = clamp(Math.min(this.state.dims.w, this.state.dims.d) * 0.16, 0.35, 2.4);
    const spread = ((mic?.spread || 0) * Math.PI) / 360;
    const accent = PRESETS_BY_ID[this.state.presetId].palette;
    for (const side of mic?.spread ? [-spread, spread] : [0]) {
      const ring = [];
      for (let i = 0; i < 72; i++) {
        const th = (i / 72) * Math.PI * 2;
        const r = Math.abs(polarGain(mic, th)) * reach;
        const world = az + side + th;
        ring.push({ x: m.x + Math.sin(world) * r, y: m.y, z: m.z + Math.cos(world) * r });
      }
      const poly = this.cam.poly(ring);
      if (!poly) continue;
      list.push({
        z: poly.depth + 0.4,
        draw: () => {
          g.fillStyle = hexA(accent, 0.11);
          fillPoly(g, poly);
          g.strokeStyle = hexA(accent, 0.42);
          g.lineWidth = 1.3;
          g.stroke();
        },
      });
    }
  }

  /** In the outside view, you are a figure in the room rather than the camera. */
  drawPerformer(g, list) {
    if (this.cam.mode === 'first') return;
    const s = this.sourcePoint;
    const head = this.cam.project(s);
    const base = this.cam.project({ x: s.x, y: 0, z: s.z });
    if (!head) return;
    const scale = clamp(this.cam.focal / head.z, 6, 600);
    const active = this.hover === 'source' || this.drag?.kind === 'source';
    list.push({
      z: head.z,
      draw: () => {
        const r = clamp(scale * 0.05, 6, 26);
        if (base) {
          g.fillStyle = 'rgba(0,0,0,0.4)';
          g.beginPath();
          g.ellipse(base.x, base.y, r * 0.7, r * 0.26, 0, 0, Math.PI * 2);
          g.fill();
        }
        const glow = g.createRadialGradient(head.x, head.y, 0, head.x, head.y, r * 3.2);
        glow.addColorStop(0, 'rgba(255,217,138,0.5)');
        glow.addColorStop(1, 'rgba(255,217,138,0)');
        g.fillStyle = glow;
        g.beginPath();
        g.arc(head.x, head.y, r * 3.2, 0, Math.PI * 2);
        g.fill();
        g.fillStyle = '#ffd98a';
        g.beginPath();
        g.arc(head.x, head.y - r * 0.5, r * 0.5, 0, Math.PI * 2);
        g.fill();
        g.beginPath();
        g.moveTo(head.x - r * 0.62, head.y + r * 1.2);
        g.quadraticCurveTo(head.x, head.y - r * 0.2, head.x + r * 0.62, head.y + r * 1.2);
        g.closePath();
        g.fill();
        if (active) {
          g.strokeStyle = '#fff';
          g.lineWidth = 1.5;
          g.beginPath();
          g.arc(head.x, head.y, r * 1.8, 0, Math.PI * 2);
          g.stroke();
        }
      },
    });
  }

  // -------------------------------------------------------------------- rays

  drawRays(g) {
    const src = this.sourcePoint;
    const mic = this.micPoint;
    const maxDelay = this.paths.length
      ? Math.max(this.response.direct.delay, ...this.paths.map((p) => p.delay))
      : this.response.direct.delay;
    const cycle = maxDelay * this.slowMotion + 0.75;
    const scaled = (this.rayClock % cycle) / this.slowMotion;
    const accent = PRESETS_BY_ID[this.state.presetId].palette;
    const peak = Math.max(Math.abs(this.response.direct.left[3]), ...this.paths.map((p) => p.amp), 1e-6);

    this.ray(g, [src, mic], scaled, Math.abs(this.response.direct.left[3]) / peak, '#ffffff', 2.2);
    for (const p of this.paths) {
      const colour = p.surface === 'ceiling' ? '#7fd6ff' : p.surface === 'floor' ? '#ffc46b' : accent;
      this.ray(g, [src, p.hit, mic], scaled, p.amp / peak, colour, 1.6);
    }
  }

  ray(g, pts, scaled, strength, colour, width) {
    const segs = [];
    let total = 0;
    for (let i = 1; i < pts.length; i++) {
      const l = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y, pts[i].z - pts[i - 1].z);
      segs.push(l);
      total += l;
    }
    const alpha = clamp(0.08 + strength * 0.42, 0.05, 0.55);

    g.strokeStyle = hexA(colour, alpha);
    g.lineWidth = width;
    g.setLineDash(pts.length > 2 ? [5, 6] : []);
    for (let i = 1; i < pts.length; i++) {
      const seg = this.cam.poly([pts[i - 1], pts[i], pts[i]]);
      if (!seg || seg.length < 2) continue;
      g.beginPath();
      g.moveTo(seg[0].x, seg[0].y);
      g.lineTo(seg[1].x, seg[1].y);
      g.stroke();
    }
    g.setLineDash([]);

    if (pts.length > 2) {
      const b = this.cam.project(pts[1]);
      if (b) {
        g.fillStyle = hexA(colour, alpha + 0.2);
        g.beginPath();
        g.arc(b.x, b.y, 3.5, 0, Math.PI * 2);
        g.fill();
      }
    }

    const travelled = scaled * SPEED_OF_SOUND;
    if (travelled <= 0 || travelled > total) return;
    let run = travelled, seg = 0;
    while (seg < segs.length && run > segs[seg]) { run -= segs[seg]; seg++; }
    if (seg >= segs.length) return;
    const f = run / segs[seg];
    const a = pts[seg], b = pts[seg + 1];
    const here = this.cam.project({ x: lerp(a.x, b.x, f), y: lerp(a.y, b.y, f), z: lerp(a.z, b.z, f) });
    if (!here) return;
    const r = clamp(3 + strength * 5, 2.5, 10);
    const glow = g.createRadialGradient(here.x, here.y, 0, here.x, here.y, r * 2.8);
    glow.addColorStop(0, hexA(colour, 0.95));
    glow.addColorStop(1, hexA(colour, 0));
    g.fillStyle = glow;
    g.beginPath();
    g.arc(here.x, here.y, r * 2.8, 0, Math.PI * 2);
    g.fill();
  }

  drawRipples(g) {
    const { w, d } = this.state.dims;
    for (const r of this.ripples) {
      const radius = (r.t * SPEED_OF_SOUND) / this.slowMotion;
      if (radius > Math.hypot(w, d) * 1.2) continue;
      const alpha = clamp(0.42 * (1 - r.t / 2.2), 0, 0.42);
      const ring = [];
      for (let a = 0; a < Math.PI * 2; a += Math.PI / 48) {
        ring.push({ x: r.at.x + Math.cos(a) * radius, y: 0.02, z: r.at.z + Math.sin(a) * radius });
      }
      const poly = this.cam.poly(ring);
      if (!poly) continue;
      g.strokeStyle = `rgba(255,255,255,${alpha})`;
      g.lineWidth = 1.5;
      fillPoly(g, poly, true);
      g.stroke();
    }
  }

  // ----------------------------------------------------------------- minimap

  minimapRect() {
    const { w, d } = this.state.dims;
    // Sized off the canvas, so it stays a plan in the corner on a phone rather
    // than taking half the screen.
    const maxW = clamp(this.w * 0.3, 84, 176);
    const maxH = clamp(this.h * 0.24, 68, 148);
    const scale = Math.min(maxW / w, maxH / d);
    const bottom = this.h - this.reserved - 34;
    return { x: 14, y: bottom - d * scale, w: w * scale, h: d * scale, scale };
  }

  drawMinimap(g) {
    // With the controls sheet up, the room is a thin strip; a plan floating in
    // it would cover the very thing the strip exists to show.
    if (this.h - this.reserved < 210) return;
    const { w, d } = this.state.dims;
    const R = this.minimapRect();
    const toMap = (p) => ({ x: R.x + p.x * R.scale, y: R.y + p.z * R.scale });

    g.save();
    g.fillStyle = 'rgba(10,12,17,0.82)';
    g.strokeStyle = 'rgba(255,255,255,0.16)';
    g.lineWidth = 1;
    roundRect(g, R.x - 8, R.y - 8, R.w + 16, R.h + 16, 8);
    g.fill();
    g.stroke();

    g.fillStyle = 'rgba(255,255,255,0.05)';
    g.fillRect(R.x, R.y, R.w, R.h);
    g.strokeStyle = 'rgba(255,255,255,0.28)';
    g.strokeRect(R.x, R.y, R.w, R.h);

    const accent = PRESETS_BY_ID[this.state.presetId].palette;
    const me = toMap(this.sourcePoint);
    const mic = toMap(this.micPoint);

    g.strokeStyle = hexA(accent, 0.5);
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(me.x, me.y);
    g.lineTo(mic.x, mic.y);
    g.stroke();

    // Which way you are looking.
    if (this.cam.mode === 'first') {
      const fovHalf = (this.cam.fov * Math.PI) / 360;
      const len = 26;
      g.fillStyle = 'rgba(255,217,138,0.20)';
      g.beginPath();
      g.moveTo(me.x, me.y);
      for (let a = -fovHalf; a <= fovHalf; a += fovHalf / 6) {
        const th = this.cam.yaw + a;
        g.lineTo(me.x + Math.sin(th) * len, me.y + Math.cos(th) * len);
      }
      g.closePath();
      g.fill();
    }

    g.fillStyle = '#ffd98a';
    g.beginPath();
    g.arc(me.x, me.y, 4.5, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = '#e9edf5';
    g.beginPath();
    g.arc(mic.x, mic.y, 3.5, 0, Math.PI * 2);
    g.fill();

    g.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.fillStyle = 'rgba(255,255,255,0.5)';
    // A long narrow room makes a long narrow map; keep the labels inside it.
    const label = (text, at, dy) => {
      g.fillText(text, clamp(at.x + 7, R.x, R.x + R.w - 20), clamp(at.y + dy, R.y + 10, R.y + R.h - 3));
    };
    label('you', me, -5);
    label('mic', mic, 11);
    g.fillStyle = 'rgba(255,255,255,0.35)';
    g.fillText(`${w.toFixed(1)} x ${d.toFixed(1)} m`, R.x, R.y + R.h + 16);
    g.restore();
  }

  hitMinimap(px, py) {
    const R = this.minimapRect();
    if (px < R.x - 8 || px > R.x + R.w + 8 || py < R.y - 8 || py > R.y + R.h + 8) return null;
    return {
      x: clamp((px - R.x) / R.scale, 0.15, this.state.dims.w - 0.15),
      z: clamp((py - R.y) / R.scale, 0.15, this.state.dims.d - 0.15),
    };
  }

  // ------------------------------------------------------------------ render

  render(dtMs) {
    if (!this.state) return;
    this.cam.bias = this.reserved / 2;
    const g = this.ctx;
    const { w: W, h: H } = this;
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#070910';
    g.fillRect(0, 0, W, H);

    this.walk(dtMs / 1000);
    if (this.cam.mode === 'orbit' && this.needsFit) this.fit(W, H);
    this.cam.update(W, H);

    this.rayClock += dtMs / 1000;
    for (const r of this.ripples) r.t += dtMs / 1000;
    this.ripples = this.ripples.filter((r) => r.t < 2.2);

    // One depth-sorted list, so the room occludes itself correctly whether you
    // are standing inside it or looking in from outside.
    const list = [];
    for (const face of this.faces()) this.drawFace(g, face, list);
    this.drawBeams(g, list);
    this.drawTreatment(g, list);
    this.drawFixtures(g, list);
    this.drawSeating(g, list);
    this.drawMic(g, list);
    this.drawPerformer(g, list);
    list.sort((a, b) => b.z - a.z || (a.sub || 0) - (b.sub || 0));
    for (const item of list) item.draw();

    this.drawRipples(g);
    if (this.showRays) this.drawRays(g);
    this.drawHud(g);
    this.drawMinimap(g);
  }

  drawSeating(g, list) {
    const preset = PRESETS_BY_ID[this.state.presetId];
    if (!preset.seating) return;
    const { w, d } = this.state.dims;
    const rows = clamp(Math.round((d * preset.seating.coverage) / 1.25), 3, 28);
    const cols = clamp(Math.round(w / 1.15), 4, 30);
    const z0 = d * (1 - preset.seating.coverage);
    const rgb = parse(MATERIALS[preset.seating.material].colour);
    for (let r = 0; r < rows; r++) {
      const z = z0 + ((r + 0.4) / rows) * (d - z0);
      for (let c = 0; c < cols; c++) {
        const x = ((c + 0.5) / cols) * w;
        const seat = this.cam.poly([
          { x: x - 0.22, y: 0.02, z: z - 0.2 }, { x: x + 0.22, y: 0.02, z: z - 0.2 },
          { x: x + 0.22, y: 0.42, z: z + 0.16 }, { x: x - 0.22, y: 0.42, z: z + 0.16 },
        ]);
        const back = this.cam.poly([
          { x: x - 0.22, y: 0.42, z: z + 0.16 }, { x: x + 0.22, y: 0.42, z: z + 0.16 },
          { x: x + 0.22, y: 0.86, z: z + 0.22 }, { x: x - 0.22, y: 0.86, z: z + 0.22 },
        ]);
        if (!seat) continue;
        const fog = this.fogAt(seat.depth);
        list.push({
          z: seat.depth,
          draw: () => {
            if (back) { g.fillStyle = shade(rgb, 0.95, fog); fillPoly(g, back); }
            g.fillStyle = shade(rgb, 0.68, fog);
            fillPoly(g, seat);
          },
        });
      }
    }
  }

  drawHud(g) {
    const { w, d, h } = this.state.dims;
    g.font = '12px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.fillStyle = 'rgba(255,255,255,0.72)';
    g.fillText(`${w.toFixed(1)} x ${d.toFixed(1)} x ${h.toFixed(1)} m`, 14, 22);
    g.fillStyle = 'rgba(255,255,255,0.42)';
    g.fillText(`${Math.round(w * d * h).toLocaleString()} m3`, 14, 40);

    if (this.cam.mode !== 'first') return;
    // A crosshair, and how far away the mic is right now.
    const m = this.cam.project(this.micPoint);
    const dist = Math.hypot(this.micPoint.x - this.cam.eye.x, this.micPoint.z - this.cam.eye.z,
                            this.micPoint.y - this.cam.eye.y);
    if (m) {
      g.strokeStyle = 'rgba(255,255,255,0.35)';
      g.lineWidth = 1;
      g.beginPath();
      g.arc(m.x, m.y, 20, 0, Math.PI * 2);
      g.stroke();
      g.fillStyle = 'rgba(255,255,255,0.7)';
      g.fillText(`${dist.toFixed(2)} m`, m.x + 26, m.y + 4);
    }
  }

  // ------------------------------------------------------------- interaction

  /** Walk, in whatever direction you are facing. */
  walk(dt) {
    if (this.cam.mode !== 'first' || this.keys.size === 0) return;
    let fwd = 0, side = 0;
    if (this.keys.has('w') || this.keys.has('arrowup')) fwd += 1;
    if (this.keys.has('s') || this.keys.has('arrowdown')) fwd -= 1;
    if (this.keys.has('a') || this.keys.has('arrowleft')) side -= 1;
    if (this.keys.has('d') || this.keys.has('arrowright')) side += 1;
    if (!fwd && !side) return;
    const step = WALK * dt;
    const s = Math.sin(this.cam.yaw), c = Math.cos(this.cam.yaw);
    this.state.source.x += (s * fwd + c * side) * step;
    this.state.source.z += (c * fwd - s * side) * step;
    this.onChange('source');
  }

  bind() {
    const canvas = this.canvas;
    const pos = (e) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    canvas.addEventListener('pointerdown', (e) => {
      if (!this.state) return;
      const { x, y } = pos(e);
      canvas.setPointerCapture(e.pointerId);

      const map = this.hitMinimap(x, y);
      if (map) {
        const dMe = Math.hypot(map.x - this.state.source.x, map.z - this.state.source.z);
        const dMic = Math.hypot(map.x - this.state.mic.x, map.z - this.state.mic.z);
        this.drag = { kind: dMic < dMe ? 'mic' : 'source', viaMap: true };
        this.applyMap(map);
        return;
      }

      const hit = this.hitTest(x, y);
      if (hit) this.drag = { kind: hit.id, grip: hit.grip, last: { x, y } };
      else this.drag = { kind: this.cam.mode === 'first' ? 'look' : 'orbit', last: { x, y } };
      e.preventDefault();
    });

    canvas.addEventListener('pointermove', (e) => {
      if (!this.state) return;
      const { x, y } = pos(e);
      if (!this.drag) {
        const hit = this.hitTest(x, y);
        this.hover = hit ? hit.id : null;
        canvas.style.cursor = hit ? 'grab' : this.hitMinimap(x, y) ? 'crosshair' : 'move';
        return;
      }
      canvas.style.cursor = 'grabbing';

      if (this.drag.viaMap) {
        const map = this.hitMinimap(x, y);
        if (map) this.applyMap(map);
      } else if (this.drag.kind === 'look') {
        this.cam.yaw += (x - this.drag.last.x) * 0.005;
        this.cam.pitch = clamp(this.cam.pitch - (y - this.drag.last.y) * 0.004, -1.2, 1.2);
        this.state.mic.aimAtSource = this.state.mic.aimAtSource;
      } else if (this.drag.kind === 'orbit') {
        this.cam.orbitYaw -= (x - this.drag.last.x) * 0.007;
        this.cam.orbitPitch = clamp(this.cam.orbitPitch + (y - this.drag.last.y) * 0.006, -0.15, 1.35);
      } else if (this.drag.kind === 'source' || this.drag.kind === 'mic') {
        const o = this.drag.kind === 'source' ? this.state.source : this.state.mic;
        // Standing in the room, your eye is at about the height of the capsule,
        // so a drag plane at that height is edge-on and never intersects. Slide
        // the stand along the floor instead, which is what you would do anyway.
        const p = this.cam.onPlane(x, y, this.cam.mode === 'first' ? 0 : o.height);
        if (p) { o.x = p.x; o.z = p.z; this.onChange(this.drag.kind); }
      } else if (this.drag.kind.startsWith('wall:')) {
        this.dragWall(this.drag.grip, x, y);
      }
      this.drag.last = { x, y };
      e.preventDefault();
    });

    const end = (e) => {
      if (this.drag) { this.drag = null; canvas.style.cursor = 'move'; this.onChange('end'); }
      if (e.pointerId !== undefined && canvas.hasPointerCapture?.(e.pointerId)) {
        canvas.releasePointerCapture(e.pointerId);
      }
    };
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);

    canvas.addEventListener('wheel', (e) => {
      if (this.cam.mode === 'first') {
        // Step forward and back through the room.
        const step = -Math.sign(e.deltaY) * 0.45;
        this.state.source.x += Math.sin(this.cam.yaw) * step;
        this.state.source.z += Math.cos(this.cam.yaw) * step;
        this.onChange('source');
      } else {
        this.cam.distance = clamp(this.cam.distance * (1 + Math.sign(e.deltaY) * 0.09), 2.5, 600);
      }
      e.preventDefault();
    }, { passive: false });

    const typing = (t) => t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName);
    window.addEventListener('keydown', (e) => {
      if (typing(e.target)) return;
      const k = e.key.toLowerCase();
      if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(k)) {
        this.keys.add(k);
        e.preventDefault();
      }
    });
    window.addEventListener('keyup', (e) => this.keys.delete(e.key.toLowerCase()));
    window.addEventListener('blur', () => this.keys.clear());
  }

  applyMap(map) {
    const o = this.drag.kind === 'source' ? this.state.source : this.state.mic;
    o.x = map.x;
    o.z = map.z;
    this.onChange(this.drag.kind);
  }

  hitTest(px, py) {
    const targets = [{ id: 'mic', p: this.micPoint }];
    if (this.cam.mode !== 'first') {
      targets.push({ id: 'source', p: this.sourcePoint });
      for (const g of this.wallGrips()) targets.push({ id: 'wall:' + g.id, p: g.p, grip: g });
    }
    let best = null;
    for (const t of targets) {
      const s = this.cam.project(t.p);
      if (!s) continue;
      const dist = Math.hypot(s.x - px, s.y - py);
      if (dist < HANDLE_R + 6 && (!best || dist < best.dist)) best = { ...t, dist };
    }
    return best;
  }

  wallGrips() {
    const { w, d } = this.state.dims;
    return [
      { id: 'z0', p: { x: w / 2, y: 0, z: 0 }, axis: 'z', side: 0 },
      { id: 'z1', p: { x: w / 2, y: 0, z: d }, axis: 'z', side: 1 },
      { id: 'x0', p: { x: 0, y: 0, z: d / 2 }, axis: 'x', side: 0 },
      { id: 'x1', p: { x: w, y: 0, z: d / 2 }, axis: 'x', side: 1 },
    ];
  }

  dragWall(grip, px, py) {
    const p = this.cam.onPlane(px, py, 0);
    if (!p) return;
    const st = this.state;
    const { w, d } = st.dims;
    const MIN = 1.6;
    if (grip.axis === 'x') {
      if (grip.side === 1) st.dims.w = Math.max(MIN, p.x);
      else {
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
}

// ------------------------------------------------------------------- helpers

function fillPoly(g, poly, strokeOnly = false) {
  g.beginPath();
  g.moveTo(poly[0].x, poly[0].y);
  for (let i = 1; i < poly.length; i++) g.lineTo(poly[i].x, poly[i].y);
  g.closePath();
  if (!strokeOnly) g.fill();
}

function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

/** Deterministic shuffle, so the same coverage always hangs the same panels. */
function shuffled(n, seed) {
  const a = [];
  for (let i = 0; i < n; i++) a.push(i);
  let s = seed * 2654435761 + 12345;
  for (let i = n - 1; i > 0; i--) {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    const j = s % (i + 1);
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
