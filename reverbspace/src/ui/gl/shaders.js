// One shader for every solid surface in the room.
//
// Per-pixel lighting from the room's own fittings, normal mapping off the
// procedural textures, and an ambient occlusion term computed analytically
// from the shoebox itself -- which is the cheap trick that buys most of the
// realism, because corners going dark is what tells your eye a space is real.

export const VERT = `#version 300 es
precision highp float;

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec3 aTangent;
layout(location = 3) in vec2 aUv;

uniform mat4 uViewProj;

out vec3 vPos;
out vec3 vNormal;
out vec3 vTangent;
out vec2 vUv;

void main() {
  vPos = aPos;
  vNormal = aNormal;
  vTangent = aTangent;
  vUv = aUv;
  gl_Position = uViewProj * vec4(aPos, 1.0);
}
`;

export const FRAG = `#version 300 es
precision highp float;

#define MAX_LIGHTS 12

in vec3 vPos;
in vec3 vNormal;
in vec3 vTangent;
in vec2 vUv;

uniform sampler2D uAlbedo;
uniform sampler2D uNormalMap;
uniform vec2 uUvScale;
uniform vec3 uTint;
uniform float uRough;
uniform float uNormalStrength;
uniform vec3 uEmissive;
uniform float uAlpha;

uniform vec3 uEye;
uniform vec3 uRoom;
uniform float uAoRadius;

uniform int uLightCount;
uniform vec3 uLightPos[MAX_LIGHTS];
uniform vec3 uLightColor[MAX_LIGHTS];
uniform float uLightRange[MAX_LIGHTS];

uniform mat4 uLightViewProj;
uniform highp sampler2DShadow uShadowMap;
uniform vec3 uSunDir;
uniform vec3 uSunColor;

// Radiance leaving each of the room's six surfaces: floor, ceiling, -x, +x,
// -z, +z. Worked out on the CPU as that surface's albedo times the light
// actually landing on it.
uniform vec3 uBounce[6];

uniform vec3 uAmbientSky;
uniform vec3 uAmbientGround;
uniform vec3 uFogColor;
uniform float uFogDensity;
uniform float uExposure;

out vec4 fragColor;

/*
 * Ambient occlusion against the six planes of the room. Each axis darkens the
 * shading only in proportion to how much the surface faces across it, so a
 * floor is not darkened by being near the floor -- only by being near a wall.
 */
float roomAo(vec3 p, vec3 n) {
  vec3 dmin = min(p, uRoom - p);
  vec3 t = clamp(dmin / uAoRadius, 0.0, 1.0);
  t = t * t * (3.0 - 2.0 * t);
  vec3 w = 1.0 - abs(n);
  vec3 f = mix(vec3(1.0), t, w);
  return clamp(f.x * f.y * f.z, 0.0, 1.0) * 0.72 + 0.28;
}

/*
 * How much of the key light reaches this point. Percentage-closer filtered over
 * a 3x3 kernel, with the bias slackened on surfaces facing away from the light,
 * where the depth gradient across a texel is steepest and acne shows first.
 */
float sunVisibility(vec3 p, float ndl) {
  vec4 lp = uLightViewProj * vec4(p, 1.0);
  vec3 proj = (lp.xyz / lp.w) * 0.5 + 0.5;
  if (proj.z > 1.0 || any(lessThan(proj.xy, vec2(0.0))) || any(greaterThan(proj.xy, vec2(1.0)))) {
    return 1.0;
  }
  float bias = mix(0.0035, 0.0006, ndl);
  vec2 texel = 1.0 / vec2(textureSize(uShadowMap, 0));
  float sum = 0.0;
  for (int y = -1; y <= 1; y++) {
    for (int x = -1; x <= 1; x++) {
      sum += texture(uShadowMap, vec3(proj.xy + vec2(float(x), float(y)) * texel, proj.z - bias));
    }
  }
  return sum / 9.0;
}

/*
 * Indirect light from the room itself.
 *
 * Each wall is a rectangle of known radiance, so the light it delivers to a
 * point is that radiance times the fraction of the hemisphere it covers. For a
 * rectangle that fraction is exact:
 *
 *     omega = 4 asin( ab / sqrt((a^2+h^2)(b^2+h^2)) )
 *
 * with a, b its half-extents and h the distance to its plane -- which tends to
 * the full hemisphere as you approach the surface and falls away as you leave
 * it. Six of those is the whole of a shoebox's first bounce, and it is why a
 * timber floor throws warm light back up the walls.
 */
vec3 roomBounce(vec3 p, vec3 n) {
  vec3 dirs[6] = vec3[6](vec3(0.0, 1.0, 0.0), vec3(0.0, -1.0, 0.0),
                         vec3(1.0, 0.0, 0.0), vec3(-1.0, 0.0, 0.0),
                         vec3(0.0, 0.0, 1.0), vec3(0.0, 0.0, -1.0));
  float dist[6];
  dist[0] = p.y;            dist[1] = uRoom.y - p.y;
  dist[2] = p.x;            dist[3] = uRoom.x - p.x;
  dist[4] = p.z;            dist[5] = uRoom.z - p.z;
  vec2 halfExt[6];
  halfExt[0] = vec2(uRoom.x, uRoom.z) * 0.5;
  halfExt[1] = halfExt[0];
  halfExt[2] = vec2(uRoom.z, uRoom.y) * 0.5;
  halfExt[3] = halfExt[2];
  halfExt[4] = vec2(uRoom.x, uRoom.y) * 0.5;
  halfExt[5] = halfExt[4];

  vec3 sum = vec3(0.0);
  for (int i = 0; i < 6; i++) {
    float ndl = max(dot(n, dirs[i]), 0.0);
    if (ndl <= 0.001) continue;
    float h = max(dist[i], 0.04);
    vec2 e = halfExt[i];
    float t = (e.x * e.y) / sqrt((e.x * e.x + h * h) * (e.y * e.y + h * h));
    float frac = (2.0 / 3.14159265) * asin(clamp(t, 0.0, 1.0));
    sum += uBounce[i] * ndl * frac;
  }
  return sum;
}

vec3 tonemap(vec3 x) {
  // Filmic curve: keeps the lamps from clipping to flat white.
  const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
  return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

void main() {
  vec3 albedo = texture(uAlbedo, vUv * uUvScale).rgb * uTint;

  vec3 N = normalize(vNormal);
  if (uNormalStrength > 0.001) {
    vec3 T = normalize(vTangent - N * dot(N, vTangent));
    vec3 B = cross(N, T);
    vec3 nm = texture(uNormalMap, vUv * uUvScale).rgb * 2.0 - 1.0;
    nm.xy *= uNormalStrength;
    N = normalize(mat3(T, B, N) * normalize(nm));
  }

  vec3 V = normalize(uEye - vPos);
  float ao = roomAo(vPos, normalize(vNormal));

  // Key light from overhead, and the only one that casts. The lamps below are
  // many and small; shadowing each would cost a map apiece for little gain.
  vec3 sunL = -normalize(uSunDir);
  float sunNdl = max(dot(N, sunL), 0.0);
  float sun = sunNdl > 0.0 ? sunVisibility(vPos, sunNdl) : 1.0;

  // Hemisphere ambient: a room is lit from above even where no lamp reaches.
  // Damped in shadow, so a cast shadow reads as a shadow and not a grey patch.
  float up = N.y * 0.5 + 0.5;
  vec3 fill = mix(uAmbientGround, uAmbientSky, up) + roomBounce(vPos, N);
  vec3 lit = albedo * fill * ao * mix(0.72, 1.0, sun);

  float gloss = 1.0 - clamp(uRough, 0.0, 1.0);

  // Environment reflection. A varnished floor picks up the room at a grazing
  // angle, which is most of what separates a sealed board from flat paint.
  vec3 R = reflect(-V, N);
  vec3 env = mix(uAmbientGround, uAmbientSky, R.y * 0.5 + 0.5);
  float fresnel = pow(1.0 - max(dot(N, V), 0.0), 5.0);
  lit += env * (0.05 + 0.85 * fresnel) * gloss * ao * mix(0.6, 1.0, sun);

  float shine = mix(64.0, 6.0, clamp(uRough, 0.0, 1.0));
  // Rough surfaces get almost no highlight. Without this the term sums across
  // every lamp in range -- a cloud facing a row of ceiling fittings collects a
  // dozen warm highlights and washes out to beige whatever colour it is.
  float specK = mix(0.16, 0.004, clamp(uRough, 0.0, 1.0));

  for (int i = 0; i < MAX_LIGHTS; i++) {
    if (i >= uLightCount) break;
    vec3 toL = uLightPos[i] - vPos;
    float dist = length(toL);
    vec3 L = toL / max(dist, 0.001);
    float ndl = max(dot(N, L), 0.0);
    if (ndl <= 0.0) continue;
    // Inverse-square, softened near the source and faded out at its range.
    float r = uLightRange[i];
    float atten = 1.0 / (1.0 + (dist * dist) / (r * r * 0.16));
    atten *= clamp(1.0 - dist / r, 0.0, 1.0);
    vec3 H = normalize(L + V);
    // Scaled by ndl so a highlight cannot exceed the light actually landing.
    float spec = pow(max(dot(N, H), 0.0), shine) * specK * ndl;
    lit += uLightColor[i] * atten * (albedo * ndl + spec) * mix(0.55, 1.0, ao);
  }

  {
    vec3 H = normalize(sunL + V);
    float spec = pow(max(dot(N, H), 0.0), shine) * specK * sunNdl;
    lit += uSunColor * sun * (albedo * sunNdl + spec);
  }

  lit += uEmissive;

  float depth = length(uEye - vPos);
  float fog = 1.0 - exp(-depth * uFogDensity);
  lit = mix(lit, uFogColor, clamp(fog, 0.0, 0.92));

  fragColor = vec4(pow(tonemap(lit * uExposure), vec3(1.0 / 2.2)), uAlpha);
}
`;

/** Depth-only pass: position in, nothing out but the depth buffer. */
export const DEPTH_VERT = `#version 300 es
precision highp float;
layout(location = 0) in vec3 aPos;
uniform mat4 uViewProj;
void main() {
  gl_Position = uViewProj * vec4(aPos, 1.0);
}
`;

export const DEPTH_FRAG = `#version 300 es
precision highp float;
void main() {}
`;

/** Compile, link, and cache every uniform location up front. */
export function buildProgram(gl, vertSrc = VERT, fragSrc = FRAG) {
  const compile = (type, src) => {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      throw new Error(`${type === gl.VERTEX_SHADER ? 'vertex' : 'fragment'} shader: ${gl.getShaderInfoLog(sh)}`);
    }
    return sh;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, vertSrc));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fragSrc));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    throw new Error(`link: ${gl.getProgramInfoLog(prog)}`);
  }
  const uniforms = {};
  const count = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < count; i++) {
    const name = gl.getActiveUniform(prog, i).name.replace(/\[0\]$/, '');
    uniforms[name] = gl.getUniformLocation(prog, name);
  }
  return { prog, uniforms };
}
