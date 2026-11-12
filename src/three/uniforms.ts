import { Vector3, Vector4 } from 'three'
import { SUN_DIR } from '../config/world'

/**
 * Uniform objects shared by reference across every vegetation material, so a
 * single update per frame drives wind, time and pointer interaction everywhere.
 */
export const globalUniforms = {
  uTime: { value: 0 },
  uWind: { value: 1 },
  /** xyz = pointer on the ground, w = push strength */
  uPointer: { value: new Vector4(0, 0, 0, 0) },
  uSunDir: { value: SUN_DIR.clone() as Vector3 },
}
