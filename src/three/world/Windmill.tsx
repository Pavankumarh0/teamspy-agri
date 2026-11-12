import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { Box3, Group, Mesh, Object3D, Vector3 } from 'three'
import { WINDMILL } from '../../config/world'
import { heightAt } from '../../lib/terrain'

const URL = '/models/windmill.glb'
const SCALE = 1.3

/** Tower windmill on the hill; the sail assembly is re-pivoted on its hub and spun. */
export function Windmill() {
  const { scene } = useGLTF(URL)
  const pivot = useRef<Group | null>(null)

  const { axis, yaw } = useMemo(() => {
    scene.updateMatrixWorld(true)
    let blades: Object3D | null = null
    scene.traverse((o) => {
      if (!blades && /blade/i.test(o.name)) blades = o
    })
    let axis: 'x' | 'z' = 'z'
    if (blades) {
      const b = blades as Object3D
      const box = new Box3().setFromObject(b)
      const size = box.getSize(new Vector3())
      const center = box.getCenter(new Vector3())
      axis = size.x < size.z ? 'x' : 'z'
      const g = new Group()
      g.name = 'SailPivot'
      g.position.copy(center)
      scene.add(g)
      g.updateMatrixWorld(true)
      g.attach(b)
      pivot.current = g
    }
    // turn the sails to face the farm
    const dx = -4 - WINDMILL.x
    const dz = -34 - WINDMILL.z
    const face = Math.atan2(dx, dz)
    const yaw = axis === 'z' ? face : face - Math.PI / 2
    return { axis, yaw }
  }, [scene])

  useEffect(() => {
    scene.traverse((o) => {
      const m = o as Mesh
      if (m.isMesh) {
        m.castShadow = true
        m.receiveShadow = true
      }
    })
  }, [scene])

  useFrame((_, dt) => {
    const p = pivot.current
    if (p) p.rotation[axis] += dt * 0.55
  })

  return (
    <group position={[WINDMILL.x, heightAt(WINDMILL.x, WINDMILL.z) - 0.2, WINDMILL.z]} rotation={[0, yaw, 0]}>
      <primitive object={scene} scale={SCALE} />
    </group>
  )
}

useGLTF.preload(URL)
