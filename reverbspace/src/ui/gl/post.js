// Post-processing.
//
// The room is rendered into a float buffer rather than straight to screen, so
// three things become possible that per-pixel shading cannot do on its own:
// occlusion between objects (the shader only knows the six room planes, not
// that a mic stand is standing on the floor), light bleeding out of the lamps,
// and a grade applied to the finished frame rather than to each fragment.

const FULLSCREEN_VERT = `#version 300 es
precision highp float;
out vec2 vUv;
void main() {
  // One oversized triangle. No buffers, no attributes.
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  vUv = p;
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
`;

const SSAO_FRAG = `#version 300 es
precision highp float;

in vec2 vUv;
uniform sampler2D uDepth;
uniform sampler2D uNormal;
uniform mat4 uProj;
uniform mat4 uInvProj;
uniform mat3 uView3;
uniform vec2 uSize;
uniform float uRadius;
uniform float uStrength;
out vec4 fragColor;

/** View-space position from the depth buffer. */
vec3 viewPos(vec2 uv) {
  float z = texture(uDepth, uv).r * 2.0 - 1.0;
  vec4 clip = vec4(uv * 2.0 - 1.0, z, 1.0);
  vec4 v = uInvProj * clip;
  return v.xyz / v.w;
}

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

void main() {
  float depth = texture(uDepth, vUv).r;
  if (depth >= 0.9999) { fragColor = vec4(1.0); return; }

  vec3 p = viewPos(vUv);
  vec3 n = normalize(uView3 * (texture(uNormal, vUv).xyz * 2.0 - 1.0));

  // Rotation from a repeating 4x4 cell rather than per pixel. A different
  // angle at every pixel is whiter noise but nothing can resolve it; with
  // sixteen angles tiled, a blur over the same 4x4 averages the whole set and
  // the speckle disappears.
  vec2 cell = mod(gl_FragCoord.xy, 4.0);
  float ang = (cell.y * 4.0 + cell.x) * (6.2831853 / 16.0);

  // A frame around the surface normal. Sampling a hemisphere built on the view
  // axis instead puts half the samples inside the surface, and a flat wall
  // then occludes itself -- which is what the speckle was.
  vec3 up = abs(n.z) < 0.9 ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
  vec3 tang = normalize(cross(up, n));
  mat3 tbn = mat3(tang, cross(n, tang), n);
  // Lift the origin off the surface so depth precision cannot put it behind.
  vec3 origin = p + n * (0.015 + uRadius * 0.02);

  float occ = 0.0;
  const int COUNT = 12;
  for (int i = 0; i < COUNT; i++) {
    float fi = float(i);
    float a = fi * 2.3999632 + ang;
    float r = sqrt((fi + 0.5) / float(COUNT));
    vec3 dir = vec3(cos(a) * r, sin(a) * r, sqrt(max(0.0, 1.0 - r * r)));
    // Cluster toward the origin, where occlusion actually matters.
    float scale = mix(0.2, 1.0, fract(fi * 0.618034 + ang));
    vec3 sp = origin + (tbn * dir) * uRadius * scale;

    vec4 clip = uProj * vec4(sp, 1.0);
    vec2 suv = (clip.xy / clip.w) * 0.5 + 0.5;
    if (suv.x < 0.0 || suv.x > 1.0 || suv.y < 0.0 || suv.y > 1.0) continue;
    float sceneZ = viewPos(suv).z;
    // Only an occluder nearer than the sample counts, and only one close
    // enough to be in the same neighbourhood -- otherwise a far wall behind a
    // near object darkens everything in front of it.
    if (sceneZ >= sp.z + 0.02) {
      occ += smoothstep(0.0, 1.0, uRadius / max(abs(p.z - sceneZ), 1e-4));
    }
  }
  float ao = 1.0 - (occ / float(COUNT)) * uStrength;
  fragColor = vec4(clamp(ao, 0.0, 1.0));
}
`;

const BLUR_FRAG = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uTex;
uniform vec2 uStep;
out vec4 fragColor;
void main() {
  // Five taps, binomial weights.
  vec4 sum = texture(uTex, vUv) * 0.375;
  sum += (texture(uTex, vUv + uStep) + texture(uTex, vUv - uStep)) * 0.25;
  sum += (texture(uTex, vUv + uStep * 2.0) + texture(uTex, vUv - uStep * 2.0)) * 0.0625;
  fragColor = sum;
}
`;

const BRIGHT_FRAG = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uTex;
uniform float uThreshold;
out vec4 fragColor;
void main() {
  vec3 c = texture(uTex, vUv).rgb;
  float lum = dot(c, vec3(0.2126, 0.7152, 0.0722));
  // Soft knee, so a lamp edging over the threshold does not pop.
  float k = smoothstep(uThreshold, uThreshold * 2.0, lum);
  fragColor = vec4(c * k, 1.0);
}
`;

