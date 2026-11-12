import { useLayoutEffect, useMemo, useRef } from 'react'
import { Color, DoubleSide, InstancedBufferAttribute, InstancedMesh, MeshStandardMaterial, Object3D } from 'three'
import CustomShaderMaterial from 'three-custom-shader-material/vanilla'
import { CROPS, CROP_ROW_SPACING, fromLocal } from '../../config/world'
import { mulberry32 } from '../../lib/noise'
import { heightAt } from '../../lib/terrain'
import { createCropGeometry } from '../geometry'
import { globalUniforms } from '../uniforms'

/** Young leafy crops planted in rows across the ploughed field. */
export function Crops({ density }: { density: number }) {
  const ref = useRef<InstancedMesh>(null)

  const placements = useMemo(() => {
    const rand = mulberry32(555)
    const out: { x: number; y: number; z: number; r: number; s: number; c: number }[] = []
    const spacing = 0.55 / Math.sqrt(Math.max(density, 0.3))
    for (let lx = -CROPS.hw + 0.8; lx <= CROPS.hw - 0.8; lx += CROP_ROW_SPACING) {
      const rowX = Math.round(lx / CROP_ROW_SPACING) * CROP_ROW_SPACING
      for (let lz = -CROPS.hd + 0.6; lz <= CROPS.hd - 0.6; lz += spacing) {
        if (rand() < 0.06) continue // a few gaps feel hand-tended
        const [x, z] = fromLocal(CROPS, rowX + (rand() - 0.5) * 0.12, lz + (rand() - 0.5) * 0.15)
        out.push({ x, y: heightAt(x, z) + 0.02, z, r: rand() * Math.PI * 2, s: 0.75 + rand() * 0.55, c: rand() })
      }
    }
    return out
  }, [density])

  const geometry = useMemo(() => {
    const g = createCropGeometry(6)
    const tint = new Float32Array(placements.length * 3)
    const a = new Color('#3f7a1f')
    const b = new Color('#86ad3c')
    const c = new Color()
    placements.forEach((p, i) => {
      c.copy(a).lerp(b, p.c)
      tint.set([c.r, c.g, c.b], i * 3)
    })
    g.setAttribute('aTint', new InstancedBufferAttribute(tint, 3))
    return g
  }, [placements])

  const material = useMemo(
    () =>
      new CustomShaderMaterial({
        baseMaterial: MeshStandardMaterial,
        roughness: 0.65,
        side: DoubleSide,
        uniforms: globalUniforms,
        vertexShader: /* glsl */ `
          attribute vec3 aTint;
          uniform float uTime;
          uniform float uWind;
          varying float vH;
          varying vec3 vTint;
          void main() {
            vTint = aTint;
            vec3 ip = instanceMatrix[3].xyz;
            float lift = smoothstep(0.0, 0.35, length(position.xz));
            vH = position.y;
            vec3 p = position;
            p.y += sin(uTime * 2.4 + ip.x * 0.8 + ip.z * 0.5 + position.x * 4.0) * 0.025 * lift * uWind;
            p.x += sin(uTime * 1.7 + ip.z * 0.6) * 0.02 * lift * uWind;
            csm_Position = p;
          }
        `,
        fragmentShader: /* glsl */ `
          varying float vH;
          varying vec3 vTint;
          void main() {
            csm_DiffuseColor = vec4(vTint * (0.45 + vH * 2.4), 1.0);
            csm_FragNormal = normalize(vNormal); // same lighting on both faces
          }
        `,
      }),
    [],
  )

  useLayoutEffect(() => {
    const mesh = ref.current
    if (!mesh) return
    const o = new Object3D()
    placements.forEach((p, i) => {
      o.position.set(p.x, p.y, p.z)
      o.rotation.set(0, p.r, 0)
      o.scale.setScalar(p.s)
      o.updateMatrix()
      mesh.setMatrixAt(i, o.matrix)
    })
    mesh.instanceMatrix.needsUpdate = true
    mesh.computeBoundingSphere()
  }, [placements])

  return <instancedMesh ref={ref} args={[geometry, material, placements.length]} receiveShadow castShadow={false} />
}
