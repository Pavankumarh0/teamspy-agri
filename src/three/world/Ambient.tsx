import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  DoubleSide,
  InstancedBufferAttribute,
  InstancedMesh,
  MeshLambertMaterial,
  MeshStandardMaterial,
  Object3D,
  Points,
  ShaderMaterial,
  Vector3,
} from 'three'
import CustomShaderMaterial from 'three-custom-shader-material/vanilla'
import { mulberry32 } from '../../lib/noise'
import { createBirdGeometry, createButterflyGeometry } from '../geometry'
import { globalUniforms } from '../uniforms'

/* ------------------------------------------------------------------ birds */

type Flock = { count: number; center: Vector3; rx: number; rz: number; h: number; speed: number; spread: number; phase: number }

export function Birds({ count }: { count: number }) {
  const ref = useRef<InstancedMesh>(null)
  const flocks = useMemo<Flock[]>(() => {
    const big = Math.round(count * 0.65)
    return [
      { count: big, center: new Vector3(-8, 0, -48), rx: 58, rz: 34, h: 30, speed: 0.11, spread: 9, phase: 0 },
      { count: count - big, center: new Vector3(-3, 0, -30), rx: 26, rz: 18, h: 12, speed: 0.24, spread: 4, phase: 2 },
    ]
  }, [count])

  const birds = useMemo(() => {
    const rand = mulberry32(31)
    const out: { flock: number; off: Vector3; lag: number; scale: number }[] = []
    flocks.forEach((f, fi) => {
      for (let i = 0; i < f.count; i++) {
        out.push({
          flock: fi,
          off: new Vector3((rand() - 0.5) * 2, (rand() - 0.5) * 0.6, (rand() - 0.5) * 2).multiplyScalar(f.spread),
          lag: rand() * 0.25,
          scale: 0.9 + rand() * 0.45,
        })
      }
    })
    return out
  }, [flocks])

  const geometry = useMemo(() => {
    const g = createBirdGeometry()
    const phase = new Float32Array(birds.length)
    const rand = mulberry32(5)
    for (let i = 0; i < birds.length; i++) phase[i] = rand()
    g.setAttribute('aPhase', new InstancedBufferAttribute(phase, 1))
    return g
  }, [birds])

  const material = useMemo(
    () =>
      new CustomShaderMaterial({
        baseMaterial: MeshLambertMaterial,
        color: new Color('#1d1f22'),
        side: DoubleSide,
        uniforms: globalUniforms,
        vertexShader: /* glsl */ `
          attribute float aWing;
          attribute float aPhase;
          uniform float uTime;
          void main() {
            vec3 p = position;
            float span = abs(aWing);
            float flap = sin(uTime * (8.5 + aPhase * 3.0) + aPhase * 6.2831);
            float glide = smoothstep(0.35, 0.8, sin(uTime * 0.45 + aPhase * 12.0));
            float ang = mix(flap * 0.8, 0.1, glide);
            if (span > 0.0) {
              float x = p.x;
              p.x = x * cos(ang * span * 1.4);
              p.y += abs(x) * sin(ang * (0.7 + span * 0.6));
            }
            csm_Position = p;
          }
        `,
      }),
    [],
  )

  const o = useMemo(() => new Object3D(), [])
  const tmp = useMemo(() => ({ a: new Vector3(), b: new Vector3() }), [])
  const pathAt = (f: Flock, t: number, out: Vector3) => {
    const w = t * f.speed + f.phase
    return out.set(f.center.x + Math.sin(w) * f.rx, f.h + Math.sin(w * 0.7) * 3, f.center.z + Math.sin(w * 2) * f.rz)
  }

  useFrame((state) => {
    const mesh = ref.current
    if (!mesh) return
    const t = state.clock.elapsedTime
    birds.forEach((b, i) => {
      const f = flocks[b.flock]
      const tt = t - b.lag * 4
      pathAt(f, tt, tmp.a)
      pathAt(f, tt + 0.25, tmp.b)
      const wob = Math.sin(t * 0.6 + i) * 0.6
      o.position.copy(tmp.a).add(b.off)
      o.position.y += wob
      const dx = tmp.b.x - tmp.a.x
      const dz = tmp.b.z - tmp.a.z
      const dy = tmp.b.y - tmp.a.y
      const yaw = Math.atan2(dx, dz)
      // bank into turns using the path's curvature
      pathAt(f, tt + 0.5, tmp.b.set(0, 0, 0))
      const yaw2 = Math.atan2(tmp.b.x - (tmp.a.x + dx), tmp.b.z - (tmp.a.z + dz))
      let turn = yaw2 - yaw
      if (turn > Math.PI) turn -= Math.PI * 2
      if (turn < -Math.PI) turn += Math.PI * 2
      o.rotation.set(-Math.atan2(dy, Math.hypot(dx, dz)), yaw, -turn * 6, 'YXZ')
      o.scale.setScalar(b.scale)
      o.updateMatrix()
      mesh.setMatrixAt(i, o.matrix)
    })
    mesh.instanceMatrix.needsUpdate = true
  })

  return <instancedMesh ref={ref} args={[geometry, material, birds.length]} frustumCulled={false} />
}

