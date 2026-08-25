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
uniform float uMetal;
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
// Aim and (cos outer, cos inner) for shaded fittings. A pendant with an
// opaque shade throws down, not up, and the dark top of the wall is the
// evidence. Omnidirectional sources pass a cone that always passes.
uniform vec3 uLightDir[MAX_LIGHTS];
uniform vec2 uLightCone[MAX_LIGHTS];

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
uniform float uTonemap;

layout(location = 0) out vec4 fragColor;
layout(location = 1) out vec4 fragNormal;

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

/*
 * The same six radiances, but along a mirror direction rather than over a
 * hemisphere. A chrome stand has no diffuse at all: everything you see on it
 * is the room, so it needs the room and not a two-colour sky, or it renders
 * as a black rod. Weighted by R squared, which sums to one over any direction.
 */
vec3 roomEnv(vec3 R) {
  vec3 w = R * R;
  vec3 neg = step(R, vec3(0.0));
  return w.y * mix(uBounce[1], uBounce[0], neg.y)
       + w.x * mix(uBounce[3], uBounce[2], neg.x)
       + w.z * mix(uBounce[5], uBounce[4], neg.z);
}

vec3 tonemap(vec3 x) {
  // Filmic curve: keeps the lamps from clipping to flat white.
  const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
  return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

/*
 * Cook-Torrance, in place of the Blinn-Phong lobe this used to carry.
 *
 * The exponent-and-a-constant version could be tuned to the right brightness
 * but never to the right shape: a real highlight has a tight core and a long
 * grazing tail, and the tail is what says "sealed board" rather than "paint".
 * Diffuse stays un-normalised so the exposure the room was balanced at still
 * holds, and the specular lobe carries a PI to sit in the same units.
 */
const float PI = 3.14159265359;

float distributionGGX(float ndh, float a) {
  float a2 = a * a;
  float d = ndh * ndh * (a2 - 1.0) + 1.0;
  return a2 / max(PI * d * d, 1e-7);
}

/** Height-correlated Smith, carrying the BRDF's own 1/(4 ndl ndv). */
float visibilitySmith(float ndv, float ndl, float a) {
  float a2 = a * a;
  float v = ndl * sqrt(ndv * ndv * (1.0 - a2) + a2);
  float l = ndv * sqrt(ndl * ndl * (1.0 - a2) + a2);
  return 0.5 / max(v + l, 1e-5);
}

vec3 fresnelSchlick(vec3 f0, float u) {
  return f0 + (1.0 - f0) * pow(clamp(1.0 - u, 0.0, 1.0), 5.0);
}

/** Fresnel for a whole environment rather than one direction. */
vec3 fresnelRough(vec3 f0, float ndv, float rough) {
  vec3 t = max(vec3(1.0 - rough), f0);
  return f0 + (t - f0) * pow(clamp(1.0 - ndv, 0.0, 1.0), 5.0);
}

/** One light's specular contribution, clamped off the firefly. */
vec3 specularLobe(vec3 N, vec3 V, vec3 L, vec3 f0, float a, float ndl, float ndv) {
  vec3 H = normalize(L + V);
  float ndh = max(dot(N, H), 0.0);
  float vdh = max(dot(V, H), 0.0);
  vec3 F = fresnelSchlick(f0, vdh);
  return min(F * (distributionGGX(ndh, a) * visibilitySmith(ndv, ndl, a) * PI), vec3(24.0));
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

  // Metals have no diffuse and tint their own reflection; everything else
  // reflects 4% white and keeps its colour in the diffuse term.
  float rough = clamp(uRough, 0.06, 1.0);
  float a = rough * rough;
  vec3 f0 = mix(vec3(0.04), albedo, uMetal);
  vec3 diffuse = albedo * (1.0 - uMetal);
  float ndv = max(dot(N, V), 1e-4);

  // Key light from overhead, and the only one that casts. The lamps below are
  // many and small; shadowing each would cost a map apiece for little gain.
  vec3 sunL = -normalize(uSunDir);
  float sunNdl = max(dot(N, sunL), 0.0);
  float sun = sunNdl > 0.0 ? sunVisibility(vPos, sunNdl) : 1.0;

  // Hemisphere ambient: a room is lit from above even where no lamp reaches.
  // Damped in shadow, so a cast shadow reads as a shadow and not a grey patch.
  float up = N.y * 0.5 + 0.5;
  vec3 fill = mix(uAmbientGround, uAmbientSky, up) + roomBounce(vPos, N);
  vec3 lit = diffuse * fill * ao * mix(0.72, 1.0, sun);

  // Environment reflection. A varnished floor picks up the room at a grazing
  // angle, which is most of what separates a sealed board from flat paint.
  // Rough surfaces fall off fast: they scatter the reflection rather than
  // returning it, and a wall that mirrors as hard as a floor looks wet.
  vec3 R = reflect(-V, N);
  vec3 env = mix(uAmbientGround, uAmbientSky, R.y * 0.5 + 0.5) + roomEnv(R);
  lit += env * fresnelRough(f0, ndv, rough) * pow(1.0 - rough, 1.3) * 1.7
         * ao * mix(0.6, 1.0, sun);

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
    atten *= smoothstep(uLightCone[i].x, uLightCone[i].y, dot(-L, uLightDir[i]));
    if (atten <= 0.0) continue;
    vec3 spec = specularLobe(N, V, L, f0, a, ndl, ndv);
    lit += uLightColor[i] * atten * ndl * (diffuse + spec) * mix(0.55, 1.0, ao);
  }

  if (sunNdl > 0.0) {
    vec3 spec = specularLobe(N, V, sunL, f0, a, sunNdl, ndv);
    lit += uSunColor * sun * sunNdl * (diffuse + spec);
  }

  lit += uEmissive;

  float depth = length(uEye - vPos);
  float fog = 1.0 - exp(-depth * uFogDensity);
  lit = mix(lit, uFogColor, clamp(fog, 0.0, 0.92));

  // Linear out. The grade happens once on the finished frame, not per
  // fragment -- unless there is no post chain, in which case do it here.
  fragColor = uTonemap > 0.5
    ? vec4(pow(tonemap(lit * uExposure), vec3(1.0 / 2.2)), uAlpha)
    : vec4(lit, uAlpha);
  // Geometric normal, not the mapped one: occlusion wants the surface, not
  // its texture.
  fragNormal = vec4(normalize(vNormal) * 0.5 + 0.5, 1.0);
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
