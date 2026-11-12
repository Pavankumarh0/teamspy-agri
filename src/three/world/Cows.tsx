import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { useAnimations, useGLTF } from '@react-three/drei'
import { Group, Mesh, MeshStandardMaterial } from 'three'
import { clone as cloneSkinned } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { mergeVertices } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { heightAt } from '../../lib/terrain'

const MODELS = {
  hereford: { url: '/models/cow.glb', scale: 0.33 },
  holstein: { url: '/models/cow-holstein.glb', scale: 0.29 },
} as const

type Kind = keyof typeof MODELS

/** Re-computes smooth normals so the low-poly character reads softer and more natural. */
function smoothShade(mesh: Mesh) {
  const g = mesh.geometry.clone()
  g.deleteAttribute('normal')
  const merged = mergeVertices(g, 1e-4)
  merged.computeVertexNormals()
  mesh.geometry = merged
}
type Walk = { cx: number; cz: number; rx: number; rz: number; speed: number; phase: number }
type CowSpec = { kind: Kind; x: number; z: number; r: number; clip: string; walk?: Walk; speed?: number }

/** Herd inside the pasture (see PASTURE in config/world). */
const HERD: CowSpec[] = [
  { kind: 'hereford', x: -2.5, z: -18.5, r: 0.9, clip: 'Eating' },
  { kind: 'holstein', x: 6.2, z: -16, r: -2.5, clip: 'Idle', speed: 0.8 },
  { kind: 'hereford', x: 9.8, z: -27.5, r: 2.6, clip: 'Idle_Headlow' },
  { kind: 'holstein', x: -1.5, z: -30, r: 1.7, clip: 'Idle' },
  { kind: 'hereford', x: 3.2, z: -24, r: -0.7, clip: 'Eating', speed: 0.9 },
  { kind: 'hereford', x: 10.5, z: -19.5, r: 3.6, clip: 'Eating', speed: 1.1 },
  {
    kind: 'holstein', x: 0, z: 0, r: 0, clip: 'WalkSlow',
    walk: { cx: 3.5, cz: -23.5, rx: 6.2, rz: 7.8, speed: 0.042, phase: 1.2 },
  },
]

function Cow({ spec }: { spec: CowSpec }) {
  const { url, scale } = MODELS[spec.kind]
  const { scene, animations } = useGLTF(url)
  const clone = useMemo(() => cloneSkinned(scene) as Group, [scene])
  const root = useRef<Group>(null)
  const { actions } = useAnimations(animations, root)

  useEffect(() => {
    clone.traverse((o) => {
      const m = o as Mesh
      if (!m.isMesh) return
      m.castShadow = true
      m.receiveShadow = true
      m.frustumCulled = false
      smoothShade(m)
      const mat = m.material as MeshStandardMaterial
      if (mat) {
        m.material = mat.clone()
        ;(m.material as MeshStandardMaterial).roughness = 0.88
      }
    })
  }, [clone])

  useEffect(() => {
    const a = actions[spec.clip] ?? Object.values(actions)[0]
    if (!a) return
    a.reset().play()
    a.time = Math.random() * a.getClip().duration
    a.timeScale = spec.speed ?? 0.85 + Math.random() * 0.3
  }, [actions, spec])

  const theta = useRef(spec.walk?.phase ?? 0)
  useFrame((_, dt) => {
    const w = spec.walk
    const g = root.current
    if (!w || !g) return
    theta.current += w.speed * dt
    const t = theta.current
    const x = w.cx + Math.cos(t) * w.rx
    const z = w.cz + Math.sin(t) * w.rz
    const tx = -Math.sin(t) * w.rx
    const tz = Math.cos(t) * w.rz
    g.position.set(x, heightAt(x, z), z)
    g.rotation.y = Math.atan2(tx, tz)
  })

  return (
    <group
      ref={root}
      position={spec.walk ? undefined : [spec.x, heightAt(spec.x, spec.z), spec.z]}
      rotation={spec.walk ? undefined : [0, spec.r, 0]}
    >
      <primitive object={clone} scale={scale} />
    </group>
  )
}

export function Cows() {
  return (
    <group>
      {HERD.map((c, i) => (
        <Cow key={i} spec={c} />
      ))}
    </group>
  )
}

export const COW_LABEL_POS: [number, number, number] = [-2.5, 2.4, -18.5]

useGLTF.preload(MODELS.hereford.url)
useGLTF.preload(MODELS.holstein.url)
