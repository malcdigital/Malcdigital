// Geometry accumulation. Positions carry their own UVs in metres, so a texture
// tiles at a real size regardless of how big the surface is -- a 68 m cathedral
// wall gets the same stone courses as a 7 m studio wall, not stretched ones.

export class MeshBuilder {
  constructor() {
    this.pos = [];
    this.nrm = [];
    this.tan = [];
    this.uv = [];
    this.idx = [];
  }

  get empty() { return this.idx.length === 0; }

  /**
   * A quad, wound a -> b -> c -> d. The tangent runs along a->b and the UVs are
   * the distance in metres along the tangent and bitangent.
   */
  quad(a, b, c, d, uvOffset = [0, 0]) {
    const e1 = sub(b, a), e2 = sub(d, a);
    const n = normalize(cross(e1, e2));
    const t = normalize(e1);
    const bt = cross(n, t);
    const base = this.pos.length / 3;
    for (const p of [a, b, c, d]) {
      const rel = sub(p, a);
      this.pos.push(p[0], p[1], p[2]);
      this.nrm.push(n[0], n[1], n[2]);
      this.tan.push(t[0], t[1], t[2]);
      this.uv.push(dot(rel, t) + uvOffset[0], dot(rel, bt) + uvOffset[1]);
    }
    this.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    return this;
  }

  /**
   * A triangle. Caps need this: feeding a quad two identical corners makes one
   * of its edges zero-length, and the normal comes out as garbage -- which is
   * how a mic capsule ends up a dark blob facing the wrong way.
   */
  tri(a, b, c) {
    const e1 = sub(b, a), e2 = sub(c, a);
    const n = normalize(cross(e1, e2));
    const t = normalize(e1);
    const bt = cross(n, t);
    const base = this.pos.length / 3;
    for (const p of [a, b, c]) {
      const rel = sub(p, a);
      this.pos.push(p[0], p[1], p[2]);
      this.nrm.push(n[0], n[1], n[2]);
      this.tan.push(t[0], t[1], t[2]);
      this.uv.push(dot(rel, t), dot(rel, bt));
    }
    this.idx.push(base, base + 1, base + 2);
    return this;
  }

  /** Axis-aligned box between two corners. `faces` selects which sides to emit. */
  box(min, max, faces = 'all') {
    const [x0, y0, z0] = min, [x1, y1, z1] = max;
    const want = (f) => faces === 'all' || faces.includes(f);
    if (want('y1')) this.quad([x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]);
    if (want('y0')) this.quad([x0, y0, z1], [x1, y0, z1], [x1, y0, z0], [x0, y0, z0]);
    if (want('z0')) this.quad([x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]);
    if (want('z1')) this.quad([x1, y0, z1], [x0, y0, z1], [x0, y1, z1], [x1, y1, z1]);
    if (want('x0')) this.quad([x0, y0, z1], [x0, y0, z0], [x0, y1, z0], [x0, y1, z1]);
    if (want('x1')) this.quad([x1, y0, z0], [x1, y0, z1], [x1, y1, z1], [x1, y1, z0]);
    return this;
  }

