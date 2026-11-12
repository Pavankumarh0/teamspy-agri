import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import type { Group } from 'three'
import { Color, DoubleSide, MeshStandardMaterial } from 'three'
import CustomShaderMaterial from 'three-custom-shader-material/vanilla'
import { CROPS, PASTURE, ROAD_WIDTH, WHEAT, inRect, isBlocked, roadDistance } from '../../config/world'
import { mulberry32 } from '../../lib/noise'
import { heightAt } from '../../lib/terrain'
import { createFlowerGeometry } from '../geometry'
import { NOISE_GLSL } from '../shaders/chunks'
import { globalUniforms } from '../uniforms'
import { WIND_GLSL } from './Grass'
import { buildInstanceChunks, cullTilesByDistance, type InstanceRecord } from './instancing'

const COLORS = ['#f4f1e8', '#f4f1e8', '#f2c94c', '#f2c94c', '#b28ad6', '#6f8fd8', '#e2553f']

/** Meadow wildflowers: daisies, buttercups, clover, cornflowers and the odd poppy. */
export function Flowers({ density }: { density: number }) {
  const geometries = useMemo(() => {
    const base = createFlowerGeometry()
    const rand = mulberry32(99)
    const records: InstanceRecord[] = []
    const count = Math.floor(5200 * density)
    const tmp = new Color()
    for (let i = 0; i < count; i++) {
      const x = -34 + rand() * 64
      const z = -44 + rand() * 60
      if (inRect(WHEAT, x, z, 0.6) || inRect(CROPS, x, z, 0.6) || inRect(PASTURE, x, z, -0.5) || isBlocked(x, z)) continue
      if (roadDistance(x, z) < ROAD_WIDTH * 0.5 + 0.3) continue
      // flowers grow in drifts
      const drift = Math.sin(x * 0.21) * Math.cos(z * 0.17) + Math.sin(x * 0.07 + z * 0.11)
      if (drift < 0.2 + rand() * 0.6) continue
      // poppies near the wheat, the rest spread by drift
      const nearWheat = inRect(WHEAT, x, z, 3)
      const ci = nearWheat && rand() < 0.5 ? 6 : Math.floor(rand() * 6)
      tmp.set(COLORS[ci])
      const h = 0.22 + rand() * 0.28
      records.push({
        x,
        y: heightAt(x, z) - 0.02,
        z,
        v: [rand() * Math.PI * 2, h, 0.7 + rand() * 0.6, rand(), tmp.r, tmp.g, tmp.b],
      })
    }
    return buildInstanceChunks(base, records, [{ name: 'aParams', size: 4 }, { name: 'aColor', size: 3 }], 12, 1)
  }, [density])

  const material = useMemo(
    () =>
      new CustomShaderMaterial({
        baseMaterial: MeshStandardMaterial,
        roughness: 0.7,
        side: DoubleSide,
        uniforms: globalUniforms,
        vertexShader: /* glsl */ `
          attribute vec3 aOffset;
          attribute vec4 aParams;
          attribute vec3 aColor;
          attribute float aPart;
          varying float vPart;
          varying vec2 vUv2;
          varying vec3 vColor;
          ${NOISE_GLSL}
          ${WIND_GLSL}
          void main() {
            vPart = aPart;
            vUv2 = uv;
            vColor = aColor;
            float c = cos(aParams.x), s = sin(aParams.x);
            vec3 p = position;
            p.y *= aParams.y / 0.95;
            p.xz *= aPart > 0.5 ? aParams.z : 1.0;
            p = vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z);
            float t = clamp(position.y / 0.95, 0.0, 1.0);
            p += fhWind(aOffset.xz, t, aParams.y, aParams.w, 0.8);
            csm_Position = p + aOffset;
          }
        `,
        fragmentShader: /* glsl */ `
          varying float vPart;
          varying vec2 vUv2;
          varying vec3 vColor;
          void main() {
            vec3 col = vec3(0.08, 0.16, 0.03);
            if (vPart > 0.5) {
              vec2 q = vUv2 * 2.0 - 1.0;
              float r = length(q);
              float a = atan(q.y, q.x);
              float petal = 0.55 + 0.45 * abs(cos(a * 2.5));
              if (r > petal) discard;
              col = r < 0.24 ? vec3(0.85, 0.6, 0.1) : vColor * (0.85 + 0.25 * (1.0 - r));
            }
            csm_DiffuseColor = vec4(col, 1.0);
            csm_FragNormal = normalize(vNormal); // same lighting on both faces
          }
        `,
      }),
    [],
  )

  const tiles = useRef<Group>(null)
  useFrame(({ camera }) => cullTilesByDistance(tiles.current, camera, 55))

  return (
    <group ref={tiles}>
      {geometries.map((g, i) => (
        <mesh key={i} geometry={g} material={material} receiveShadow />
      ))}
    </group>
  )
}
