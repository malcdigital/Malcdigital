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