  /** A box rotated about the vertical axis, for anything hung at an angle. */
  boxRotY(centre, size, angle) {
    const [cx, cy, cz] = centre;
    const [sx, sy, sz] = size;
    const ca = Math.cos(angle), sa = Math.sin(angle);
    const corner = (ix, iz) => {
      const x = ix * sx / 2, z = iz * sz / 2;
      return [cx + x * ca - z * sa, cy, cz + x * sa + z * ca];
    };
    const p = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)];
    const top = p.map(([x, y, z]) => [x, y + sy / 2, z]);
    const bot = p.map(([x, y, z]) => [x, y - sy / 2, z]);
    this.quad(top[0], top[1], top[2], top[3]);
    this.quad(bot[3], bot[2], bot[1], bot[0]);
    for (let i = 0; i < 4; i++) {
      const j = (i + 1) % 4;
      this.quad(bot[i], bot[j], top[j], top[i]);
    }
    return this;
  }

  /** A closed cylinder from a to b: mic bodies, stand columns, chains. */
  tube(a, b, r, sides = 12, capEnds = true) {
    const ax = normalize(sub(b, a));
    const helper = Math.abs(ax[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0];
    const u = normalize(cross(ax, helper));
    const v = cross(ax, u);
    const ring = (p) => {
      const out = [];
      for (let i = 0; i < sides; i++) {
        const t = (i / sides) * Math.PI * 2;
        const c = Math.cos(t) * r, s = Math.sin(t) * r;
        out.push([p[0] + u[0] * c + v[0] * s, p[1] + u[1] * c + v[1] * s, p[2] + u[2] * c + v[2] * s]);
      }
      return out;
    };
    const A = ring(a), B = ring(b);
    for (let i = 0; i < sides; i++) {
      const j = (i + 1) % sides;
      this.quad(A[i], A[j], B[j], B[i]);
    }
    if (capEnds) {
      for (let i = 1; i < sides - 1; i++) {
        this.tri(B[0], B[i], B[i + 1]);
        this.tri(A[0], A[i + 1], A[i]);
      }
    }
    return this;
  }

  /**
   * A ring lying in a plane, built from tube segments. Coiled cable on a wall
   * hook -- the detail that says a room is worked in rather than rendered.
   */
  ring(centre, radius, thickness, axis = 'z', segments = 14) {
    const pt = (t) => {
      const a = (t / segments) * Math.PI * 2;
      const c = Math.cos(a) * radius, s2 = Math.sin(a) * radius;
      if (axis === 'z') return [centre[0] + c, centre[1] + s2, centre[2]];
      if (axis === 'x') return [centre[0], centre[1] + s2, centre[2] + c];
      return [centre[0] + c, centre[1], centre[2] + s2];
    };
    for (let i = 0; i < segments; i++) this.tube(pt(i), pt(i + 1), thickness, 5, false);
    return this;
  }

  /** One vertex with an explicit normal, for surfaces that must shade smoothly. */
  vert(p, n, t, uv) {
    this.pos.push(p[0], p[1], p[2]);
    this.nrm.push(n[0], n[1], n[2]);
    this.tan.push(t[0], t[1], t[2]);
    this.uv.push(uv[0], uv[1]);
    return this.pos.length / 3 - 1;
  }

  /**
   * A hanging curtain: fabric bowing away from the wall and back in a run of
   * pleats, floor to rail.
   *
   * Normals come from the fold's own slope rather than per-quad, because flat
   * shading turns a curtain into corrugated iron -- the soft gradient round
   * each fold is the whole look.
   */
  curtain(from, to, bottom, top, wallNormal, opts = {}) {
    const depth = opts.depth ?? 0.14;
    const period = opts.period ?? 0.34;
    const seed = opts.seed ?? 1;
    const run = Math.hypot(to[0] - from[0], to[2] - from[2]);
    if (run < 0.05) return this;
    const along = [(to[0] - from[0]) / run, 0, (to[2] - from[2]) / run];
    const n = normalize(wallNormal);
    // Whole number of folds, so the run starts and ends against the wall.
    const folds = Math.max(2, Math.round(run / period));
    const steps = folds * 8;
    const w = (Math.PI * 2 * folds) / run;

    const cols = [];
    let arc = 0;
    let prev = null;
    for (let i = 0; i <= steps; i++) {
      const u = (i / steps) * run;
      // Never negative, so the fabric never passes through the wall.
      const off = depth * (0.5 - 0.5 * Math.cos(w * u));
      const slope = depth * 0.5 * w * Math.sin(w * u);
      const base = [from[0] + along[0] * u, 0, from[2] + along[2] * u];
      const pos = (y) => [base[0] + n[0] * off, y, base[2] + n[2] * off];
      const tan = normalize([along[0] + n[0] * slope, 0, along[2] + n[2] * slope]);
      let nl = normalize(cross(tan, [0, 1, 0]));
      if (dot(nl, n) < 0) nl = [-nl[0], -nl[1], -nl[2]];
      if (prev) arc += Math.hypot(pos(0)[0] - prev[0], pos(0)[2] - prev[2]);
      prev = pos(0);
      // A little slack at the hem, so it does not read as a printed board.
      const hem = bottom - (0.5 + 0.5 * Math.sin(u * 3.1 + seed)) * 0.012;
      cols.push({ lo: pos(hem), hi: pos(top), n: nl, t: tan, arc });
    }

    for (let i = 0; i < cols.length - 1; i++) {
      const a = cols[i], b = cols[i + 1];
      const i0 = this.vert(a.lo, a.n, a.t, [a.arc, 0]);
      const i1 = this.vert(b.lo, b.n, b.t, [b.arc, 0]);
      const i2 = this.vert(b.hi, b.n, b.t, [b.arc, top - bottom]);
      const i3 = this.vert(a.hi, a.n, a.t, [a.arc, top - bottom]);
      this.idx.push(i0, i1, i2, i0, i2, i3);
    }
    return this;
  }

  /**
   * A truncated cone from a to b. Lamp shades are cones, not boxes, and the
   * taper is most of what makes a fixture read as a fixture.
   */
  frustum(a, b, rA, rB, sides = 18, capA = false, capB = false) {
    const ax = normalize(sub(b, a));
    const helper = Math.abs(ax[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0];
    const u = normalize(cross(ax, helper));
    const v = cross(ax, u);
    const ring = (p, r) => {
      const out = [];
      for (let i = 0; i < sides; i++) {
        const t = (i / sides) * Math.PI * 2;
        const c = Math.cos(t) * r, s2 = Math.sin(t) * r;
        out.push([p[0] + u[0] * c + v[0] * s2, p[1] + u[1] * c + v[1] * s2, p[2] + u[2] * c + v[2] * s2]);
      }
      return out;
    };
    const A = ring(a, rA), B = ring(b, rB);
    for (let i = 0; i < sides; i++) {
      const j = (i + 1) % sides;
      this.quad(A[i], A[j], B[j], B[i]);
    }
    if (capB) for (let i = 1; i < sides - 1; i++) this.tri(B[0], B[i], B[i + 1]);
    if (capA) for (let i = 1; i < sides - 1; i++) this.tri(A[0], A[i + 1], A[i]);
    return this;
  }

  /** A flat disc facing along `dir`, for a lamp's mouth or a bulb. */
  disc(centre, radius, dir, sides = 18) {
    const ax = normalize(dir);
    const helper = Math.abs(ax[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0];
    const u = normalize(cross(ax, helper));
    const v = cross(ax, u);
    const pts = [];
    for (let i = 0; i < sides; i++) {
      const t = (i / sides) * Math.PI * 2;
      const c = Math.cos(t) * radius, s2 = Math.sin(t) * radius;
      pts.push([centre[0] + u[0] * c + v[0] * s2, centre[1] + u[1] * c + v[1] * s2, centre[2] + u[2] * c + v[2] * s2]);
    }
    for (let i = 1; i < sides - 1; i++) this.tri(pts[0], pts[i], pts[i + 1]);
    return this;
  }

  /** A wedge tile, as acoustic foam is actually moulded. */
  wedge(centre, size, height, axis, sign) {
    const h = size / 2;
    const out = [0, 0, 0];
    out[axis] = sign;
    const corner = (a, b) => {
      const p = [centre[0], centre[1], centre[2]];
      const [ia, ib] = axis === 0 ? [1, 2] : axis === 1 ? [0, 2] : [0, 1];
      p[ia] += a * h;
      p[ib] += b * h;
      return p;
    };
    const apex = [centre[0] + out[0] * height, centre[1] + out[1] * height, centre[2] + out[2] * height];
    const c = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)];
    const order = sign > 0 ? [0, 1, 2, 3] : [3, 2, 1, 0];
    for (let i = 0; i < 4; i++) {
      this.tri(c[order[i]], c[order[(i + 1) % 4]], apex);
    }
    return this;
  }

  /** Upload to GPU buffers and return something drawable. */
  upload(gl) {
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const attrib = (loc, data, size) => {
      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
      return buf;
    };
    const buffers = [
      attrib(0, this.pos, 3),
      attrib(1, this.nrm, 3),
      attrib(2, this.tan, 3),
      attrib(3, this.uv, 2),
    ];
    const ibo = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
    const Index = this.pos.length / 3 > 65535 ? Uint32Array : Uint16Array;
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Index(this.idx), gl.STATIC_DRAW);
    gl.bindVertexArray(null);
    return {
      vao,
      count: this.idx.length,
      type: Index === Uint32Array ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT,
      dispose() {
        gl.deleteVertexArray(vao);
        for (const b of buffers) gl.deleteBuffer(b);
        gl.deleteBuffer(ibo);
      },
    };
  }
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const normalize = (v) => {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
};

