import { useLayoutEffect, useMemo, useRef } from 'react'
import { useGLTF } from '@react-three/drei'
import {
  Box3,
  BufferGeometry,
  Color,
  DoubleSide,
  InstancedMesh,
  Material,
  Matrix4,
  Mesh,
  MeshLambertMaterial,
  MeshStandardMaterial,
  Object3D,
  Vector3,
} from 'three'
import CustomShaderMaterial from 'three-custom-shader-material/vanilla'
import { CROPS, HERO_TREES, PASTURE, WHEAT, inRect, isBlocked, roadDistance } from '../../config/world'
import { mulberry32 } from '../../lib/noise'
import { heightAt, slopeAt } from '../../lib/terrain'
import { createBlobTreeGeometry, toFloatGeometry } from '../geometry'
import { globalUniforms } from '../uniforms'

type Part = { geometry: BufferGeometry; material: Material; leaves: boolean }
type Placement = { x: number; y: number; z: number; s: number; r: number }

const TREE_URL = '/models/trees.glb'

/** Extracts each of the five trees as centred bark + leaves geometries. */
function useTreeSpecies() {
  const { scene } = useGLTF(TREE_URL)
  return useMemo(() => {
    scene.updateMatrixWorld(true)
    const species: Part[][] = []
    for (let i = 1; i <= 5; i++) {
      const node = scene.getObjectByName(`NormalTree_${i}`)
      if (!node) continue
      const parts: Part[] = []
      const meshes: Mesh[] = []
      node.traverse((o) => {
        if ((o as Mesh).isMesh) meshes.push(o as Mesh)
      })
      const box = new Box3()
      const geos = meshes.map((m) => {
        const g = toFloatGeometry(m.geometry)
        g.applyMatrix4(m.matrixWorld)
        g.computeBoundingBox()
        box.union(g.boundingBox!)
        return g
      })
      const c = box.getCenter(new Vector3())
      geos.forEach((g, k) => {
        g.translate(-c.x, -box.min.y, -c.z)
        const src = meshes[k].material as MeshStandardMaterial
        const leaves = src.alphaTest > 0 || src.transparent
        parts.push({ geometry: g, material: src, leaves })
      })
      species.push(parts)
    }
    return species
  }, [scene])
}

function makeLeafMaterial(src: MeshStandardMaterial) {
  return new CustomShaderMaterial({
    baseMaterial: MeshStandardMaterial,
    map: src.map,
    color: new Color('#a7ba78'),
    alphaTest: 0.45,
    side: DoubleSide,
    roughness: 0.8,
    uniforms: globalUniforms,
    vertexShader: /* glsl */ `
      uniform float uTime;
      uniform float uWind;
      varying float vLeafH;
      varying float vTreeHash;
      void main() {
        vec3 ip = instanceMatrix[3].xyz;
        vTreeHash = fract(sin(dot(ip.xz, vec2(12.9898, 78.233))) * 43758.5453);
        float h = max(position.y - 1.6, 0.0);
        vLeafH = position.y;
        vec3 p = position;
        float w = uWind * (0.03 + 0.012 * sin(uTime * 0.7 + ip.x));
        p.x += sin(uTime * 1.4 + ip.x * 0.3 + position.y * 0.6) * w * h;
        p.z += cos(uTime * 1.15 + ip.z * 0.3 + position.x * 0.6) * w * h;
        csm_Position = p;
      }
    `,
    fragmentShader: /* glsl */ `
      varying float vLeafH;
      varying float vTreeHash;
      void main() {
        vec3 c = csm_DiffuseColor.rgb * mix(0.5, 1.05, smoothstep(1.5, 6.5, vLeafH));
        // each tree gets its own shade, from fresh spring green to deep summer olive
        c *= mix(vec3(0.82, 0.9, 0.72), vec3(1.05, 1.0, 0.86), vTreeHash);
        csm_DiffuseColor.rgb = c;
      }
    `,
  })
}

function InstancedSpecies({ parts, placements, shadows }: { parts: Part[]; placements: Placement[]; shadows: boolean }) {
  const refs = useRef<(InstancedMesh | null)[]>([])
  const materials = useMemo(
    () =>
      parts.map((p) => {
        if (p.leaves) return makeLeafMaterial(p.material as MeshStandardMaterial)
        const m = (p.material as MeshStandardMaterial).clone()
        m.roughness = 0.95
        return m
      }),
    [parts],
  )

  useLayoutEffect(() => {
    const o = new Object3D()
    refs.current.forEach((mesh) => {
      if (!mesh) return
      placements.forEach((p, i) => {
        o.position.set(p.x, p.y - 0.1, p.z)
        o.rotation.set(0, p.r, 0)
        o.scale.setScalar(p.s)
        o.updateMatrix()
        mesh.setMatrixAt(i, o.matrix)
      })
      mesh.instanceMatrix.needsUpdate = true
      mesh.computeBoundingSphere()
    })
  }, [placements])

  if (!placements.length) return null
  return (
    <>
      {parts.map((p, k) => (
        <instancedMesh
          key={k}
          ref={(m) => {
            refs.current[k] = m
          }}
          args={[p.geometry, materials[k], placements.length]}
          castShadow={shadows}
          receiveShadow
        />
      ))}
    </>
  )
}

