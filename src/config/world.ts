import { CatmullRomCurve3, Vector3 } from 'three'

/**
 * World layout (metres). +X = east, -Z = north (away from the hero camera), Y up.
 * Every scene component reads positions from here so the terrain shader, the
 * instanced vegetation and the characters always agree with each other.
 */

/** Late-afternoon sun, behind-right of the hero shot (rim-lights the farmer). */
export const SUN_DIR = new Vector3(0.55, 0.26, -0.8).normalize()

export type Rect = { cx: number; cz: number; hw: number; hd: number; rot: number }

export const FARMER_POS = new Vector3(0, 0, 0)

/** Golden wheat field, west of the farm road. */
export const WHEAT: Rect = { cx: -29, cz: -30, hw: 15, hd: 19, rot: 0.05 }

/** Ploughed field with green crop rows, north of the farm road. */
export const CROPS: Rect = { cx: -6, cz: -64, hw: 26, hd: 15, rot: 0 }
export const CROP_ROW_SPACING = 1.5

/** Fenced pasture the cows graze in (the tractor loops around it). */
export const PASTURE: Rect = { cx: 3.5, cz: -24, hw: 9.5, hd: 11, rot: 0 }

export const BARN = { x: 30, z: -55, rot: -0.35 }
export const SILO = { x: 38.5, z: -50, rot: 0 }
export const WINDMILL = { x: -40, z: -112, rot: 0.45 }

export const ROAD_WIDTH = 3.6

const v = (x: number, z: number) => new Vector3(x, 0, z)

/** The tractor's loop road around the pasture. */
export const ROAD_LOOP = new CatmullRomCurve3(
  [v(-9, -8), v(-9.5, -24), v(-9, -40), v(2, -42.5), v(16, -40), v(17, -24), v(16, -8), v(4, -6.5)],
  true,
  'centripetal',
)

/** Open-ended roads (a lane toward the viewer and a spur to the barn). */
export const ROAD_SPURS = [
  new CatmullRomCurve3([v(-9, -8), v(-11, 10), v(-15, 30), v(-22, 60)], false, 'centripetal'),
  new CatmullRomCurve3([v(16, -40), v(22, -44), v(29, -48)], false, 'centripetal'),
]

/** Flattened segment list (ax, az, bx, bz) consumed by the terrain shader. */
export const ROAD_SEGMENTS: number[][] = (() => {
  const segs: number[][] = []
  const push = (curve: CatmullRomCurve3, n: number) => {
    const pts = curve.getSpacedPoints(n)
    for (let i = 0; i < pts.length - 1; i++) segs.push([pts[i].x, pts[i].z, pts[i + 1].x, pts[i + 1].z])
  }
  push(ROAD_LOOP, 30)
  push(ROAD_SPURS[0], 8)
  push(ROAD_SPURS[1], 4)
  return segs
})()

export function toLocal(r: Rect, x: number, z: number): [number, number] {
  const dx = x - r.cx
  const dz = z - r.cz
  const c = Math.cos(r.rot)
  const s = Math.sin(r.rot)
  return [c * dx - s * dz, s * dx + c * dz]
}

export function fromLocal(r: Rect, lx: number, lz: number): [number, number] {
  const c = Math.cos(r.rot)
  const s = Math.sin(r.rot)
  return [r.cx + c * lx + s * lz, r.cz - s * lx + c * lz]
}

export function inRect(r: Rect, x: number, z: number, pad = 0) {
  const [lx, lz] = toLocal(r, x, z)
  return Math.abs(lx) < r.hw + pad && Math.abs(lz) < r.hd + pad
}

function distToSegment(px: number, pz: number, s: number[]) {
  const [ax, az, bx, bz] = s
  const abx = bx - ax
  const abz = bz - az
  const t = Math.max(0, Math.min(1, ((px - ax) * abx + (pz - az) * abz) / (abx * abx + abz * abz)))
  const dx = px - (ax + abx * t)
  const dz = pz - (az + abz * t)
  return Math.sqrt(dx * dx + dz * dz)
}

export function roadDistance(x: number, z: number) {
  let d = Infinity
  for (const s of ROAD_SEGMENTS) d = Math.min(d, distToSegment(x, z, s))
  return d
}

/** Footprints vegetation must avoid (buildings etc). */
const BLOCKERS = [
  { x: BARN.x, z: BARN.z, r: 7 },
  { x: SILO.x, z: SILO.z, r: 3 },
  { x: WINDMILL.x, z: WINDMILL.z, r: 6 },
]

export function isBlocked(x: number, z: number) {
  return BLOCKERS.some((b) => (x - b.x) ** 2 + (z - b.z) ** 2 < b.r * b.r)
}

