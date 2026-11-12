import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html, useAnimations, useGLTF } from '@react-three/drei'
import { Bone, Euler, Group, LoopOnce, Mesh, MeshStandardMaterial, Quaternion } from 'three'
import { mergeVertices } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { FARMER_POS } from '../../config/world'
import { heightAt } from '../../lib/terrain'
import { worldUiRef, onActiveSection, store } from '../../lib/store'

const URL = '/models/farmer.glb'

/** Re-computes smooth normals so the low-poly character reads softer and more natural. */
function smoothShade(mesh: Mesh) {
  const g = mesh.geometry.clone()
  g.deleteAttribute('normal')
  const merged = mergeVertices(g, 1e-4)
  merged.computeVertexNormals()
  mesh.geometry = merged
}

/** Slightly more natural, earthy fabric tones than the stock flat colours. */
const RETINT: Record<string, string> = {
  Brown: '#6b4a2e',
  Brown2: '#8a6a3c',
  LightBlue: '#3d4f5c',
  Beige: '#d8c9a3',
  Skin: '#d9a982',
  Red: '#8c2f22',
}

export function Farmer() {
  const group = useRef<Group>(null)
  const { scene, animations } = useGLTF(URL)
  const { actions, mixer } = useAnimations(animations, group)
  const [hover, setHover] = useState(false)
  const [showHint, setShowHint] = useState(true)
  const busy = useRef(false)

  const head = useMemo(() => {
    let found: Bone | null = null
    scene.traverse((o) => {
      if (!found && (o as Bone).isBone && /head/i.test(o.name)) found = o as Bone
    })
    return found as Bone | null
  }, [scene])

  useEffect(() => {
    scene.traverse((o) => {
      const m = o as Mesh
      if (!m.isMesh) return
      m.castShadow = true
      m.receiveShadow = true
      m.frustumCulled = false
      if (!m.userData.smoothed) {
        smoothShade(m)
        m.userData.smoothed = true
      }
      const mat = m.material as MeshStandardMaterial
      if (mat && RETINT[mat.name]) mat.color.set(RETINT[mat.name])
      if (mat) {
        mat.roughness = 0.82
        mat.metalness = 0
      }
    })
  }, [scene])

  useEffect(() => {
    const idle = actions.Idle
    idle?.reset().fadeIn(0.6).play()
    const onFinish = () => {
      busy.current = false
      actions.Interact?.fadeOut(0.4)
      idle?.reset().fadeIn(0.4).play()
    }
    mixer.addEventListener('finished', onFinish)
    return () => mixer.removeEventListener('finished', onFinish)
  }, [actions, mixer])

  useEffect(() => onActiveSection((a) => setShowHint(a === 0)), [])

  const wave = () => {
    const a = actions.Interact
    if (!a || busy.current) return
    busy.current = true
    a.reset()
    a.setLoop(LoopOnce, 1)
    a.clampWhenFinished = true
    actions.Idle?.fadeOut(0.3)
    a.fadeIn(0.3).play()
  }

  // Additive head look-at toward the pointer, applied after the mixer and undone before it.
  const offset = useRef(new Quaternion())
  const inv = useRef(new Quaternion())
  const look = useRef({ yaw: 0, pitch: 0 })
  const euler = useMemo(() => new Euler(), [])
  useFrame(() => {
    if (head) head.quaternion.multiply(inv.current)
  }, -1)
  useFrame((_, dt) => {
    if (!head) return
    const k = 1 - Math.exp(-dt * 4)
    const active = store.section < 0.6 ? 1 : 0
    look.current.yaw += (store.pointer.x * 0.55 * active - look.current.yaw) * k
    look.current.pitch += (-store.pointer.y * 0.22 * active - look.current.pitch) * k
    euler.set(look.current.pitch, look.current.yaw, 0)
    offset.current.setFromEuler(euler)
    inv.current.copy(offset.current).invert()
    head.quaternion.multiply(offset.current)
  })

  const y = heightAt(FARMER_POS.x, FARMER_POS.z)

  return (
    <group position={[FARMER_POS.x, y, FARMER_POS.z]} rotation={[0, 0.42, 0]}>
      <group ref={group}>
        <primitive object={scene} />
      </group>
      {/* cheap hit-box instead of ray-casting the skinned mesh */}
      <mesh
        position={[0, 0.95, 0]}
        visible={false}
        onPointerOver={(e) => {
          e.stopPropagation()
          setHover(true)
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={() => {
          setHover(false)
          document.body.style.cursor = ''
        }}
        onClick={(e) => {
          e.stopPropagation()
          wave()
        }}
      >
        <capsuleGeometry args={[0.38, 1.1, 4, 8]} />
      </mesh>
      <Html position={[0.1, 2.2, 0]} center portal={worldUiRef as RefObject<HTMLElement>} zIndexRange={[5, 0]} className="hint-wrap">
        <button
          type="button"
          className={`farmer-hint ${showHint ? 'is-on' : ''} ${hover ? 'is-hover' : ''}`}
          onClick={wave}
          tabIndex={showHint ? 0 : -1}
        >
          <span className="dot" /> Say <span lang="kn">ನಮಸ್ಕಾರ</span>
        </button>
      </Html>
    </group>
  )
}

useGLTF.preload(URL)