/** Scatter for the mid-distance tree belts around the farm. */
function belts(fraction: number) {
  const rand = mulberry32(2024)
  const out: { t: number; p: Placement }[] = []
  const tries = Math.floor(900 * fraction)
  for (let i = 0; i < tries && out.length < 64 * fraction; i++) {
    const a = rand() * Math.PI * 2
    const r = 58 + rand() * 70
    const x = -4 + Math.cos(a) * r
    const z = -34 + Math.sin(a) * r * 0.9
    if (z > -4 && Math.abs(x + 2) < 46) continue // keep the hero + panorama foregrounds open
    if (inRect(WHEAT, x, z, 4) || inRect(CROPS, x, z, 4) || inRect(PASTURE, x, z, 4) || isBlocked(x, z)) continue
    if (roadDistance(x, z) < 5) continue
    // trees grow in clumps
    const clump = Math.sin(x * 0.09) * Math.cos(z * 0.07) + Math.sin((x + z) * 0.03)
    if (clump < 0.15) continue
    // distant belts use the two lightest species (2-7k tris) — detail is lost in the haze anyway
    const t = rand() < 0.7 ? 4 : 2
    out.push({ t, p: { x, y: heightAt(x, z), z, s: (t === 4 ? 1.7 : 1.1) + rand() * 0.6, r: rand() * 6.28 } })
  }
  return out
}

export function Trees({ fraction, forest }: { fraction: number; forest: number }) {
  const species = useTreeSpecies()

  const { hero, background } = useMemo(() => {
    const hero: Placement[][] = species.map(() => [])
    const background: Placement[][] = species.map(() => [])
    for (const t of HERO_TREES) {
      hero[t.t % species.length]?.push({ x: t.x, y: heightAt(t.x, t.z), z: t.z, s: t.s, r: t.r })
    }
    for (const b of belts(fraction)) background[b.t % species.length]?.push(b.p)
    return { hero, background }
  }, [species, fraction])

  return (
    <group>
      {species.map((parts, i) => (
        <group key={i}>
          <InstancedSpecies parts={parts} placements={hero[i]} shadows />
          <InstancedSpecies parts={parts} placements={background[i]} shadows={false} />
        </group>
      ))}
      <Forest count={forest} />
    </group>
  )
}

/** Hundreds of cheap low-poly trees on the foothills; fog does the rest. */
function Forest({ count }: { count: number }) {
  const round = useRef<InstancedMesh>(null)
  const conifer = useRef<InstancedMesh>(null)
  const geos = useMemo(() => ({ round: createBlobTreeGeometry('round'), conifer: createBlobTreeGeometry('conifer') }), [])
  const material = useMemo(() => new MeshLambertMaterial({ vertexColors: true }), [])

  const placements = useMemo(() => {
    const rand = mulberry32(77)
    const r: { m: Matrix4; c: Color }[] = []
    const c: { m: Matrix4; c: Color }[] = []
    const o = new Object3D()
    const greens = [new Color('#2c4a1c'), new Color('#3a5a22'), new Color('#24401a'), new Color('#4a6a2a')]
    let guard = 0
    while (r.length + c.length < count && guard++ < count * 30) {
      const a = rand() * Math.PI * 2
      const dist = 125 + Math.pow(rand(), 0.7) * 360
      const x = -4 + Math.cos(a) * dist
      const z = -34 + Math.sin(a) * dist
      const h = heightAt(x, z)
      if (h < 3.5 || h > 95 || slopeAt(x, z) > 0.75) continue
      // forest patches
      const patch = Math.sin(x * 0.021 + 1.3) * Math.cos(z * 0.018) + Math.sin((x - z) * 0.011)
      if (patch < 0.1) continue
      const conif = h > 30 || rand() < 0.3
      const s = (conif ? 9 : 7) + rand() * 6
      o.position.set(x, h - 0.4, z)
      o.rotation.set(0, rand() * 6.28, 0)
      o.scale.set(s, s * (0.85 + rand() * 0.4), s)
      o.updateMatrix()
      const col = greens[Math.floor(rand() * greens.length)].clone()
      ;(conif ? c : r).push({ m: o.matrix.clone(), c: col })
    }
    return { r, c }
  }, [count])

  useLayoutEffect(() => {
    const apply = (mesh: InstancedMesh | null, list: { m: Matrix4; c: Color }[]) => {
      if (!mesh) return
      list.forEach((p, i) => {
        mesh.setMatrixAt(i, p.m)
        mesh.setColorAt(i, p.c)
      })
      mesh.instanceMatrix.needsUpdate = true
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
      mesh.computeBoundingSphere()
    }
    apply(round.current, placements.r)
    apply(conifer.current, placements.c)
  }, [placements])

  return (
    <>
      {placements.r.length > 0 && <instancedMesh ref={round} args={[geos.round, material, placements.r.length]} />}
      {placements.c.length > 0 && <instancedMesh ref={conifer} args={[geos.conifer, material, placements.c.length]} />}
    </>
  )
}

useGLTF.preload(TREE_URL)
