import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { useGLTF } from '@react-three/drei'
import { BufferGeometry, InstancedMesh, Material, Mesh, MeshStandardMaterial, Object3D } from 'three'
import { BARN, PASTURE, SILO, WHEAT, fromLocal } from '../../config/world'
import { heightAt } from '../../lib/terrain'

const BARN_URL = '/models/barn.glb'
const SILO_URL = '/models/silo.glb'
const FENCE_URL = '/models/fence.glb'
const HAY_URL = '/models/hay.glb'

function useShadows(scene: Object3D) {
  useEffect(() => {
    scene.traverse((o) => {
      const m = o as Mesh
      if (!m.isMesh) return
      m.castShadow = true
      m.receiveShadow = true
      const mat = m.material as MeshStandardMaterial
      if (mat) mat.roughness = 0.9
    })
  }, [scene])
}

/** First mesh's geometry + material, for instancing simple props. */
function firstMesh(scene: Object3D) {
  let found: Mesh | null = null
  scene.traverse((o) => {
    if (!found && (o as Mesh).isMesh) found = o as Mesh
  })
  const m = found as unknown as Mesh
  m.updateWorldMatrix(true, false)
  const g = (m.geometry as BufferGeometry).clone()
  return { geometry: g, material: m.material as Material, matrix: m.matrixWorld.clone() }
}

type T = { x: number; z: number; r: number; s: number }

function Instanced({ url, items }: { url: string; items: T[] }) {
  const { scene } = useGLTF(url)
  const ref = useRef<InstancedMesh>(null)
  const { geometry, material, matrix } = useMemo(() => firstMesh(scene), [scene])
  useLayoutEffect(() => {
    const mesh = ref.current
    if (!mesh) return
    const o = new Object3D()
    items.forEach((it, i) => {
      o.position.set(it.x, heightAt(it.x, it.z), it.z)
      o.rotation.set(0, it.r, 0)
      o.scale.setScalar(it.s)
      o.updateMatrix()
      o.matrix.multiply(matrix)
      mesh.setMatrixAt(i, o.matrix)
    })
    mesh.instanceMatrix.needsUpdate = true
    mesh.computeBoundingSphere()
  }, [items, matrix])
  return <instancedMesh ref={ref} args={[geometry, material, items.length]} castShadow receiveShadow />
}

/** Fence posts follow the pasture rectangle, leaving a gate toward the road. */
function fenceItems(): T[] {
  const SEG = 5.89
  const out: T[] = []
  const hw = PASTURE.hw + 0.6
  const hd = PASTURE.hd + 0.6
  const edges: [number, number, number, number][] = [
    [-hw, -hd, hw, -hd],
    [hw, -hd, hw, hd],
    [hw, hd, -hw, hd],
    [-hw, hd, -hw, -hd],
  ]
  edges.forEach(([ax, az, bx, bz], e) => {
    const len = Math.hypot(bx - ax, bz - az)
    const n = Math.ceil(len / SEG)
    const s = len / n / SEG
    for (let i = 0; i < n; i++) {
      if (e === 2 && i === Math.floor(n / 2)) continue // gate on the south side
      const t = (i + 0.5) / n
      const lx = ax + (bx - ax) * t
      const lz = az + (bz - az) * t
      out.push({ x: PASTURE.cx + lx, z: PASTURE.cz + lz, r: -Math.atan2(bz - az, bx - ax), s: s * 1.0 })
    }
  })
  return out
}

function hayItems(): T[] {
  const out: T[] = []
  // round bales left on the harvested headland of the wheat field
  const spots: [number, number][] = [[-12, 1.6], [-6.5, 2.2], [1.5, 1.4], [7.5, 2.4], [-14, 3.6], [10.5, 1.5]]
  for (const [lx, gap] of spots) {
    const [x, z] = fromLocal(WHEAT, lx, WHEAT.hd + gap)
    out.push({ x, z, r: lx * 0.7, s: 7.2 })
  }
  // and a stack by the barn
  out.push({ x: BARN.x - 6.5, z: BARN.z + 4, r: 0.3, s: 7.5 })
  out.push({ x: BARN.x - 8.2, z: BARN.z + 5.6, r: 1.1, s: 7.5 })
  out.push({ x: BARN.x - 7.2, z: BARN.z + 7.4, r: 2.0, s: 7.2 })
  return out
}

export function Farmstead() {
  const barn = useGLTF(BARN_URL).scene
  const silo = useGLTF(SILO_URL).scene
  useShadows(barn)
  useShadows(silo)
  const fences = useMemo(fenceItems, [])
  const hay = useMemo(hayItems, [])

  return (
    <group>
      <primitive object={barn} position={[BARN.x, heightAt(BARN.x, BARN.z) - 0.1, BARN.z]} rotation={[0, BARN.rot, 0]} scale={1.05} />
      <primitive object={silo} position={[SILO.x, heightAt(SILO.x, SILO.z) - 0.1, SILO.z]} rotation={[0, SILO.rot, 0]} scale={1.05} />
      <Instanced url={FENCE_URL} items={fences} />
      <Instanced url={HAY_URL} items={hay} />
    </group>
  )
}

useGLTF.preload([BARN_URL, SILO_URL, FENCE_URL, HAY_URL])
