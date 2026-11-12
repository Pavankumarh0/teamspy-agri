import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import {
  BufferAttribute,
  Color,
  BufferGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  NormalBlending,
  type Blending,
  Points,
  ShaderMaterial,
  Vector3,
} from 'three'
import { ROAD_LOOP } from '../../config/world'
import { heightAt } from '../../lib/terrain'

const URL = '/models/tractor.glb'
const SCALE = 0.26
const SPEED = 3.1 // m/s
/** The model's nose points along -Z, so it is flipped to face its direction of travel. */
const MODEL_YAW = Math.PI

/** Shared live tractor position so other parts of the scene (labels) can follow it. */
export const tractorState = { position: new Vector3(), heading: 0 }

type Particle = { p: Vector3; v: Vector3; age: number; life: number; size: number }

function Puffs({ count, color, blending, opacity }: { count: number; color: string; blending: Blending; opacity: number }) {
  const ref = useRef<Points>(null)
  const dpr = useThree((s) => s.viewport.dpr)
  const geometry = useMemo(() => {
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(new Float32Array(count * 3), 3))
    g.setAttribute('aLife', new BufferAttribute(new Float32Array(count), 1))
    g.setAttribute('aSize', new BufferAttribute(new Float32Array(count), 1))
    return g
  }, [count])
  const material = useMemo(
    () =>
      new ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending,
        uniforms: { uColor: { value: new Vector3() }, uOpacity: { value: opacity }, uDpr: { value: dpr } },
        vertexShader: /* glsl */ `
          attribute float aLife;
          attribute float aSize;
          uniform float uDpr;
          varying float vLife;
          void main() {
            vLife = aLife;
            vec4 mv = modelViewMatrix * vec4(position, 1.0);
            gl_Position = projectionMatrix * mv;
            gl_PointSize = aSize * uDpr * (420.0 / max(-mv.z, 0.5));
          }
        `,
        fragmentShader: /* glsl */ `
          uniform vec3 uColor;
          uniform float uOpacity;
          varying float vLife;
          void main() {
            float d = length(gl_PointCoord - 0.5);
            float a = smoothstep(0.5, 0.05, d) * sin(clamp(vLife, 0.0, 1.0) * 3.14159) * uOpacity;
            if (a < 0.01) discard;
            gl_FragColor = vec4(uColor, a);
          }
        `,
      }),
    [blending, opacity, dpr],
  )
  useEffect(() => {
    const col = new Color(color)
    material.uniforms.uColor.value.set(col.r, col.g, col.b)
  }, [color, material])
  return <points ref={ref} geometry={geometry} material={material} frustumCulled={false} />
}

export function Tractor() {
  const { scene } = useGLTF(URL)
  const group = useRef<Group>(null)
  const body = useRef<Group>(null)
  const smoke = useRef<Group>(null)
  const dust = useRef<Group>(null)
  const length = useMemo(() => ROAD_LOOP.getLength(), [])
  const u = useRef(0.62)

  useEffect(() => {
    scene.traverse((o) => {
      const m = o as Mesh
      if (!m.isMesh) return
      m.castShadow = true
      m.receiveShadow = true
      const mat = m.material as MeshStandardMaterial
      mat.roughness = 0.55
      mat.metalness = 0.1
    })
  }, [scene])

  const smokeParts = useMemo<Particle[]>(
    () => Array.from({ length: 26 }, () => ({ p: new Vector3(0, -100, 0), v: new Vector3(), age: 1, life: 1, size: 0 })),
    [],
  )
  const dustParts = useMemo<Particle[]>(
    () => Array.from({ length: 40 }, () => ({ p: new Vector3(0, -100, 0), v: new Vector3(), age: 1, life: 1, size: 0 })),
    [],
  )
  const spawn = useRef({ smoke: 0, dust: 0, si: 0, di: 0 })
  const tmp = useMemo(() => ({ p: new Vector3(), t: new Vector3(), off: new Vector3() }), [])

  useFrame((state, dtRaw) => {
    const dt = Math.min(dtRaw, 0.05)
    const g = group.current
    if (!g) return
    u.current = (u.current + (SPEED * dt) / length) % 1
    ROAD_LOOP.getPointAt(u.current, tmp.p)
    ROAD_LOOP.getTangentAt(u.current, tmp.t)
    const heading = Math.atan2(tmp.t.x, tmp.t.z)
    g.position.set(tmp.p.x, heightAt(tmp.p.x, tmp.p.z), tmp.p.z)
    g.rotation.y = heading
    tractorState.position.copy(g.position)
    tractorState.heading = heading
    const t = state.clock.elapsedTime
    if (body.current) {
      body.current.position.y = Math.sin(t * 11) * 0.012 + Math.sin(t * 5.3) * 0.008
      body.current.rotation.z = Math.sin(t * 7.1) * 0.006
    }

    // exhaust (local → world)
    const s = spawn.current
    s.smoke += dt
    if (s.smoke > 0.12) {
      s.smoke = 0
      const p = smokeParts[s.si++ % smokeParts.length]
      tmp.off.set(0.32, 2.25, 0.95).applyAxisAngle(new Vector3(0, 1, 0), heading)
      p.p.copy(g.position).add(tmp.off)
      p.v.set(0.35 + Math.random() * 0.2, 0.9 + Math.random() * 0.4, -0.15 + Math.random() * 0.3)
      p.age = 0
      p.life = 2.2 + Math.random()
      p.size = 0.22
    }
    s.dust += dt
    if (s.dust > 0.07) {
      s.dust = 0
      const p = dustParts[s.di++ % dustParts.length]
      const side = Math.random() < 0.5 ? -1 : 1
      tmp.off.set(side * 0.9, 0.25, -1.3).applyAxisAngle(new Vector3(0, 1, 0), heading)
      p.p.copy(g.position).add(tmp.off)
      p.v.set((Math.random() - 0.5) * 0.5, 0.25 + Math.random() * 0.3, (Math.random() - 0.5) * 0.5)
      p.age = 0
      p.life = 1.6 + Math.random() * 0.8
      p.size = 0.35
    }
    const write = (grp: Group | null, list: Particle[], grow: number) => {
      const pts = grp?.children[0] as Points | undefined
      if (!pts) return
      const pos = pts.geometry.attributes.position as BufferAttribute
      const life = pts.geometry.attributes.aLife as BufferAttribute
      const size = pts.geometry.attributes.aSize as BufferAttribute
      list.forEach((p, i) => {
        p.age += dt
        const k = p.age / p.life
        p.p.addScaledVector(p.v, dt)
        p.v.multiplyScalar(1 - dt * 0.6)
        p.v.x += dt * 0.25
        pos.setXYZ(i, p.p.x, p.p.y, p.p.z)
        life.setX(i, k < 1 ? k : 0)
        size.setX(i, p.size * (1 + k * grow))
      })
      pos.needsUpdate = life.needsUpdate = size.needsUpdate = true
    }
    write(smoke.current, smokeParts, 5)
    write(dust.current, dustParts, 3)
  })

  return (
    <>
      <group ref={group}>
        <group ref={body}>
          <primitive object={scene} scale={SCALE} rotation={[0, MODEL_YAW, 0]} />
        </group>
      </group>
      <group ref={smoke}>
        <Puffs count={26} color="#cfc8bd" blending={NormalBlending} opacity={0.38} />
      </group>
      <group ref={dust}>
        <Puffs count={40} color="#b39b78" blending={NormalBlending} opacity={0.32} />
      </group>
    </>
  )
}

useGLTF.preload(URL)