const COMPOSITE_FRAG = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uScene;
uniform sampler2D uAo;
uniform sampler2D uBloom;
uniform float uExposure;
uniform float uBloomAmount;
uniform float uVignette;
uniform float uGrain;
uniform float uSeed;
out vec4 fragColor;

vec3 tonemap(vec3 x) {
  const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
  return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

void main() {
  vec3 c = texture(uScene, vUv).rgb;
  // Occlusion applies to what the lamps did not reach, so pull it back where
  // the pixel is already bright rather than crushing lit surfaces.
  float ao = texture(uAo, vUv).r;
  float lum = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c *= mix(ao, 1.0, clamp(lum * 1.6, 0.0, 0.85));
  c += texture(uBloom, vUv).rgb * uBloomAmount;

  vec2 d = vUv - 0.5;
  c *= 1.0 - uVignette * dot(d, d) * 1.9;

  // Grain multiplied in before the curve, not added after it. A fixed offset
  // is a couple of percent of a lit surface and a fifth of a shadow, so it
  // swamps exactly the parts of the picture that should be quietest.
  c *= 1.0 + (hash12(vUv * 1024.0 + uSeed) - 0.5) * uGrain * 2.0;
  c = tonemap(c * uExposure);
  fragColor = vec4(pow(max(c, 0.0), vec3(1.0 / 2.2)), 1.0);
}
`;

function compile(gl, vertSrc, fragSrc) {
  const make = (type, src) => {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(sh));
    }
    return sh;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, make(gl.VERTEX_SHADER, vertSrc));
  gl.attachShader(prog, make(gl.FRAGMENT_SHADER, fragSrc));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  const uniforms = {};
  const n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) {
    const name = gl.getActiveUniform(prog, i).name.replace(/\[0\]$/, '');
    uniforms[name] = gl.getUniformLocation(prog, name);
  }
  return { prog, uniforms };
}

function makeTexture(gl, w, h, internal, format, type, filter) {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, internal, w, h, 0, format, type, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return tex;
}

export class PostChain {
  constructor(gl) {
    this.gl = gl;
    this.ok = !!gl.getExtension('EXT_color_buffer_float');
    if (!this.ok) return;
    this.ssao = compile(gl, FULLSCREEN_VERT, SSAO_FRAG);
    this.blur = compile(gl, FULLSCREEN_VERT, BLUR_FRAG);
    this.bright = compile(gl, FULLSCREEN_VERT, BRIGHT_FRAG);
    this.composite = compile(gl, FULLSCREEN_VERT, COMPOSITE_FRAG);
    this.empty = gl.createVertexArray();
    this.width = 0;
    this.height = 0;
  }

  /** (Re)allocate every target for a canvas of this size. */
  resize(w, h) {
    const gl = this.gl;
    if (!this.ok || (w === this.width && h === this.height)) return;
    this.dispose();
    this.width = w;
    this.height = h;
    const half = [Math.max(1, w >> 1), Math.max(1, h >> 1)];
    const quarter = [Math.max(1, w >> 2), Math.max(1, h >> 2)];

    const target = (tw, th, internal, format, type, filter, withDepth) => {
      const colour = makeTexture(gl, tw, th, internal, format, type, filter);
      const fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, colour, 0);
      let depth = null, normal = null;
      if (withDepth) {
        depth = makeTexture(gl, tw, th, gl.DEPTH_COMPONENT24, gl.DEPTH_COMPONENT, gl.UNSIGNED_INT, gl.NEAREST);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.TEXTURE_2D, depth, 0);
        normal = makeTexture(gl, tw, th, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, gl.NEAREST);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT1, gl.TEXTURE_2D, normal, 0);
        gl.drawBuffers([gl.COLOR_ATTACHMENT0, gl.COLOR_ATTACHMENT1]);
      }
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      return { fb, colour, depth, normal, w: tw, h: th };
    };

    this.scene = target(w, h, gl.RGBA16F, gl.RGBA, gl.HALF_FLOAT, gl.LINEAR, true);
    this.aoA = target(half[0], half[1], gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, gl.LINEAR, false);
    this.aoB = target(half[0], half[1], gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, gl.LINEAR, false);
    this.bloomA = target(quarter[0], quarter[1], gl.RGBA16F, gl.RGBA, gl.HALF_FLOAT, gl.LINEAR, false);
    this.bloomB = target(quarter[0], quarter[1], gl.RGBA16F, gl.RGBA, gl.HALF_FLOAT, gl.LINEAR, false);
  }

  dispose() {
    const gl = this.gl;
    for (const key of ['scene', 'aoA', 'aoB', 'bloomA', 'bloomB']) {
      const t = this[key];
      if (!t) continue;
      gl.deleteFramebuffer(t.fb);
      gl.deleteTexture(t.colour);
      if (t.depth) gl.deleteTexture(t.depth);
      if (t.normal) gl.deleteTexture(t.normal);
      this[key] = null;
    }
  }

  bindScene() {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.scene.fb);
    gl.viewport(0, 0, this.scene.w, this.scene.h);
  }

  draw(target, prog, setup) {
    const gl = this.gl;
    if (target) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fb);
      gl.viewport(0, 0, target.w, target.h);
    } else {
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, this.width, this.height);
    }
    gl.useProgram(prog.prog);
    setup(prog.uniforms);
    gl.bindVertexArray(this.empty);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  /** Everything after the room is drawn: occlusion, bleed, grade. */
  run(opts) {
    const gl = this.gl;
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);

    const bind = (unit, tex) => {
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, tex);
    };

    this.draw(this.aoA, this.ssao, (u) => {
      bind(0, this.scene.depth);
      bind(1, this.scene.normal);
      gl.uniform1i(u.uDepth, 0);
      gl.uniform1i(u.uNormal, 1);
      gl.uniformMatrix4fv(u.uProj, false, opts.proj);
      gl.uniformMatrix4fv(u.uInvProj, false, opts.invProj);
      gl.uniformMatrix3fv(u.uView3, false, opts.view3);
      gl.uniform2f(u.uSize, this.aoA.w, this.aoA.h);
      gl.uniform1f(u.uRadius, opts.aoRadius);
      gl.uniform1f(u.uStrength, opts.aoStrength);
    });
    // Two separable passes at increasing width: the second covers the 4x4
    // rotation cell, which is what actually removes the pattern.
    for (const width of [1, 2]) {
      for (const [from, to, step] of [
        [this.aoA, this.aoB, [width / this.aoA.w, 0]],
        [this.aoB, this.aoA, [0, width / this.aoA.h]],
      ]) {
        this.draw(to, this.blur, (u) => {
          bind(0, from.colour);
          gl.uniform1i(u.uTex, 0);
          gl.uniform2f(u.uStep, step[0], step[1]);
        });
      }
    }

    this.draw(this.bloomA, this.bright, (u) => {
      bind(0, this.scene.colour);
      gl.uniform1i(u.uTex, 0);
      gl.uniform1f(u.uThreshold, opts.bloomThreshold);
    });
    for (let pass = 0; pass < 2; pass++) {
      for (const [from, to, step] of [
        [this.bloomA, this.bloomB, [(1 + pass * 1.6) / this.bloomA.w, 0]],
        [this.bloomB, this.bloomA, [0, (1 + pass * 1.6) / this.bloomA.h]],
      ]) {
        this.draw(to, this.blur, (u) => {
          bind(0, from.colour);
          gl.uniform1i(u.uTex, 0);
          gl.uniform2f(u.uStep, step[0], step[1]);
        });
      }
    }

    this.draw(null, this.composite, (u) => {
      bind(0, this.scene.colour);
      bind(1, this.aoA.colour);
      bind(2, this.bloomA.colour);
      gl.uniform1i(u.uScene, 0);
      gl.uniform1i(u.uAo, 1);
      gl.uniform1i(u.uBloom, 2);
      gl.uniform1f(u.uExposure, opts.exposure);
      gl.uniform1f(u.uBloomAmount, opts.bloomAmount);
      gl.uniform1f(u.uVignette, opts.vignette);
      gl.uniform1f(u.uGrain, opts.grain);
      gl.uniform1f(u.uSeed, opts.seed);
    });

    gl.bindVertexArray(null);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
  }
}