/* ------------------------------------------------------------- butterflies */

const BUTTERFLY_COLORS = ['#e8862a', '#f5f1e4', '#f1d24a', '#e8862a', '#9fb8e6', '#f5f1e4', '#e8862a', '#f1d24a']

export function Butterflies({ count = 8 }: { count?: number }) {
  const ref = useRef<InstancedMesh>(null)
  const data = useMemo(() => {
    const rand = mulberry32(808)
    return Array.from({ length: count }, (_, i) => ({
      anchor: new Vector3(-4 + rand() * 10, 0.6 + rand() * 0.8, -6 + rand() * 9),
      f: [0.3 + rand() * 0.4, 0.25 + rand() * 0.35, 0.4 + rand() * 0.4],
      ph: rand() * 10,
      r: 1.5 + rand() * 2.5,
      color: new Color(BUTTERFLY_COLORS[i % BUTTERFLY_COLORS.length]),
    }))
  }, [count])

  const geometry = useMemo(() => {
    const g = createButterflyGeometry()
    const ph = new Float32Array(count)
    const tint = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      ph[i] = i / count
      const c = data[i].color
      tint.set([c.r, c.g, c.b], i * 3)
    }
    g.setAttribute('aPhase', new InstancedBufferAttribute(ph, 1))
    g.setAttribute('aTint', new InstancedBufferAttribute(tint, 3))
    return g
  }, [count, data])

  const material = useMemo(
    () =>
      new CustomShaderMaterial({
        baseMaterial: MeshStandardMaterial,
        side: DoubleSide,
        roughness: 0.6,
        uniforms: globalUniforms,
        vertexShader: /* glsl */ `
          attribute float aWing;
          attribute float aPhase;
          attribute vec3 aTint;
          uniform float uTime;
          varying vec2 vUv2;
          varying vec3 vTint;
          void main() {
            vUv2 = uv;
            vTint = aTint;
            vec3 p = position;
            float a = (sin(uTime * 16.0 + aPhase * 30.0) * 0.5 + 0.5) * 1.25;
            float x = p.x;
            p.x = x * cos(a);
            p.y = abs(x) * sin(a);
            csm_Position = p;
          }
        `,
        fragmentShader: /* glsl */ `
          varying vec2 vUv2;
          varying vec3 vTint;
          void main() {
            vec2 q = vUv2;
            float edge = smoothstep(0.72, 0.9, q.x);
            float spot = smoothstep(0.12, 0.06, distance(q, vec2(0.78, 0.7)));
            vec3 c = vTint;
            c = mix(c, vec3(0.04), edge * 0.85);
            c = mix(c, vec3(0.95), spot);
            float vein = smoothstep(0.03, 0.0, abs(fract(q.y * 4.0 + q.x) - 0.5) - 0.46);
            c *= 1.0 - vein * 0.4;
            csm_DiffuseColor = vec4(c, 1.0);
          }
        `,
      }),
    [],
  )

  const o = useMemo(() => new Object3D(), [])
  const prev = useMemo(() => data.map((d) => d.anchor.clone()), [data])
  useFrame((state) => {
    const m = ref.current
    if (!m) return
    const t = state.clock.elapsedTime
    data.forEach((d, i) => {
      const x = d.anchor.x + Math.sin(t * d.f[0] + d.ph) * d.r + Math.sin(t * 1.7 + d.ph) * 0.25
      const y = d.anchor.y + Math.sin(t * d.f[1] * 2.3 + d.ph) * 0.35 + Math.sin(t * 5.1 + d.ph) * 0.06
      const z = d.anchor.z + Math.cos(t * d.f[2] + d.ph * 1.3) * d.r * 0.7
      const p = prev[i]
      const yaw = Math.atan2(x - p.x, z - p.z)
      p.set(x, y, z)
      o.position.set(x, y, z)
      o.rotation.set(0.25, yaw, 0)
      o.scale.setScalar(0.4)
      o.updateMatrix()
      m.setMatrixAt(i, o.matrix)
    })
    m.instanceMatrix.needsUpdate = true
  })

  return <instancedMesh ref={ref} args={[geometry, material, count]} frustumCulled={false} castShadow />
}

