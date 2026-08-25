// The room, rendered in WebGL, seen from where you are standing in it.
//
// Two cameras over one renderer: first person, with your eyes at the
// performer's head and the mic in front of you, and an outside orbit view for
// placing things. The surfaces, the panels on the walls, the clouds overhead
// and the seating are all built from the numbers the acoustics model uses. A
// few things -- a door, spare stands, a stool -- are decoration, and the
// legend says so.
//
// Rays, the plan and the read-outs are drawn in 2D on a canvas over the top,
// where text is cheap and they can sit above the room rather than in it.

import { MATERIALS, TREATMENTS } from '../core/materials.js';
import { PRESETS_BY_ID } from '../core/presets.js';
import { MICS_BY_ID, polarGain } from '../core/mics.js';
import { reflectionPaths, SPEED_OF_SOUND } from '../core/acoustics.js';
import { buildProgram, DEPTH_VERT, DEPTH_FRAG } from './gl/shaders.js';
import {
  MeshBuilder, perspectiveOffset, viewMatrix, multiply, orthographic, lookAt,
} from './gl/mesh.js';
import { buildRoom, buildMic } from './gl/room.js';
import { woodTexture, stoneTexture, fabricTexture, plasterTexture, normalFrom } from './gl/textures.js';

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
    this.bias = 0;
  }

  update(w, h) {
    this.cx = w / 2;
    this.cy = h / 2 - this.bias;
    const fov = this.mode === 'first' ? this.fov : this.orbitFov;
    // Size the lens off the long edge: driving it from the width alone gives a
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
    this.w = w;
    this.h = h;
  }

  /** Matches the 2D projection below exactly, so overlays line up with the room. */
  viewProj() {
    return multiply(
      perspectiveOffset(this.focal, this.w, this.h, this.bias),
      viewMatrix(this.eye, this.r, this.u, this.f));
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

  /** Clip against the near plane, then project. Walls straddle the eye indoors. */
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

// ----------------------------------------------------------------- materials

/** Texture recipe for one of the model's materials, at a real-world tile size. */
function recipeFor(id) {
  const mat = MATERIALS[id];
  const base = mat.colour;
  switch (mat.pattern) {
    case 'planks':
      return { kind: 'wood', base, boards: 4, tile: id === 'woodFloor' ? 0.68 : 0.92,
               rough: 0.62, normalStrength: 1.0 };
    case 'blocks':
      return { kind: 'stone', base, rows: 6, tile: 3.2, rough: 0.9, normalStrength: 1.25 };
    case 'bricks':
      return { kind: 'stone', base, rows: 12, tile: 1.1, rough: 0.92, normalStrength: 1.3 };
    case 'tiles':
      return { kind: 'stone', base, rows: 3, tile: 3.1, rough: 0.35, normalStrength: 0.5 };
    default:
      return { kind: 'plaster', base, tile: 2.6, rough: 0.85, normalStrength: 0.5 };
  }
}

const HANDLE_R = 15;
const EYE_DROP = 0.10;
const WALK = 3.2;
const MAX_LIGHTS = 12;
const SHADOW_SIZE = 1536;
/** Where the key light comes from. Down and across, so shadows have a length. */
const SUN = { x: 0.34, y: -1, z: 0.22 };
/**
 * Weight on the first bounce. Held at one: further bounces do exist, and the
 * series sums to 1/(1-albedo), but leaning on that flattens a bright room --
 * a marble nave ends up lit evenly from every direction with no contrast left.
 */
const BOUNCE = 1.0;

export class RoomScene {
  constructor(canvas, hudCanvas) {
    this.canvas = canvas;
    this.hud = hudCanvas;
    this.ctx = hudCanvas.getContext('2d');
    this.cam = new Camera();
    this.state = null;
    this.response = null;
    this.paths = [];
    this.dpr = 1;
    this.w = 1;
    this.h = 1;

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

    this.textures = new Map();
    this.batches = null;
    this.signature = '';
    this.micSignature = '';
    this.failed = null;

    this.initGL();
    this.bind();
  }

  initGL() {
    const gl = this.canvas.getContext('webgl2', {
      antialias: true, alpha: false, depth: true, powerPreference: 'high-performance',
      // Lets the canvas be read back after the frame: screenshots, tests, and
      // anyone wanting to save a picture of their room.
      preserveDrawingBuffer: true,
    });
    if (!gl) {
      this.failed = 'This browser has no WebGL 2, which the room needs to draw itself.';
      return;
    }
    this.gl = gl;
    try {
      const built = buildProgram(gl);
      this.prog = built.prog;
      this.uni = built.uniforms;
    } catch (err) {
      this.failed = `Shader problem: ${err.message}`;
      return;
    }
    try {
      const depth = buildProgram(gl, DEPTH_VERT, DEPTH_FRAG);
      this.depthProg = depth.prog;
      this.depthUni = depth.uniforms;
    } catch (err) {
      this.failed = `Shadow shader problem: ${err.message}`;
      return;
    }
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
    gl.cullFace(gl.BACK);
    this.aniso = gl.getExtension('EXT_texture_filter_anisotropic');
    this.initShadow();
  }

  /** Depth target for the key light. Compared on sample, so the hardware filters. */
  initShadow() {
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.DEPTH_COMPONENT24, SHADOW_SIZE, SHADOW_SIZE, 0,
                  gl.DEPTH_COMPONENT, gl.UNSIGNED_INT, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_COMPARE_FUNC, gl.LEQUAL);
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.TEXTURE_2D, tex, 0);
    gl.drawBuffers([gl.NONE]);
    gl.readBuffer(gl.NONE);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
      this.failed = 'Could not set up a shadow buffer.';
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.shadowTex = tex;
    this.shadowFb = fb;
    this.shadowDirty = true;
  }

  /** Light's view-projection, sized to hold the whole room. */
  lightMatrix() {
    const { w, d, h } = this.state.dims;
    const centre = { x: w / 2, y: h / 2, z: d / 2 };
    const span = Math.hypot(w, d, h) * 0.5;
    const dir = norm(SUN);
    const eye = {
      x: centre.x - dir.x * span * 1.6,
      y: centre.y - dir.y * span * 1.6,
      z: centre.z - dir.z * span * 1.6,
    };
    return multiply(orthographic(span * 1.05, span * 1.05, 0.05, span * 3.4),
                    lookAt(eye, centre));
  }

  /**
   * The room and its fittings do not move, so the depth pass only needs
   * redrawing when the geometry changes -- which on a phone is most of the
   * cost saved.
   */
  renderShadow() {
    const gl = this.gl;
    this.lightVP = this.lightMatrix();
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.shadowFb);
    gl.viewport(0, 0, SHADOW_SIZE, SHADOW_SIZE);
    gl.clear(gl.DEPTH_BUFFER_BIT);
    gl.useProgram(this.depthProg);
    gl.uniformMatrix4fv(this.depthUni.uViewProj, false, this.lightVP);
    // The shell itself must not cast, or its own ceiling shadows the entire
    // room and nothing inside is lit at all. Only the things standing in the
    // room cast: panels, clouds, beams, stands, the mic.
    gl.cullFace(gl.FRONT);
    const SHELL = new Set(['walls', 'floor', 'ceiling', 'glow', 'glass']);
    for (const batch of [...(this.batches || []), ...(this.micBatches || [])]) {
      if (SHELL.has(batch.name)) continue;
      gl.bindVertexArray(batch.mesh.vao);
      gl.drawElements(gl.TRIANGLES, batch.mesh.count, batch.mesh.type, 0);
    }
    gl.cullFace(gl.BACK);
    gl.bindVertexArray(null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.shadowDirty = false;
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
    this.rebuildIfNeeded();
  }

  lookAtMic() {
    if (!this.state) return;
    const m = this.micPoint;
    const e = this.cam.eyeAt;
    const flat = Math.hypot(m.x - e.x, m.z - e.z);
    this.cam.yaw = Math.atan2(m.x - e.x, m.z - e.z);
    this.cam.pitch = clamp(Math.atan2(m.y - e.y, Math.max(flat, 0.1)), -0.9, 0.9);
  }

  frame() { this.framed = true; this.needsFit = true; }

  // ------------------------------------------------------------- gl plumbing

  texture(key, make) {
    if (this.textures.has(key)) return this.textures.get(key);
    const gl = this.gl;
    const canvas = make();
    /*
     * Albedo goes up as sRGB so the GPU linearises it on sample. Uploaded as
     * plain RGBA it is used as though already linear, and then gamma-encoded
     * again on the way out -- which lifts and desaturates every mid-tone. It
     * is why a dark green acoustic panel was coming out pale grey.
     * Normal maps are vectors, not colour, and must stay linear.
     */
    const upload = (src, srgb) => {
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, srgb ? gl.SRGB8_ALPHA8 : gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      if (this.aniso) {
        const max = gl.getParameter(this.aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT);
        gl.texParameterf(gl.TEXTURE_2D, this.aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(8, max));
      }
      return tex;
    };
    const pair = { albedo: upload(canvas, true), normal: upload(normalFrom(canvas), false) };
    this.textures.set(key, pair);
    return pair;
  }

  materialFor(id) {
    const r = recipeFor(id);
    const key = `${id}:${r.kind}`;
    const tex = this.texture(key, () => {
      if (r.kind === 'wood') return woodTexture({ base: r.base, boards: r.boards, seed: id.length * 13 });
      if (r.kind === 'stone') return stoneTexture({ base: r.base, rows: r.rows, seed: id.length * 7 });
      return plasterTexture({ base: r.base, seed: id.length * 5 });
    });
    return { ...tex, uvScale: 1 / r.tile, tint: [1, 1, 1], rough: r.rough, normalStrength: r.normalStrength };
  }

  /**
   * Radiance leaving each of the six surfaces, for the shader's bounce term.
   *
   * For each one, sample its area, add up the light every fitting actually
   * delivers there, and multiply by the surface's own albedo. A pendant over a
   * timber floor gives a warm floor; that warmth is then what fills the room.
   * Cheap to do here -- the lights and the room only change when the design
   * does, so this runs on a rebuild rather than per frame.
   */
  computeBounce() {
    const preset = PRESETS_BY_ID[this.state.presetId];
    const { w, d, h } = this.state.dims;
    const srgb = (hex) => {
      const n = parseInt(hex.replace('#', ''), 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
        const c = v / 255;
        return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
      });
    };
    const albedoFor = (id) => srgb(MATERIALS[id].colour);
    const floorA = albedoFor(preset.surfaces.floor);
    const ceilA = albedoFor(preset.surfaces.ceiling);
    const wallA = albedoFor(preset.surfaces.walls);

    const faces = [
      { n: [0, 1, 0], a: floorA, at: (u, v) => [u * w, 0, v * d] },
      { n: [0, -1, 0], a: ceilA, at: (u, v) => [u * w, h, v * d] },
      { n: [1, 0, 0], a: wallA, at: (u, v) => [0, v * h, u * d] },
      { n: [-1, 0, 0], a: wallA, at: (u, v) => [w, v * h, u * d] },
      { n: [0, 0, 1], a: wallA, at: (u, v) => [u * w, v * h, 0] },
      { n: [0, 0, -1], a: wallA, at: (u, v) => [u * w, v * h, d] },
    ];
    const sun = norm(SUN);
    const out = new Float32Array(18);

    faces.forEach((face, fi) => {
      let er = 0, eg = 0, eb = 0, samples = 0;
      for (let i = 0; i < 3; i++) {
        for (let j = 0; j < 3; j++) {
          const p = face.at((i + 0.5) / 3, (j + 0.5) / 3);
          samples++;
          for (const l of this.lights || []) {
            const dx = l.pos[0] - p[0], dy = l.pos[1] - p[1], dz = l.pos[2] - p[2];
            const dist = Math.hypot(dx, dy, dz) || 1e-4;
            const ndl = (dx * face.n[0] + dy * face.n[1] + dz * face.n[2]) / dist;
            if (ndl <= 0) continue;
            // Same falloff the shader uses, or the bounce disagrees with the
            // light it is supposed to be bouncing.
            const r = l.range;
            const atten = (1 / (1 + (dist * dist) / (r * r * 0.16)))
                        * clamp(1 - dist / r, 0, 1) * l.power * ndl;
            er += l.colour[0] * atten;
            eg += l.colour[1] * atten;
            eb += l.colour[2] * atten;
          }
          const sundl = Math.max(0, -(sun.x * face.n[0] + sun.y * face.n[1] + sun.z * face.n[2]));
          er += 0.30 * sundl; eg += 0.34 * sundl; eb += 0.43 * sundl;
        }
      }
      const k = BOUNCE / samples;
      out[fi * 3] = face.a[0] * er * k;
      out[fi * 3 + 1] = face.a[1] * eg * k;
      out[fi * 3 + 2] = face.a[2] * eb * k;
    });
    this.bounce = out;
  }

  /** Rebuild geometry only when something that shapes it actually changed. */
  rebuildIfNeeded() {
    if (!this.gl || this.failed) return;
    const s = this.state;
    const sig = [
      s.presetId, s.dims.w.toFixed(3), s.dims.d.toFixed(3), s.dims.h.toFixed(3),
      s.treatment.coverage.toFixed(3), s.treatment.type, s.source.height.toFixed(2),
    ].join('|');
    if (sig !== this.signature) {
      this.signature = sig;
      this.buildBatches();
      this.computeBounce();
      this.shadowDirty = true;
    }
    const msig = [s.mic.x.toFixed(3), s.mic.z.toFixed(3), s.mic.height.toFixed(3),
                  s.mic.azimuth.toFixed(3)].join('|');
    if (msig !== this.micSignature) {
      this.micSignature = msig;
      this.buildMicBatch();
      this.shadowDirty = true;
    }
  }

  buildBatches() {
    const gl = this.gl;
    if (this.batches) for (const b of this.batches) b.mesh.dispose();
    const preset = PRESETS_BY_ID[this.state.presetId];
    const { batches, lights } = buildRoom(this.state);
    this.lights = lights;

    const treat = TREATMENTS[this.state.treatment.type] || TREATMENTS.rockwool;
    const fabric = this.texture(`fabric:${this.state.treatment.type}`,
      () => fabricTexture({ base: treat.colour, seed: 5 }));
    const trimTex = this.texture('trim', () => woodTexture({ base: '#6a4526', boards: 2, seed: 41, grain: 0.4 }));
    const seatTex = preset.seating
      ? this.texture(`seat:${preset.seating.material}`,
          () => fabricTexture({ base: MATERIALS[preset.seating.material].colour, seed: 23 }))
      : null;
    const metalTex = this.texture('metal', () => plasterTexture({ base: '#585f6d', seed: 9, strength: 0.25 }));
    const glassTex = this.texture('glasspane', () => plasterTexture({ base: '#20242c', seed: 17, strength: 0.05 }));

    const list = [];
    // Named so a batch can be isolated when something looks wrong.
    const add = (name, mesh, material) => {
      if (mesh.empty) return;
      list.push({ name, mesh: mesh.upload(gl), material });
    };
    add('walls', batches.walls, this.materialFor(preset.surfaces.walls));
    add('floor', batches.floor, this.materialFor(preset.surfaces.floor));
    add('ceiling', batches.ceiling, this.materialFor(preset.surfaces.ceiling));
    add('trim', batches.trim, { ...trimTex, uvScale: 1 / 1.1, tint: [1, 1, 1], rough: 0.55, normalStrength: 0.8 });
    add('panels', batches.panels, { ...fabric, uvScale: 1 / 0.55, tint: [1, 1, 1], rough: 0.95, normalStrength: 0.9 });
    // Velvet: matte, so the shape of each fold does the work rather than a
    // highlight running down it.
    add('drape', batches.drape,
      { ...fabric, uvScale: 1 / 0.75, tint: [1, 1, 1], rough: 0.99, normalStrength: 0.35 });
    add('foam', batches.foam,
      { ...fabric, uvScale: 1 / 0.3, tint: [1, 1, 1], rough: 0.99, normalStrength: 0.5 });
    add('diffuser', batches.diffuser,
      { ...trimTex, uvScale: 1 / 0.5, tint: [1.15, 1.06, 0.92], rough: 0.5, normalStrength: 0.7 });
    // Brass. Painted dark, a shade is lit only from inside and reads as a
    // silhouette from across the room; a bright metal catches the other lamps.
    const brassTex = this.texture('brass', () => plasterTexture({ base: '#a8823f', seed: 33, strength: 0.16 }));
    add('shade', batches.shade,
      { ...brassTex, uvScale: 1 / 0.3, tint: [1.12, 1.02, 0.84], rough: 0.22, normalStrength: 0.2 });
    // Lit fabric: glowing, but not a light source in its own right.
    add('shadeSoft', batches.shadeSoft,
      { ...fabric, uvScale: 1 / 0.3, tint: [1.25, 1.15, 0.95], rough: 0.98, normalStrength: 0.4,
        emissive: [0.30, 0.235, 0.145] });
    add('door', batches.door,
      { ...trimTex, uvScale: 1 / 0.9, tint: [1.1, 1.0, 0.88], rough: 0.45, normalStrength: 0.7 });
    add('rug', batches.rug,
      { ...fabric, uvScale: 1 / 1.1, tint: [0.7, 0.55, 0.46], rough: 0.99, normalStrength: 0.6 });
    add('panelsAlt', batches.panelsAlt,
      { ...fabric, uvScale: 1 / 0.5, tint: [0.66, 0.55, 0.5], rough: 0.95, normalStrength: 0.9 });
    add('metal', batches.metal, { ...metalTex, uvScale: 1 / 0.4, tint: [1, 1, 1], rough: 0.3, normalStrength: 0.3 });
    add('decor', batches.decor, { ...metalTex, uvScale: 1 / 0.5, tint: [0.85, 0.8, 0.76], rough: 0.45, normalStrength: 0.3 });
    if (seatTex) add('seats', batches.seats, { ...seatTex, uvScale: 1 / 0.6, tint: [1, 1, 1], rough: 0.95, normalStrength: 0.7 });
    // Barely there: a pane is mostly the room reflected in it, which the
    // environment term already supplies.
    add('glass', batches.glass, { ...glassTex, uvScale: 1 / 2, tint: [1, 1, 1], rough: 0.03,
                                  normalStrength: 0, alpha: 0.22 });
    add('screens', batches.screens, { ...glassTex, uvScale: 1 / 0.4, tint: [1, 1, 1], rough: 0.1,
                                      normalStrength: 0, emissive: [0.5, 0.66, 1.05] });
    add('booth', batches.booth, { ...trimTex, uvScale: 1 / 1.4, tint: [0.62, 0.6, 0.6], rough: 0.9,
                                  normalStrength: 0.4 });
    add('glow', batches.glow, { ...metalTex, uvScale: 1 / 0.4, tint: [1, 1, 1], rough: 0.2, normalStrength: 0,
                        emissive: [1.5, 1.15, 0.72] });
    this.batches = list;
  }

  buildMicBatch() {
    const gl = this.gl;
    if (this.micBatches) for (const b of this.micBatches) b.mesh.dispose();
    const { body, metal, cable } = buildMic(this.state);
    const metalTex = this.texture('metal', () => plasterTexture({ base: '#585f6d', seed: 9, strength: 0.25 }));
    const bodyTex = this.texture('micbody', () => plasterTexture({ base: '#9aa3b4', seed: 29, strength: 0.14 }));
    this.micBatches = [
      { mesh: metal.upload(gl), material: { ...metalTex, uvScale: 1 / 0.3, tint: [1, 1, 1], rough: 0.28, normalStrength: 0.3 } },
      { mesh: body.upload(gl), material: { ...bodyTex, uvScale: 1 / 0.2, tint: [1, 1, 1], rough: 0.18, normalStrength: 0.25 } },
      { name: 'cable', mesh: cable.upload(gl),
        material: { ...metalTex, uvScale: 1 / 0.2, tint: [0.2, 0.2, 0.22], rough: 0.75, normalStrength: 0.2 } },
    ];
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    for (const c of [this.canvas, this.hud]) {
      c.width = Math.max(1, Math.round(rect.width * this.dpr));
      c.height = Math.max(1, Math.round(rect.height * this.dpr));
    }
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

  // ------------------------------------------------------------------ render

  render(dtMs) {
    if (!this.state) return;
    this.cam.bias = this.reserved / 2;
    this.walk(dtMs / 1000);
    if (this.cam.mode === 'orbit' && this.needsFit) this.fit(this.w, this.h);
    this.cam.update(this.w, this.h);

    this.rayClock += dtMs / 1000;
    for (const r of this.ripples) r.t += dtMs / 1000;
    this.ripples = this.ripples.filter((r) => r.t < 2.2);

    if (this.failed) this.drawFailure();
    else this.drawGL();
    this.drawHudLayer();
  }

  drawFailure() {
    const g = this.ctx;
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.clearRect(0, 0, this.w, this.h);
    g.fillStyle = '#0a0c11';
    g.fillRect(0, 0, this.w, this.h);
    g.fillStyle = '#e7ebf3';
    g.font = '14px system-ui, sans-serif';
    g.fillText(this.failed, 20, 40);
  }

  drawGL() {
    const gl = this.gl;
    const { w, d, h } = this.state.dims;
    if (this.shadowDirty) this.renderShadow();
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    const dark = this.state.presetId === 'cathedral' ? [0.026, 0.028, 0.038] : [0.02, 0.022, 0.03];
    gl.clearColor(dark[0], dark[1], dark[2], 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    gl.useProgram(this.prog);
    const u = this.uni;
    gl.uniformMatrix4fv(u.uViewProj, false, this.cam.viewProj());
    gl.uniform3f(u.uEye, this.cam.eye.x, this.cam.eye.y, this.cam.eye.z);
    gl.uniform3f(u.uRoom, w, h, d);
    gl.uniform1f(u.uAoRadius, clamp(Math.min(w, d, h) * 0.22, 0.25, 2.4));

    // The room's own fittings light it. Keep the nearest handful.
    const lights = (this.lights || [])
      .map((l) => ({ ...l, dist: Math.hypot(l.pos[0] - this.cam.eye.x, l.pos[1] - this.cam.eye.y, l.pos[2] - this.cam.eye.z) }))
      .sort((a, b) => a.dist - b.dist)
      .slice(0, MAX_LIGHTS);
    const pos = new Float32Array(MAX_LIGHTS * 3);
    const col = new Float32Array(MAX_LIGHTS * 3);
    const rng = new Float32Array(MAX_LIGHTS);
    lights.forEach((l, i) => {
      pos.set(l.pos, i * 3);
      col.set([l.colour[0] * l.power, l.colour[1] * l.power, l.colour[2] * l.power], i * 3);
      rng[i] = l.range;
    });
    if (this.bounce) gl.uniform3fv(u.uBounce, this.bounce);
    gl.uniform1i(u.uLightCount, lights.length);
    gl.uniform3fv(u.uLightPos, pos);
    gl.uniform3fv(u.uLightColor, col);
    gl.uniform1fv(u.uLightRange, rng);

    const big = Math.max(w, d, h);
    // Neutral ambient: leaning it warm as well as the lamps pushed every
    // surface toward the same orange and the panels lost their own colour.
    // Cool shadow, warm light. The lamps are tungsten; what fills in behind
    // them should not be, or the whole room sits at one temperature.
    gl.uniform3f(u.uAmbientSky, 0.058, 0.066, 0.086);
    gl.uniform3f(u.uAmbientGround, 0.030, 0.034, 0.044);
    gl.uniform3f(u.uFogColor, dark[0] * 6, dark[1] * 6, dark[2] * 7);
    // Air does not visibly haze a 7 metre room. Keep it near nothing indoors
    // and let it build only across the length of something like a nave.
    gl.uniform1f(u.uFogDensity, 0.005 + clamp((big - 18) / 2600, 0, 0.019));
    gl.uniform1f(u.uExposure, 1.05);

    const sun = norm(SUN);
    gl.uniform3f(u.uSunDir, sun.x, sun.y, sun.z);
    gl.uniform3f(u.uSunColor, 0.30, 0.34, 0.43);
    gl.uniformMatrix4fv(u.uLightViewProj, false, this.lightVP || this.lightMatrix());

    gl.uniform1i(u.uAlbedo, 0);
    gl.uniform1i(u.uNormalMap, 1);
    gl.uniform1i(u.uShadowMap, 2);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, this.shadowTex);

    const all = [...(this.batches || []), ...(this.micBatches || [])];
    const drawList = this.only ? all.filter((b) => b.name === this.only) : all;
    // Glass goes last and blended, so the control room shows through it.
    const opaque = drawList.filter((b) => (b.material.alpha ?? 1) >= 1);
    const clear = drawList.filter((b) => (b.material.alpha ?? 1) < 1);
    for (const batch of opaque.concat(clear)) {
      const alpha = batch.material.alpha ?? 1;
      if (alpha < 1) {
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.depthMask(false);
      }
      gl.uniform1f(u.uAlpha, alpha);
      const m = batch.material;
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, m.albedo);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, m.normal);
      gl.uniform2f(u.uUvScale, m.uvScale, m.uvScale);
      gl.uniform3fv(u.uTint, m.tint || [1, 1, 1]);
      gl.uniform1f(u.uRough, m.rough ?? 0.7);
      gl.uniform1f(u.uNormalStrength, m.normalStrength ?? 1);
      gl.uniform3fv(u.uEmissive, m.emissive || [0, 0, 0]);
      gl.bindVertexArray(batch.mesh.vao);
      gl.drawElements(gl.TRIANGLES, batch.mesh.count, batch.mesh.type, 0);
      if (alpha < 1) {
        gl.depthMask(true);
        gl.disable(gl.BLEND);
      }
    }
    gl.bindVertexArray(null);
  }

  // --------------------------------------------------------------- 2D layer

  drawHudLayer() {
    const g = this.ctx;
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.clearRect(0, 0, this.w, this.h);
    this.drawLampGlow(g);
    this.drawMicLobe(g);
    this.drawRipples(g);
    if (this.showRays) this.drawRays(g);
    this.drawPerformerMark(g);
    this.drawHud(g);
    this.drawMinimap(g);
  }

  /** Bloom around the lamps, cheaper here than a post-process pass. */
  drawLampGlow(g) {
    for (const l of this.lights || []) {
      const p = this.cam.project({ x: l.pos[0], y: l.pos[1], z: l.pos[2] });
      if (!p) continue;
      const r = clamp((this.cam.focal / p.z) * 0.34, 12, 190);
      const glow = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, r);
      glow.addColorStop(0, 'rgba(255,214,152,0.34)');
      glow.addColorStop(0.45, 'rgba(255,198,126,0.11)');
      glow.addColorStop(1, 'rgba(255,190,120,0)');
      g.fillStyle = glow;
      g.beginPath();
      g.arc(p.x, p.y, r, 0, Math.PI * 2);
      g.fill();
    }
  }

  drawMicLobe(g) {
    const mic = MICS_BY_ID[this.state.mic.id];
    if (!mic) return;
    const m = this.micPoint;
    const az = this.state.mic.azimuth;
    const reach = clamp(Math.min(this.state.dims.w, this.state.dims.d) * 0.16, 0.35, 2.4);
    const spread = ((mic.spread || 0) * Math.PI) / 360;
    const accent = PRESETS_BY_ID[this.state.presetId].palette;
    for (const side of mic.spread ? [-spread, spread] : [0]) {
      const ring = [];
      for (let i = 0; i < 72; i++) {
        const th = (i / 72) * Math.PI * 2;
        const r = Math.abs(polarGain(mic, th)) * reach;
        const world = az + side + th;
        ring.push({ x: m.x + Math.sin(world) * r, y: m.y, z: m.z + Math.cos(world) * r });
      }
      const poly = this.cam.poly(ring);
      if (!poly) continue;
      // Faint fill: at close range the lobe covers most of the view, and a
      // heavy wash flattens the whole room.
      g.fillStyle = hexA(accent, 0.055);
      fillPoly(g, poly);
      g.strokeStyle = hexA(accent, 0.42);
      g.lineWidth = 1.4;
      g.stroke();
    }
    const active = this.hover === 'mic' || this.drag?.kind === 'mic';
    if (active) {
      const p = this.cam.project(m);
      if (p) {
        g.strokeStyle = '#fff';
        g.lineWidth = 1.6;
        g.beginPath();
        g.arc(p.x, p.y, HANDLE_R + 6, 0, Math.PI * 2);
        g.stroke();
      }
    }
  }

  drawPerformerMark(g) {
    if (this.cam.mode === 'first') return;
    const s = this.sourcePoint;
    const p = this.cam.project(s);
    if (!p) return;
    const r = clamp(this.cam.focal / p.z * 0.05, 7, 26);
    const glow = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3);
    glow.addColorStop(0, 'rgba(255,217,138,0.6)');
    glow.addColorStop(1, 'rgba(255,217,138,0)');
    g.fillStyle = glow;
    g.beginPath();
    g.arc(p.x, p.y, r * 3, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = '#ffd98a';
    g.beginPath();
    g.arc(p.x, p.y - r * 0.5, r * 0.45, 0, Math.PI * 2);
    g.fill();
    g.beginPath();
    g.moveTo(p.x - r * 0.6, p.y + r * 1.15);
    g.quadraticCurveTo(p.x, p.y - r * 0.2, p.x + r * 0.6, p.y + r * 1.15);
    g.closePath();
    g.fill();
    if (this.hover === 'source' || this.drag?.kind === 'source') {
      g.strokeStyle = '#fff';
      g.lineWidth = 1.5;
      g.beginPath();
      g.arc(p.x, p.y, r * 1.9, 0, Math.PI * 2);
      g.stroke();
    }
  }

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
    const alpha = clamp(0.08 + strength * 0.4, 0.05, 0.5);
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
      const alpha = clamp(0.4 * (1 - r.t / 2.2), 0, 0.4);
      const ring = [];
      for (let a = 0; a < Math.PI * 2; a += Math.PI / 48) {
        ring.push({ x: r.at.x + Math.cos(a) * radius, y: 0.03, z: r.at.z + Math.sin(a) * radius });
      }
      const poly = this.cam.poly(ring);
      if (!poly) continue;
      g.strokeStyle = `rgba(255,255,255,${alpha})`;
      g.lineWidth = 1.5;
      fillPoly(g, poly, true);
      g.stroke();
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
    const m = this.cam.project(this.micPoint);
    const dist = Math.hypot(this.micPoint.x - this.cam.eye.x, this.micPoint.z - this.cam.eye.z,
                            this.micPoint.y - this.cam.eye.y);
    if (m) {
      g.strokeStyle = 'rgba(255,255,255,0.32)';
      g.lineWidth = 1;
      g.beginPath();
      g.arc(m.x, m.y, 22, 0, Math.PI * 2);
      g.stroke();
      g.fillStyle = 'rgba(255,255,255,0.72)';
      g.fillText(`${dist.toFixed(2)} m`, m.x + 28, m.y + 4);
    }
  }

  minimapRect() {
    const { w, d } = this.state.dims;
    const maxW = clamp(this.w * 0.3, 84, 176);
    const maxH = clamp(this.h * 0.24, 68, 148);
    const scale = Math.min(maxW / w, maxH / d);
    const bottom = this.h - this.reserved - 34;
    return { x: 14, y: bottom - d * scale, w: w * scale, h: d * scale, scale };
  }

  drawMinimap(g) {
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
    g.beginPath();
    g.moveTo(me.x, me.y);
    g.lineTo(mic.x, mic.y);
    g.stroke();

    if (this.cam.mode === 'first') {
      const fovHalf = (this.cam.fov * Math.PI) / 360;
      const len = 26;
      g.fillStyle = 'rgba(255,217,138,0.2)';
      g.beginPath();
      g.moveTo(me.x, me.y);
      for (let a = -fovHalf; a <= fovHalf; a += fovHalf / 6) {
        g.lineTo(me.x + Math.sin(this.cam.yaw + a) * len, me.y + Math.cos(this.cam.yaw + a) * len);
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
    g.fillText('you', me.x + 7, me.y + 3);
    g.fillText('mic', mic.x + 6, mic.y + 3);
    g.fillStyle = 'rgba(255,255,255,0.35)';
    g.fillText(`${w.toFixed(1)} x ${d.toFixed(1)} m`, R.x, R.y + R.h + 16);
    g.restore();
  }

  hitMinimap(px, py) {
    if (this.h - this.reserved < 210) return null;
    const R = this.minimapRect();
    if (px < R.x - 8 || px > R.x + R.w + 8 || py < R.y - 8 || py > R.y + R.h + 8) return null;
    return {
      x: clamp((px - R.x) / R.scale, 0.15, this.state.dims.w - 0.15),
      z: clamp((py - R.y) / R.scale, 0.15, this.state.dims.d - 0.15),
    };
  }

  // ------------------------------------------------------------- interaction

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
    const canvas = this.hud;
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
      } else if (this.drag.kind === 'orbit') {
        this.cam.orbitYaw -= (x - this.drag.last.x) * 0.007;
        this.cam.orbitPitch = clamp(this.cam.orbitPitch + (y - this.drag.last.y) * 0.006, -0.15, 1.35);
      } else if (this.drag.kind === 'source' || this.drag.kind === 'mic') {
        const o = this.drag.kind === 'source' ? this.state.source : this.state.mic;
        // Indoors your eye sits at about capsule height, so a plane at that
        // height is edge-on. Slide the stand along the floor instead.
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

function hexA(hex, a) {
  const s = hex.replace('#', '');
  const n = parseInt(s.length === 3 ? s.split('').map((c) => c + c).join('') : s, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
