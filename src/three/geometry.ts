import {
  BufferAttribute,
  BufferGeometry,
  Float32BufferAttribute,
  IcosahedronGeometry,
  CylinderGeometry,
  ConeGeometry,
  Color,
} from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'

/** Adds reversed copies of every triangle so thin cards render from both sides with FrontSide culling. */
function doubleWound(indices: number[]) {
  const out = indices.slice()
  for (let i = 0; i < indices.length; i += 3) out.push(indices[i], indices[i + 2], indices[i + 1])
  return out
}

/** Grass blade, y in 0..1, tapered, slight forward curl. uv.y = height along blade. */
export function createBladeGeometry(segments = 4) {
  const pos: number[] = []
  const uv: number[] = []
  const nrm: number[] = []
  const idx: number[] = []
  for (let i = 0; i < segments; i++) {
    const t = i / segments
    const w = 0.5 * Math.pow(1 - t, 0.75)
    const z = t * t * 0.18
    pos.push(-w, t, z, w, t, z)
    uv.push(0, t, 1, t)
    nrm.push(0, 1, 0, 0, 1, 0)
  }
  pos.push(0, 1, 0.18)
  uv.push(0.5, 1)
  nrm.push(0, 1, 0)
  for (let i = 0; i < segments - 1; i++) {
    const a = i * 2
    idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2)
  }
  const last = (segments - 1) * 2
  idx.push(last, last + 1, segments * 2)
  const g = new BufferGeometry()
  g.setAttribute('position', new Float32BufferAttribute(pos, 3))
  g.setAttribute('uv', new Float32BufferAttribute(uv, 2))
  g.setAttribute('normal', new Float32BufferAttribute(nrm, 3))
  g.setIndex(idx)
  return g
}

/**
 * A clump of three wheat stalks with ears. Attribute `aPart`: 0 = stalk, 1 = ear, 2 = awns.
 * uv.y runs 0..1 along the whole plant height so wind bending is continuous.
 */
export function createWheatGeometry() {
  const pos: number[] = []
  const uv: number[] = []
  const part: number[] = []
  const nrm: number[] = []
  const idx: number[] = []
  let base = 0

  const stalks: [number, number, number, number][] = [
    // x, z, height, lean
    [0, 0, 1.0, 0.0],
    [0.09, 0.06, 0.92, 0.05],
    [-0.07, 0.08, 0.86, -0.04],
  ]
  for (const [sx, sz, h, lean] of stalks) {
    const segs = 3
    const earStart = 0.78
    // stalk ribbon (two crossed ribbons would double cost; one ribbon + ear cards is enough)
    for (let i = 0; i <= segs; i++) {
      const t = (i / segs) * earStart
      const w = 0.012
      pos.push(sx - w, t * h, sz + lean * t, sx + w, t * h, sz + lean * t)
      uv.push(0, t, 1, t)
      part.push(0, 0)
      nrm.push(0, 1, 0, 0, 1, 0)
    }
    for (let i = 0; i < segs; i++) {
      const a = base + i * 2
      idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2)
    }
    base += (segs + 1) * 2

    // ear: two crossed cards with a procedural spindle silhouette
    const y0 = earStart * h
    const y1 = h * 1.02
    const ew = 0.045
    const lz = sz + lean * earStart
    for (const [dx, dz] of [
      [ew, 0],
      [0, ew],
    ]) {
      pos.push(sx - dx, y0, lz - dz, sx + dx, y0, lz + dz, sx - dx, y1, lz - dz + lean * 0.2, sx + dx, y1, lz + dz + lean * 0.2)
      uv.push(0, earStart, 1, earStart, 0, 1, 1, 1)
      part.push(1, 1, 1, 1)
      nrm.push(0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0)
      idx.push(base, base + 1, base + 2, base + 1, base + 3, base + 2)
      base += 4
    }
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new Float32BufferAttribute(pos, 3))
  g.setAttribute('uv', new Float32BufferAttribute(uv, 2))
  g.setAttribute('normal', new Float32BufferAttribute(nrm, 3))
  g.setAttribute('aPart', new Float32BufferAttribute(part, 1))
  g.setIndex(idx)
  return g
}

