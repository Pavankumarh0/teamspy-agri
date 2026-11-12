import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import type { Group } from 'three'
import { DoubleSide, MeshStandardMaterial } from 'three'
import CustomShaderMaterial from 'three-custom-shader-material/vanilla'
import { CROPS, PASTURE, ROAD_WIDTH, WHEAT, inRect, isBlocked, roadDistance } from '../../config/world'
import { mulberry32, smoothstep } from '../../lib/noise'
import { heightAt } from '../../lib/terrain'
import { createBladeGeometry } from '../geometry'
import { NOISE_GLSL } from '../shaders/chunks'
import { globalUniforms } from '../uniforms'
import { buildInstanceChunks, cullTilesByDistance, type InstanceRecord } from './instancing'

const BOUNDS = { x0: -38, x1: 34, z0: -48, z1: 20 }

/** Wind + pointer displacement shared by grass, flowers and wheat. */
export const WIND_GLSL = /* glsl */ `
  uniform float uTime;
  uniform float uWind;
  uniform vec4 uPointer;
  vec3 fhWind(vec2 wp, float t01, float height, float rand, float stiffness) {
    vec2 windDir = normalize(vec2(1.0, -0.4));
    float gust = fh_vnoise(wp * 0.07 - windDir * uTime * 0.9);
    float flutter = sin(uTime * 2.6 + rand * 6.2831 + wp.x * 0.35 + wp.y * 0.2) * 0.12;
    float bend = (0.12 + gust * 0.75 + flutter) * uWind * stiffness;
    float k = t01 * t01;
    vec3 disp = vec3(windDir.x, 0.0, windDir.y) * bend * k * height * 0.75;
    vec2 d = wp - uPointer.xz;
    float dl = length(d);
    float push = (1.0 - smoothstep(0.0, 2.6, dl)) * uPointer.w;
    disp.xz += (d / max(dl, 0.001)) * push * k * height * 1.2;
    disp.y -= dot(disp.xz, disp.xz) * 0.55 / max(height, 0.1);
    return disp;
  }
`

export function Grass({ density }: { density: number }) {
  const geometries = useMemo(() => {
    const blade = createBladeGeometry(density > 30 ? 4 : 3)
    const rand = mulberry32(1337)
    const records: InstanceRecord[] = []
    const w = BOUNDS.x1 - BOUNDS.x0
    const d = BOUNDS.z1 - BOUNDS.z0
    const candidates = Math.floor(w * d * density)
    for (let i = 0; i < candidates; i++) {
      const x = BOUNDS.x0 + rand() * w
      const z = BOUNDS.z0 + rand() * d
      // dense patch around the hero shot, sparser elsewhere
      const e = ((x + 2) / 18) ** 2 + ((z + 2) / 15) ** 2
      const hero = 1 - smoothstep(0.6, 1.25, e)
      const edge = Math.min(x - BOUNDS.x0, BOUNDS.x1 - x, z - BOUNDS.z0, BOUNDS.z1 - z)
      const edgeFade = smoothstep(0, 6, edge)
      const pasture = inRect(PASTURE, x, z, 1.5) ? 1 : 0
      const keep = Math.max(0.3 + 0.7 * hero, pasture * 0.85) * edgeFade
      if (rand() > keep) continue
      if (inRect(WHEAT, x, z, 0.2) || inRect(CROPS, x, z, 0.4) || isBlocked(x, z)) continue
      const rd = roadDistance(x, z)
      if (rd < ROAD_WIDTH * 0.5 - 0.25 && rd > 0.45) continue
      const crown = rd <= 0.45 ? 0.45 : 1 // short grass on the road's centre strip
      const roadside = smoothstep(ROAD_WIDTH * 0.5 - 0.25, ROAD_WIDTH * 0.5 + 0.8, rd)
      const grazed = pasture ? 0.55 : 1
      const h = (0.26 + rand() * 0.36) * grazed * Math.max(crown, 0.45 + 0.55 * roadside) * (0.55 + 0.45 * edgeFade)
      records.push({
        x,
        y: heightAt(x, z) - 0.03,
        z,
        v: [rand() * Math.PI * 2, h, 0.05 + rand() * 0.045, rand()],
      })
    }
    return buildInstanceChunks(blade, records, [{ name: 'aParams', size: 4 }], 10, 1.5)
  }, [density])

  const material = useMemo(
    () =>
      new CustomShaderMaterial({
        baseMaterial: MeshStandardMaterial,
        roughness: 0.9,
        side: DoubleSide,
        uniforms: globalUniforms,
        vertexShader: /* glsl */ `
          attribute vec3 aOffset;
          attribute vec4 aParams;
          varying float vT;
          varying float vRand;
          varying float vH;
          varying vec3 vGPos;
          ${NOISE_GLSL}
          ${WIND_GLSL}
          void main() {
            float t = position.y;
            vT = t;
            vRand = aParams.w;
            vH = aParams.y;
            float c = cos(aParams.x), s = sin(aParams.x);
            vec3 p = vec3(position.x * aParams.z, t * aParams.y, position.z * aParams.y);
            p = vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z);
            p += fhWind(aOffset.xz, t, aParams.y, aParams.w, 1.0);
            csm_Position = p + aOffset;
            csm_Normal = normalize(vec3(s * 0.3, 1.0, c * 0.3));
            vGPos = csm_Position;
          }
        `,
        fragmentShader: /* glsl */ `
          uniform vec3 uSunDir;
          varying float vT;
          varying float vRand;
          varying float vH;
          varying vec3 vGPos;
          void main() {
            vec3 base = vec3(0.02, 0.05, 0.01);
            vec3 mid = vec3(0.085, 0.175, 0.028);
            vec3 tip = vec3(0.36, 0.44, 0.10);
            vec3 col = mix(base, mid, smoothstep(0.0, 0.45, vT));
            col = mix(col, tip, smoothstep(0.5, 1.0, vT) * smoothstep(0.12, 0.42, vH));
            col *= 0.72 + 0.56 * vRand;
            col = mix(col, vec3(0.34, 0.30, 0.11) * (0.45 + vT), step(0.94, vRand) * 0.75);
            csm_DiffuseColor = vec4(col, 1.0);
            csm_FragNormal = normalize(vNormal); // same lighting on both faces
            vec3 V = normalize(vGPos - cameraPosition);
            float tr = pow(max(dot(V, uSunDir), 0.0), 4.0) * smoothstep(0.25, 1.0, vT);
            csm_Emissive = col * vec3(1.0, 0.82, 0.5) * tr * 2.4;
          }
        `,
      }),
    [],
  )

  const tiles = useRef<Group>(null)
  useFrame(({ camera }) => cullTilesByDistance(tiles.current, camera, 70))

  return (
    <group ref={tiles}>
      {geometries.map((g, i) => (
        <mesh key={i} geometry={g} material={material} receiveShadow />
      ))}
    </group>
  )
}