/** Hand-placed hero trees (type index into the tree pack, scale, yaw). */
export const HERO_TREES: { x: number; z: number; t: number; s: number; r: number }[] = [
  { x: 6.5, z: -31, t: 0, s: 1.35, r: 0.4 }, // shade tree in the pasture
  { x: -16, z: 6, t: 1, s: 1.2, r: 1.2 },
  { x: -19, z: -4, t: 3, s: 1.05, r: 2.1 },
  { x: 13, z: 4, t: 2, s: 1.15, r: 0.2 },
  { x: 22, z: -10, t: 0, s: 1.3, r: 2.8 },
  { x: 24, z: -26, t: 4, s: 1.6, r: 1.7 },
  { x: 33, z: -40, t: 1, s: 1.3, r: 0.9 },
  { x: 23, z: -67, t: 3, s: 1.2, r: 0.5 },
  { x: 36, z: -62, t: 0, s: 1.4, r: 2.2 },
  { x: -47, z: -14, t: 2, s: 1.3, r: 1.1 },
  { x: -49, z: -30, t: 0, s: 1.25, r: 0.3 },
  { x: -48, z: -46, t: 1, s: 1.4, r: 2.6 },
  { x: -36, z: -54, t: 3, s: 1.1, r: 1.4 },
  { x: -25, z: -6.5, t: 4, s: 1.5, r: 0.7 },
  { x: -36, z: -98, t: 0, s: 1.3, r: 2.0 },
  { x: -46, z: -104, t: 2, s: 1.2, r: 0.8 },
  { x: 8, z: -84, t: 1, s: 1.3, r: 1.9 },
  { x: 26, z: -80, t: 0, s: 1.5, r: 0.1 },
  { x: -34, z: -84, t: 3, s: 1.3, r: 2.4 },
  { x: 40, z: -24, t: 2, s: 1.2, r: 1.0 },
]

/** Camera beats, one per page section. pos / target pairs. */
export type Shot = { pos: [number, number, number]; target: [number, number, number] }

/**
 * The scroll journey only ever moves forward (toward -Z): from the lane, past the
 * farmer, into the wheat, along the pasture, over the crop rows, up above the
 * valley and on toward the mountains — so scrolling feels like walking in.
 */
export const SHOTS_LANDSCAPE: Shot[] = [
  { pos: [1.1, 1.5, 6.2], target: [-1.3, 1.25, -0.5] }, // hero — the farmer
  { pos: [-11, 1.65, -9.5], target: [-27, 0.5, -29] }, // fields — into the wheat
  { pos: [-11, 3.0, -21], target: [5, 0.7, -25] }, // livestock — over the fence
  { pos: [1, 9.5, -38], target: [-9, 2, -70] }, // technology — above the crop rows
  { pos: [-6, 21, -66], target: [-40, 9, -152] }, // impact — rising over the valley
  { pos: [-4, 20, -112], target: [70, 16, -300] }, // contact — on toward the sun
]

export const SHOTS_PORTRAIT: Shot[] = [
  { pos: [0.5, 1.9, 8.6], target: [-0.2, 0.2, -0.5] },
  { pos: [-10.5, 2.0, -6.5], target: [-26, 0.4, -30] },
  { pos: [-12, 3.6, -18], target: [4, 0.7, -25] },
  { pos: [2, 12, -33], target: [-10, 0, -64] },
  { pos: [-4, 25, -60], target: [-40, 9, -152] },
  { pos: [-4, 24, -106], target: [60, 18, -300] },
]

/** Where the camera starts before the intro fly-in: above the lane, outside the farm. */
export const INTRO_SHOT: Shot = { pos: [-14, 24, 72], target: [-5, 3, -24] }

/**
 * Ground point under a screen position of a landscape shot (16:10, fov 38).
 * Used to pin in-world cards beside — never behind — the section copy.
 */
export function groundUnderShot(shot: Shot, ndcX: number, ndcY: number, fov = 38, aspect = 1.6): [number, number] {
  const p = new Vector3(...shot.pos)
  const f = new Vector3(...shot.target).sub(p).normalize()
  const r = new Vector3().crossVectors(f, new Vector3(0, 1, 0)).normalize()
  const u = new Vector3().crossVectors(r, f)
  const th = Math.tan((fov * Math.PI) / 360)
  const dir = f.clone().addScaledVector(r, ndcX * th * aspect).addScaledVector(u, ndcY * th).normalize()
  const t = dir.y < -1e-3 ? -p.y / dir.y : 60
  return [p.x + dir.x * t, p.z + dir.z * t]
}