/* ------------------------------------------------------------------ pollen */

/** Sun-lit pollen motes in a box that wraps around the camera, so they are always present. */
export function Pollen({ count }: { count: number }) {
  const ref = useRef<Points>(null)
  const dpr = useThree((s) => s.viewport.dpr)
  const geometry = useMemo(() => {
    const rand = mulberry32(64)
    const pos = new Float32Array(count * 3)
    const seed = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      pos[i * 3] = rand() * 26
      pos[i * 3 + 1] = rand() * 9
      pos[i * 3 + 2] = rand() * 26
      seed[i * 3] = rand()
      seed[i * 3 + 1] = rand()
      seed[i * 3 + 2] = rand()
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(pos, 3))
    g.setAttribute('aSeed', new BufferAttribute(seed, 3))
    return g
  }, [count])

  const material = useMemo(
    () =>
      new ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        uniforms: { uTime: globalUniforms.uTime, uCam: { value: new Vector3() }, uDpr: { value: dpr } },
        vertexShader: /* glsl */ `
          attribute vec3 aSeed;
          uniform float uTime;
          uniform vec3 uCam;
          uniform float uDpr;
          varying float vA;
          void main() {
            vec3 box = vec3(26.0, 9.0, 26.0);
            vec3 drift = vec3(uTime * 0.32, uTime * 0.05 + sin(uTime * 0.4 + aSeed.x * 6.28) * 0.4, -uTime * 0.12);
            vec3 p = position + drift;
            p.x += sin(uTime * 0.7 + aSeed.y * 12.0) * 0.3;
            p = mod(p - uCam + box * 0.5, box) - box * 0.5 + uCam;
            vec4 mv = viewMatrix * vec4(p, 1.0);
            gl_Position = projectionMatrix * mv;
            float tw = 0.55 + 0.45 * sin(uTime * (1.5 + aSeed.z * 2.0) + aSeed.y * 20.0);
            float d = -mv.z;
            vA = tw * smoothstep(1.6, 4.0, d) * (1.0 - smoothstep(9.0, 13.0, d));
            gl_PointSize = min((2.0 + aSeed.z * 3.5) * uDpr * (9.0 / max(d, 0.5)), 9.0 * uDpr);
          }
        `,
        fragmentShader: /* glsl */ `
          varying float vA;
          void main() {
            float d = length(gl_PointCoord - 0.5);
            float a = smoothstep(0.5, 0.0, d);
            gl_FragColor = vec4(vec3(1.0, 0.86, 0.58) * 1.8, a * vA * 0.6);
          }
        `,
      }),
    [dpr],
  )

  useFrame(({ camera }) => {
    material.uniforms.uCam.value.copy(camera.position)
  })

  return <points ref={ref} geometry={geometry} material={material} frustumCulled={false} />
}
