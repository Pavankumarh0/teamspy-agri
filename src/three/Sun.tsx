import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { DirectionalLight, Object3D, Vector3 } from 'three'
import { SUN_DIR } from '../config/world'
import { store } from '../lib/store'

const SHADOW_EXTENT = 34

/**
 * Warm key light. Its orthographic shadow camera tracks whatever the camera is
 * looking at (snapped to shadow-map texels to avoid shimmering), so a single
 * 2K map gives crisp shadows anywhere along the scroll journey.
 */
export function Sun({ mapSize, throttle = false }: { mapSize: number; throttle?: boolean }) {
  const gl = useThree((st) => st.gl)
  const frame = useRef(0)
  const light = useRef<DirectionalLight>(null)
  const target = useRef(new Object3D())
  const focus = useRef(new Vector3())

  useEffect(() => {
    const l = light.current
    if (!l) return
    l.target = target.current
    const cam = l.shadow.camera
    cam.left = -SHADOW_EXTENT
    cam.right = SHADOW_EXTENT
    cam.top = SHADOW_EXTENT
    cam.bottom = -SHADOW_EXTENT
    cam.near = 1
    cam.far = 260
    cam.updateProjectionMatrix()
  }, [])

  useEffect(() => {
    gl.shadowMap.autoUpdate = !throttle
    gl.shadowMap.needsUpdate = true
  }, [gl, throttle])

  useFrame(() => {
    const l = light.current
    if (!l) return
    if (throttle && frame.current++ % 2 === 0) gl.shadowMap.needsUpdate = true
    // aim slightly toward the camera from the look-at point so foreground objects stay inside
    focus.current.copy(store.camTarget)
    const texel = (SHADOW_EXTENT * 2) / mapSize
    focus.current.x = Math.round(focus.current.x / texel) * texel
    focus.current.z = Math.round(focus.current.z / texel) * texel
    target.current.position.copy(focus.current)
    target.current.updateMatrixWorld()
    l.position.copy(focus.current).addScaledVector(SUN_DIR, 120)
  })

  return (
    <>
      <directionalLight
        ref={light}
        color="#ffd59c"
        intensity={3.5}
        castShadow
        shadow-mapSize={[mapSize, mapSize]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.035}
        shadow-radius={3}
      />
      <primitive object={target.current} />
      <hemisphereLight args={['#bcd6f2', '#56652c', 0.75]} />
    </>
  )
}
