export type Tier = 'high' | 'medium' | 'low'

export type Quality = {
  tier: Tier
  /** [min, max] render scale (already multiplied by devicePixelRatio) */
  dpr: [number, number]
  /** starting render scale before PerformanceMonitor adapts */
  startDpr?: number
  shadowMap: number
  grass: number // blades per m² in the dense hero patch
  wheat: number // clump density multiplier
  flowers: number
  trees: number // fraction of background trees
  forest: number // distant blob trees
  birds: number
  pollen: number
  post: boolean
  msaa: number
}

const PRESETS: Record<Tier, Quality> = {
  high: {
    tier: 'high', dpr: [1, 1.75], shadowMap: 2048, grass: 70, wheat: 1, flowers: 1,
    trees: 1, forest: 900, birds: 26, pollen: 450, post: true, msaa: 4,
  },
  medium: {
    tier: 'medium', dpr: [0.75, 1.1], shadowMap: 1024, grass: 26, wheat: 0.5, flowers: 0.7,
    trees: 0.7, forest: 420, birds: 18, pollen: 240, post: true, msaa: 0,
  },
  low: {
    tier: 'low', dpr: [0.6, 1.1], shadowMap: 1024, grass: 18, wheat: 0.32, flowers: 0.4,
    trees: 0.55, forest: 320, birds: 12, pollen: 140, post: false, msaa: 0,
  },
}

function gpuString(): string {
  try {
    const c = document.createElement('canvas')
    const gl = c.getContext('webgl2') || c.getContext('webgl')
    if (!gl) return 'none'
    const ext = gl.getExtension('WEBGL_debug_renderer_info')
    const s = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return String(s).toLowerCase()
  } catch {
    return 'unknown'
  }
}

export function hasWebGL() {
  return gpuString() !== 'none'
}

/** Multiplies the preset's render-scale range by the device pixel ratio. */
function scaled(q: Quality, start: number): Quality {
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  return { ...q, dpr: [q.dpr[0] * dpr, q.dpr[1] * dpr], startDpr: Math.min(start * dpr, q.dpr[1] * dpr) }
}

/** Heuristic device tier. PerformanceMonitor refines the pixel ratio at runtime. */
export function detectQuality(): Quality {
  const params = new URLSearchParams(window.location.search)
  const forced = params.get('quality') as Tier | null
  if (forced && forced in PRESETS) return scaled(PRESETS[forced], 0.85)

  const gpu = gpuString()
  const coarse = window.matchMedia('(pointer: coarse)').matches
  const small = Math.min(window.innerWidth, window.innerHeight) < 700
  const cores = navigator.hardwareConcurrency || 4
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8

  const software = /swiftshader|llvmpipe|software|basic render/.test(gpu)
  const integrated = /intel|mali|adreno|powervr|apple gpu|iris|uhd/.test(gpu)

  if (software || mem <= 2 || (coarse && small)) return scaled(PRESETS.low, 0.75)
  if (coarse || integrated || cores <= 4 || mem <= 4) return scaled(PRESETS.medium, 0.85)
  return scaled(PRESETS.high, 1)
}
