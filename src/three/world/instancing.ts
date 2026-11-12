import { BufferGeometry, Group, InstancedBufferAttribute, InstancedBufferGeometry, Mesh, Sphere, Vector3 } from 'three'

export type InstanceRecord = { x: number; y: number; z: number; v: number[] }

/**
 * Buckets instances into square tiles, each with its own InstancedBufferGeometry
 * and a correct bounding sphere so three.js can frustum-cull tile by tile.
 * Every tile gets `aOffset` (vec3 world position) plus the named extra attributes
 * whose values are read sequentially from `record.v`.
 */
export function buildInstanceChunks(
  base: BufferGeometry,
  records: InstanceRecord[],
  extra: { name: string; size: number }[],
  tile: number,
  pad: number,
) {
  const buckets = new Map<string, InstanceRecord[]>()
  for (const r of records) {
    const key = `${Math.floor(r.x / tile)}:${Math.floor(r.z / tile)}`
    let b = buckets.get(key)
    if (!b) buckets.set(key, (b = []))
    b.push(r)
  }
  const out: InstancedBufferGeometry[] = []
  for (const list of buckets.values()) {
    const g = new InstancedBufferGeometry()
    g.index = base.index
    for (const name of Object.keys(base.attributes)) g.setAttribute(name, base.getAttribute(name))
    const off = new Float32Array(list.length * 3)
    const arrays = extra.map((e) => new Float32Array(list.length * e.size))
    let minX = Infinity, minY = Infinity, minZ = Infinity, maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
    list.forEach((r, i) => {
      off[i * 3] = r.x
      off[i * 3 + 1] = r.y
      off[i * 3 + 2] = r.z
      let k = 0
      extra.forEach((e, ei) => {
        for (let c = 0; c < e.size; c++) arrays[ei][i * e.size + c] = r.v[k++]
      })
      minX = Math.min(minX, r.x); maxX = Math.max(maxX, r.x)
      minY = Math.min(minY, r.y); maxY = Math.max(maxY, r.y)
      minZ = Math.min(minZ, r.z); maxZ = Math.max(maxZ, r.z)
    })
    g.setAttribute('aOffset', new InstancedBufferAttribute(off, 3))
    extra.forEach((e, ei) => g.setAttribute(e.name, new InstancedBufferAttribute(arrays[ei], e.size)))
    g.instanceCount = list.length
    const center = new Vector3((minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2)
    const radius = Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2 + pad
    g.boundingSphere = new Sphere(center, radius)
    out.push(g)
  }
  return out
}

/** Hides tiles whose bounding sphere is further than `maxDist` from the camera. */
export function cullTilesByDistance(group: Group | null, camera: { position: Vector3 }, maxDist: number) {
  if (!group) return
  for (const child of group.children) {
    const m = child as Mesh
    const bs = m.geometry?.boundingSphere
    if (!bs) continue
    m.visible = bs.center.distanceTo(camera.position) - bs.radius < maxDist
  }
}