/** Perspective with an off-centre principal point, for the phone sheet lift. */
export function perspectiveOffset(focal, w, h, biasPx, near = 0.05, far = 400) {
  const f = (2 * focal) / h;
  const m = new Float32Array(16);
  m[0] = f / (w / h);
  m[5] = f;
  m[9] = (-2 * biasPx) / h;
  m[10] = (far + near) / (near - far);
  m[11] = -1;
  m[14] = (2 * far * near) / (near - far);
  return m;
}

/** View matrix from an eye and the camera's own right/up/forward basis. */
export function viewMatrix(eye, r, u, f) {
  const m = new Float32Array(16);
  m[0] = r.x; m[4] = r.y; m[8] = r.z;
  m[1] = u.x; m[5] = u.y; m[9] = u.z;
  m[2] = -f.x; m[6] = -f.y; m[10] = -f.z;
  m[12] = -(r.x * eye.x + r.y * eye.y + r.z * eye.z);
  m[13] = -(u.x * eye.x + u.y * eye.y + u.z * eye.z);
  m[14] = f.x * eye.x + f.y * eye.y + f.z * eye.z;
  m[15] = 1;
  return m;
}

export function multiply(a, b) {
  const out = new Float32Array(16);
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      out[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1]
                     + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    }
  }
  return out;
}

/** Orthographic projection, for a directional light's shadow pass. */
export function orthographic(halfW, halfH, near, far) {
  const m = new Float32Array(16);
  m[0] = 1 / halfW;
  m[5] = 1 / halfH;
  m[10] = -2 / (far - near);
  m[14] = -(far + near) / (far - near);
  m[15] = 1;
  return m;
}

/** View matrix looking from `eye` at `target`. */
export function lookAt(eye, target, up = { x: 0, y: 1, z: 0 }) {
  const f = normalize([target.x - eye.x, target.y - eye.y, target.z - eye.z]);
  let upv = [up.x, up.y, up.z];
  if (Math.abs(dot(f, upv)) > 0.999) upv = [1, 0, 0];
  const r = normalize(cross(f, upv));
  const u = cross(r, f);
  return viewMatrix(eye, { x: r[0], y: r[1], z: r[2] },
                         { x: u[0], y: u[1], z: u[2] },
                         { x: f[0], y: f[1], z: f[2] });
}