/** Wildflower: short stem + crossed head cards (petal shape is procedural in the shader). */
export function createFlowerGeometry() {
  const pos: number[] = []
  const uv: number[] = []
  const part: number[] = []
  const nrm: number[] = []
  const idx: number[] = []
  const w = 0.008
  pos.push(-w, 0, 0, w, 0, 0, -w, 0.82, 0, w, 0.82, 0)
  uv.push(0, 0, 1, 0, 0, 0.82, 1, 0.82)
  part.push(0, 0, 0, 0)
  nrm.push(0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0)
  idx.push(0, 1, 2, 1, 3, 2)
  // head: horizontal card + tilted card
  const s = 0.11
  const y = 0.85
  pos.push(-s, y, -s, s, y, -s, -s, y, s, s, y, s)
  uv.push(0, 0, 1, 0, 0, 1, 1, 1)
  part.push(1, 1, 1, 1)
  nrm.push(0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0)
  idx.push(4, 6, 5, 5, 6, 7)
  pos.push(-s, y - s * 0.9, 0.02, s, y - s * 0.9, 0.02, -s, y + s * 0.9, 0.06, s, y + s * 0.9, 0.06)
  uv.push(0, 0, 1, 0, 0, 1, 1, 1)
  part.push(1, 1, 1, 1)
  nrm.push(0, 0.6, 0.8, 0, 0.6, 0.8, 0, 0.6, 0.8, 0, 0.6, 0.8)
  idx.push(8, 9, 10, 9, 11, 10)
  const g = new BufferGeometry()
  g.setAttribute('position', new Float32BufferAttribute(pos, 3))
  g.setAttribute('uv', new Float32BufferAttribute(uv, 2))
  g.setAttribute('normal', new Float32BufferAttribute(nrm, 3))
  g.setAttribute('aPart', new Float32BufferAttribute(part, 1))
  g.setIndex(idx)
  return g
}

/** Young leafy crop plant (think lettuce / soy): a rosette of curved leaves. */
export function createCropGeometry(leaves = 6) {
  const pos: number[] = []
  const uv: number[] = []
  const nrm: number[] = []
  const idx: number[] = []
  let base = 0
  for (let l = 0; l < leaves; l++) {
    const a = (l / leaves) * Math.PI * 2 + (l % 2) * 0.4
    const len = 0.34 + (l % 3) * 0.06
    const up = 0.22 + (l % 2) * 0.1
    const ca = Math.cos(a)
    const sa = Math.sin(a)
    // 3 rows x 3 cols leaf patch, bowed upward
    for (let i = 0; i <= 2; i++) {
      const t = i / 2
      const r = len * t
      const y = up * Math.sin(t * Math.PI * 0.85) + 0.02
      const w = 0.11 * Math.sin(Math.PI * Math.min(1, t * 1.1 + 0.05))
      for (let j = -1; j <= 1; j++) {
        const px = ca * r - sa * w * j
        const pz = sa * r + ca * w * j
        pos.push(px, y + Math.abs(j) * -0.02, pz)
        uv.push((j + 1) / 2, t)
        nrm.push(0, 1, 0)
      }
    }
    for (let i = 0; i < 2; i++) {
      for (let j = 0; j < 2; j++) {
        const q = base + i * 3 + j
        idx.push(q, q + 3, q + 1, q + 1, q + 3, q + 4)
      }
    }
    base += 9
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new Float32BufferAttribute(pos, 3))
  g.setAttribute('uv', new Float32BufferAttribute(uv, 2))
  g.setAttribute('normal', new Float32BufferAttribute(nrm, 3))
  g.setIndex(idx)
  return g
}

/**
 * Low-poly bird silhouette, nose along +Z. Attribute `aWing`: 0 = body,
 * ±span (0..1) for wing vertices so the shader can flap them.
 */
