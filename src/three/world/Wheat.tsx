import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import type { Group } from 'three'
import { DoubleSide, MeshStandardMaterial } from 'three'
import CustomShaderMaterial from 'three-custom-shader-material/vanilla'
import { WHEAT, fromLocal } from '../../config/world'
import { mulberry32, smoothstep } from '../../lib/noise'
import { heightAt } from '../../lib/terrain'
import { createWheatGeometry } from '../geometry'
import { NOISE_GLSL } from '../shaders/chunks'
import { globalUniforms } from '../uniforms'
import { buildInstanceChunks, cullTilesByDistance, type InstanceRecord } from './instancing'

/** Golden wheat with rolling wind waves and a travelling sheen across the field. */
export function Wheat({ density }: { density: number }) {
  const geometries = useMemo(() => {
    const base = createWheatGeometry()
    const rand = mulberry32(4242)
    const records: InstanceRecord[] = []
    const perM2 = 10.5 * density
    const count = Math.floor(WHEAT.hw * 2 * WHEAT.hd * 2 * perM2)
    for (let i = 0; i < count; i++) {
      const lx = (rand() * 2 - 1) * WHEAT.hw
      const lz = (rand() * 2 - 1) * WHEAT.hd
      // ragged, hand-sown edges
      const edge = Math.min(WHEAT.hw - Math.abs(lx), WHEAT.hd - Math.abs(lz))
      const ragged = smoothstep(-0.2, 1.6, edge + Math.sin(lx * 1.3 + lz * 0.7) * 0.6)
      if (rand() > ragged) continue
      const [x, z] = fromLocal(WHEAT, lx, lz)
      const h = (0.92 + rand() * 0.38) * (0.75 + 0.25 * ragged)
      records.push({ x, y: heightAt(x, z) - 0.04, z, v: [rand() * Math.PI * 2, h, 0.9 + rand() * 0.25, rand()] })
    }
    return buildInstanceChunks(base, records, [{ name: 'aParams', size: 4 }], 9, 1.8)
  }, [density])

  const material = useMemo(
    () =>
      new CustomShaderMaterial({
        baseMaterial: MeshStandardMaterial,
        roughness: 0.75,
        side: DoubleSide,
        uniforms: globalUniforms,
        vertexShader: /* glsl */ `
          attribute vec3 aOffset;
          attribute vec4 aParams;
          attribute float aPart;
          uniform float uTime;
          uniform float uWind;
          uniform vec4 uPointer;
          varying float vT;
          varying float vRand;
          varying float vPart;
          varying float vWave;
          varying vec2 vUv2;
          varying vec3 vGPos;
          ${NOISE_GLSL}
          void main() {
            float t = uv.y;
            vT = t;
            vUv2 = uv;
            vRand = aParams.w;
            vPart = aPart;
            float c = cos(aParams.x), s = sin(aParams.x);
            vec3 p = position * vec3(aParams.z, aParams.y, aParams.z);
            p = vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z);

            vec2 wp = aOffset.xz;
            vec2 windDir = normalize(vec2(1.0, -0.4));
            float phase = dot(wp, windDir) * 0.24 - uTime * 1.8;
            float gust = fh_vnoise(wp * 0.035 - windDir * uTime * 0.25);
            float wave = (sin(phase) * 0.5 + 0.5) * (0.35 + gust * 0.9);
            vWave = wave;
            float sway = sin(uTime * 2.1 + aParams.w * 6.2831) * 0.05;
            float bend = (0.08 + wave * 0.42 + sway) * uWind;
            float k = pow(t, 1.7);
            vec3 disp = vec3(windDir.x, 0.0, windDir.y) * bend * k * aParams.y;
            vec2 d = wp - uPointer.xz;
            float dl = length(d);
            disp.xz += (d / max(dl, 0.001)) * (1.0 - smoothstep(0.0, 2.8, dl)) * uPointer.w * k * 0.9;
            disp.y -= dot(disp.xz, disp.xz) * 0.5;
            csm_Position = p + disp + aOffset;
            csm_Normal = normalize(vec3(windDir.x * bend, 1.0, windDir.y * bend));
            vGPos = csm_Position;
          }
        `,
        fragmentShader: /* glsl */ `
          uniform vec3 uSunDir;
          varying float vT;
          varying float vRand;
          varying float vPart;
          varying float vWave;
          varying vec2 vUv2;
          varying vec3 vGPos;
          void main() {
            vec3 col;
            if (vPart > 0.5) {
              float ty = clamp((vUv2.y - 0.78) / 0.22, 0.0, 1.0);
              float serr = 0.78 + 0.22 * step(0.5, fract(ty * 8.0));
              float w = pow(sin(ty * 3.14159), 0.7) * 0.5 * serr;
              if (abs(vUv2.x - 0.5) > w) discard;
              col = mix(vec3(0.58, 0.36, 0.07), vec3(0.86, 0.58, 0.14), ty) * (0.82 + 0.36 * vRand);
            } else {
              col = mix(vec3(0.13, 0.09, 0.025), vec3(0.60, 0.40, 0.09), smoothstep(0.0, 0.65, vT));
              col = mix(col, vec3(0.30, 0.36, 0.10), step(0.9, vRand) * 0.4 * (1.0 - vT));
            }
            col *= 0.86 + vWave * 0.42;
            csm_DiffuseColor = vec4(col, 1.0);
            csm_FragNormal = normalize(vNormal); // same lighting on both faces
            vec3 V = normalize(vGPos - cameraPosition);
            float tr = pow(max(dot(V, uSunDir), 0.0), 3.0) * smoothstep(0.3, 1.0, vT);
            csm_Emissive = col * vec3(1.0, 0.8, 0.45) * (tr * 2.2 + vWave * 0.08);
          }
        `,
      }),
    [],
  )

  const tiles = useRef<Group>(null)
  useFrame(({ camera }) => cullTilesByDistance(tiles.current, camera, 120))

  return (
    <group ref={tiles}>
      {geometries.map((g, i) => (
        <mesh key={i} geometry={g} material={material} receiveShadow />
      ))}
    </group>
  )
}
