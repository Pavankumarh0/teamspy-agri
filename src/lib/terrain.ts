import { createSimplex2D, smoothstep } from './noise'
import { WINDMILL } from '../config/world'

const n1 = createSimplex2D(11)
const n2 = createSimplex2D(29)
const n3 = createSimplex2D(73)

function fbm(noise: (x: number, y: number) => number, x: number, z: number, oct: number) {
  let a = 0.5
  let f = 1
  let s = 0
  let norm = 0
  for (let i = 0; i < oct; i++) {
    s += a * noise(x * f, z * f)
    norm += a
    a *= 0.5
    f *= 2.03
  }
  return s / norm
}

function ridged(x: number, z: number, oct: number) {
  let a = 0.5
  let f = 1
  let s = 0
  let norm = 0
  let prev = 1
  for (let i = 0; i < oct; i++) {
    let n = 1 - Math.abs(n3(x * f, z * f))
    n *= n
    s += n * a * prev
    prev = n
    norm += a
    a *= 0.5
    f *= 2.1
  }
  return s / norm
}

/** Farm centre: the valley floor is flattest around here. */
const FC_X = -4
const FC_Z = -34

/**
 * Terrain height in metres. Flat-ish valley floor for the farm, rolling hills
 * further out and a ridged mountain range on the horizon.
 */
export function heightAt(x: number, z: number) {
  const r = Math.hypot(x - FC_X, z - FC_Z)

  // gentle undulation of the valley floor (kept small where crops grow)
  let h = fbm(n1, x * 0.011, z * 0.011, 3) * 2.4 + n2(x * 0.06, z * 0.06) * 0.18
  h *= 0.22 + 0.78 * smoothstep(30, 110, r)

  // rolling foothills
  h += (fbm(n2, x * 0.0055 + 7.1, z * 0.0055 - 3.3, 4) * 0.5 + 0.5) * 30 * smoothstep(90, 260, r)

  // mountain range, taller to the north (behind the hero shot)
  const north = 0.55 + 0.45 * smoothstep(0, -600, z)
  const rid = ridged(x * 0.0017 + 3.7, z * 0.0017 - 1.2, 3)
  const soft = fbm(n1, x * 0.0024 - 5.3, z * 0.0024 + 2.9, 3) * 0.5 + 0.5
  h += (rid * 0.62 + soft * 0.38) * 250 * smoothstep(330, 780, r) * north

  // the windmill's hill
  const dx = x - WINDMILL.x
  const dz = z - WINDMILL.z
  h += 7.5 * Math.exp(-(dx * dx + dz * dz) / (2 * 24 * 24))

  return h
}

/** Finite-difference slope (0 = flat). */
export function slopeAt(x: number, z: number) {
  const e = 1.5
  const dx = heightAt(x + e, z) - heightAt(x - e, z)
  const dz = heightAt(x, z + e) - heightAt(x, z - e)
  return Math.hypot(dx, dz) / (2 * e)
}