export function createBirdGeometry() {
  // body (diamond), wings (two segments each side), tail
  const P: number[] = []
  const W: number[] = []
  const I: number[] = []
  const add = (x: number, y: number, z: number, w: number) => {
    P.push(x, y, z)
    W.push(w)
    return P.length / 3 - 1
  }
  const nose = add(0, 0, 0.42, 0)
  const back = add(0, 0.05, 0, 0)
  const belly = add(0, -0.05, 0, 0)
  const tailL = add(-0.09, 0, -0.42, 0)
  const tailR = add(0.09, 0, -0.42, 0)
  const tailC = add(0, 0.01, -0.2, 0)
  I.push(nose, back, tailC, nose, tailC, belly, back, tailL, tailC, back, tailC, tailR)
  for (const side of [-1, 1]) {
    const root0 = add(0.04 * side, 0.02, 0.14, 0)
    const root1 = add(0.04 * side, 0.02, -0.08, 0)
    const mid0 = add(0.38 * side, 0.03, 0.1, 0.5 * side)
    const mid1 = add(0.38 * side, 0.03, -0.1, 0.5 * side)
    const tip = add(0.72 * side, 0.02, -0.12, 1.0 * side)
    I.push(root0, mid0, root1, root1, mid0, mid1, mid0, tip, mid1)
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new Float32BufferAttribute(P, 3))
  g.setAttribute('aWing', new Float32BufferAttribute(W, 1))
  g.setIndex(doubleWound(I))
  g.computeVertexNormals()
  return g
}

/** Butterfly: two wing quads hinged on Z. `aWing` = -1 / +1 side, uv for the wing pattern. */
export function createButterflyGeometry() {
  const pos: number[] = []
  const uv: number[] = []
  const wing: number[] = []
  const idx: number[] = []
  let b = 0
  for (const side of [-1, 1]) {
    pos.push(0, 0, 0.09, 0.2 * side, 0, 0.12, 0, 0, -0.08, 0.17 * side, 0, -0.12)
    uv.push(0, 1, 1, 1, 0, 0, 1, 0)
    wing.push(0, side, 0, side)
    idx.push(b, b + 1, b + 2, b + 1, b + 3, b + 2)
    b += 4
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new Float32BufferAttribute(pos, 3))
  g.setAttribute('uv', new Float32BufferAttribute(uv, 2))
  g.setAttribute('aWing', new Float32BufferAttribute(wing, 1))
  g.setAttribute('normal', new Float32BufferAttribute(new Array((pos.length / 3) * 3).fill(0).map((_, i) => (i % 3 === 1 ? 1 : 0)), 3))
  g.setIndex(doubleWound(idx))
  return g
}

function paint(g: BufferGeometry, color: Color, jitter = 0) {
  const n = g.attributes.position.count
  const c = new Float32Array(n * 3)
  for (let i = 0; i < n; i++) {
    const k = 1 - jitter * Math.random()
    c[i * 3] = color.r * k
    c[i * 3 + 1] = color.g * k
    c[i * 3 + 2] = color.b * k
  }
  g.setAttribute('color', new BufferAttribute(c, 3))
  return g
}

/** Cheap distant tree for forested hills (canopy + trunk, vertex coloured). Height ≈ 1. */
export function createBlobTreeGeometry(kind: 'round' | 'conifer') {
  const trunk = new CylinderGeometry(0.035, 0.05, 0.35, 5).translate(0, 0.175, 0)
  paint(trunk, new Color('#3a2a1a'))
  let crown: BufferGeometry
  if (kind === 'round') {
    crown = new IcosahedronGeometry(0.36, 1).scale(1, 1.1, 1).translate(0, 0.62, 0)
  } else {
    crown = new ConeGeometry(0.3, 0.85, 7).translate(0, 0.62, 0)
  }
  if (crown.index) crown = crown.toNonIndexed()
  paint(crown, new Color('#ffffff'), 0.25)
  const t = trunk.toNonIndexed()
  const merged = mergeGeometries([t, crown])!
  merged.computeVertexNormals()
  return merged
}

/** Copies a (possibly quantised / interleaved) geometry into plain Float32 attributes. */
export function toFloatGeometry(src: BufferGeometry) {
  const g = new BufferGeometry()
  for (const name of Object.keys(src.attributes)) {
    const a = src.getAttribute(name)
    const size = a.itemSize
    const arr = new Float32Array(a.count * size)
    for (let i = 0; i < a.count; i++) {
      arr[i * size] = a.getX(i)
      if (size > 1) arr[i * size + 1] = a.getY(i)
      if (size > 2) arr[i * size + 2] = a.getZ(i)
      if (size > 3) arr[i * size + 3] = a.getW(i)
    }
    g.setAttribute(name, new BufferAttribute(arr, size))
  }
  if (src.index) g.setIndex(src.index.clone())
  for (const grp of src.groups) g.addGroup(grp.start, grp.count, grp.materialIndex)
  return g
}
