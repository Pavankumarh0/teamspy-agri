import { Color, ShaderChunk } from 'three'
import { SUN_DIR } from '../../config/world'

/** sRGB hex → linear GLSL vec3 literal. */
const lin = (hex: string, mul = 1) => {
  const c = new Color(hex)
  return `vec3(${(c.r * mul).toFixed(4)}, ${(c.g * mul).toFixed(4)}, ${(c.b * mul).toFixed(4)})`
}
const v3 = (x: number, y: number, z: number) => `vec3(${x.toFixed(5)}, ${y.toFixed(5)}, ${z.toFixed(5)})`

export const PALETTE = {
  zenith: '#3470b8',
  upper: '#86b4dc',
  horizonCool: '#bfd4e2',
  horizonWarm: '#f7d3a0',
  sunGlow: '#ffc98a',
  sun: '#fff2d8',
}

/** Value noise + fbm, shared by every custom shader. */
export const NOISE_GLSL = /* glsl */ `
float fh_hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
float fh_vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(fh_hash12(i), fh_hash12(i + vec2(1.0, 0.0)), u.x),
             mix(fh_hash12(i + vec2(0.0, 1.0)), fh_hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fh_fbm(vec2 p) {
  float s = 0.0;
  float a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 5; i++) {
    s += a * fh_vnoise(p);
    p = m * p;
    a *= 0.5;
  }
  return s;
}
`

/** Sky gradient + sun glow. Used by the sky dome AND the fog, so they always match. */
export const ATMOSPHERE_GLSL = /* glsl */ `
const vec3 FH_SUN_DIR = ${v3(SUN_DIR.x, SUN_DIR.y, SUN_DIR.z)};
const vec3 FH_ZENITH = ${lin(PALETTE.zenith)};
const vec3 FH_UPPER = ${lin(PALETTE.upper)};
const vec3 FH_HORIZON_COOL = ${lin(PALETTE.horizonCool)};
const vec3 FH_HORIZON_WARM = ${lin(PALETTE.horizonWarm)};
const vec3 FH_SUN_GLOW = ${lin(PALETTE.sunGlow)};
const vec3 FH_SUN = ${lin(PALETTE.sun)};

vec3 fh_atmosphere(vec3 dir) {
  float y = dir.y;
  float sunAmt = max(dot(dir, FH_SUN_DIR), 0.0);
  vec2 dh = normalize(dir.xz + vec2(1e-5));
  vec2 sh = normalize(FH_SUN_DIR.xz);
  float az = dot(dh, sh) * 0.5 + 0.5;
  vec3 horizon = mix(FH_HORIZON_COOL, FH_HORIZON_WARM, pow(az, 2.2));
  float t = pow(clamp(y, 0.0, 1.0), 0.5);
  vec3 col = mix(horizon, FH_UPPER, smoothstep(0.0, 0.5, t));
  col = mix(col, FH_ZENITH, smoothstep(0.4, 1.0, t));
  col += FH_SUN_GLOW * (pow(sunAmt, 5.0) * 0.32 + pow(sunAmt, 40.0) * 0.55);
  col = mix(col, horizon * 0.95, smoothstep(0.0, -0.1, y));
  return col * 1.08;
}
`

let installed = false

/**
 * Replaces three's flat fog with aerial perspective: fog colour is looked up
 * from the same sky function along the view ray, it thins with altitude, and it
 * glows warm toward the sun. Must run before any material compiles.
 */
export function installAtmosphere() {
  if (installed) return
  installed = true

  ShaderChunk.fog_pars_vertex = /* glsl */ `
#ifdef USE_FOG
  varying float vFogDepth;
  varying vec3 vFogWorldDir;
#endif
`
  ShaderChunk.fog_vertex = /* glsl */ `
#ifdef USE_FOG
  vFogDepth = - mvPosition.z;
  vFogWorldDir = (vec4(mvPosition.xyz, 0.0) * viewMatrix).xyz;
#endif
`
  ShaderChunk.fog_pars_fragment = /* glsl */ `
#ifdef USE_FOG
  uniform vec3 fogColor;
  varying float vFogDepth;
  varying vec3 vFogWorldDir;
  #ifdef FOG_EXP2
    uniform float fogDensity;
  #else
    uniform float fogNear;
    uniform float fogFar;
  #endif
  ${ATMOSPHERE_GLSL}
#endif
`
  ShaderChunk.fog_fragment = /* glsl */ `
#ifdef USE_FOG
  float fhDist = length(vFogWorldDir);
  vec3 fhDir = vFogWorldDir / max(fhDist, 1e-4);
  #ifdef FOG_EXP2
    float fogFactor = 1.0 - exp(- fogDensity * fogDensity * fhDist * fhDist);
  #else
    float fogFactor = smoothstep(fogNear, fogFar, fhDist);
  #endif
  float fhY = cameraPosition.y + vFogWorldDir.y;
  fogFactor *= mix(1.0, 0.62, smoothstep(12.0, 260.0, fhY));
  vec3 fhCol = fh_atmosphere(normalize(vec3(fhDir.x, max(fhDir.y, 0.0) * 0.35, fhDir.z)));
  fhCol = mix(fhCol, fogColor, 0.15);
  gl_FragColor.rgb = mix(gl_FragColor.rgb, fhCol, fogFactor);
#endif
`
}
