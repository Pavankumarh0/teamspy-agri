import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { CatmullRomCurve3, PerspectiveCamera, Plane, Raycaster, Vector3 } from 'three'
import { INTRO_SHOT, SHOTS_LANDSCAPE, SHOTS_PORTRAIT, type Shot } from '../config/world'
import { SECTION_COUNT, store } from '../lib/store'
import { globalUniforms } from './uniforms'

const toV = (a: [number, number, number]) => new Vector3(...a)
function curves(shots: Shot[]) {
  return {
    pos: new CatmullRomCurve3(shots.map((s) => toV(s.pos)), false, 'centripetal', 0.5),
    target: new CatmullRomCurve3(shots.map((s) => toV(s.target)), false, 'centripetal', 0.5),
  }
}

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

/**
 * Scroll-driven cinematic camera. `store.section` (0..N-1) picks a point on a
 * spline through the section shots; the camera eases toward it with inertia,
 * adds pointer parallax and a gentle hand-held drift.
 */
export function CameraRig() {
  const camera = useThree((s) => s.camera) as PerspectiveCamera
  const size = useThree((s) => s.size)
  const landscape = useMemo(() => curves(SHOTS_LANDSCAPE), [])
  const portrait = useMemo(() => curves(SHOTS_PORTRAIT), [])
  const state = useRef({
    pos: toV(INTRO_SHOT.pos),
    target: toV(INTRO_SHOT.target),
    parallax: new Vector3(),
  })
  const tmp = useMemo(
    () => ({ pos: new Vector3(), target: new Vector3(), introPos: toV(INTRO_SHOT.pos), introTarget: toV(INTRO_SHOT.target), side: new Vector3(), up: new Vector3(0, 1, 0) }),
    [],
  )
  const ray = useMemo(() => new Raycaster(), [])
  const ground = useMemo(() => new Plane(new Vector3(0, 1, 0), 0), [])
  const hit = useMemo(() => new Vector3(), [])

  useFrame((frame, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1)
    const aspect = size.width / size.height
    const isPortrait = aspect < 0.95
    store.portrait = isPortrait
    const c = isPortrait ? portrait : landscape

    const t = Math.min(Math.max(store.section / (SECTION_COUNT - 1), 0), 1)
    c.pos.getPoint(t, tmp.pos)
    c.target.getPoint(t, tmp.target)

    // intro fly-in from a high establishing shot
    const k = easeInOut(Math.min(store.intro, 1))
    if (k < 1) {
      tmp.pos.lerpVectors(tmp.introPos, tmp.pos, k)
      tmp.target.lerpVectors(tmp.introTarget, tmp.target, k)
    }

    // pointer parallax, scaled by distance so wide shots move a little more
    const dist = tmp.pos.distanceTo(tmp.target)
    const amt = store.reducedMotion ? 0 : Math.min(0.3 + dist * 0.012, 1.4)
    tmp.side.subVectors(tmp.target, tmp.pos).cross(tmp.up).normalize()
    const px = store.pointer.x * amt
    const py = store.pointer.y * amt * 0.45
    state.current.parallax.lerp(tmp.side.multiplyScalar(px).add(new Vector3(0, py, 0)), 1 - Math.exp(-dt * 2.5))
    tmp.pos.add(state.current.parallax)

    // hand-held drift
    if (!store.reducedMotion) {
      const time = frame.clock.elapsedTime
      tmp.pos.x += Math.sin(time * 0.23) * 0.06
      tmp.pos.y += Math.sin(time * 0.31) * 0.04
    }

    const damp = 1 - Math.exp(-dt * (store.intro < 1 ? 6 : 2.6))
    state.current.pos.lerp(tmp.pos, damp)
    state.current.target.lerp(tmp.target, damp)
    camera.position.copy(state.current.pos)
    camera.lookAt(state.current.target)
    store.camTarget.copy(state.current.target)

    const fov = isPortrait ? 52 : 38
    if (Math.abs(camera.fov - fov) > 0.01) {
      camera.fov += (fov - camera.fov) * damp
      camera.updateProjectionMatrix()
    }

    // pointer → ground for grass / wheat interaction
    ray.setFromCamera(store.pointer, camera)
    ground.constant = -0.1
    if (ray.ray.intersectPlane(ground, hit) && hit.distanceTo(camera.position) < 45) {
      globalUniforms.uPointer.value.x = hit.x
      globalUniforms.uPointer.value.y = hit.y
      globalUniforms.uPointer.value.z = hit.z
    }
    store.pointerActive = Math.max(0, store.pointerActive - dt * 0.6)
    globalUniforms.uPointer.value.w += (store.pointerActive - globalUniforms.uPointer.value.w) * (1 - Math.exp(-dt * 6))
    globalUniforms.uTime.value = frame.clock.elapsedTime
  })

  return null
}
