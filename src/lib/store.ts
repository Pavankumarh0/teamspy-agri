import { Vector2, Vector3 } from 'three'

/**
 * Mutable runtime state shared between the DOM (scroll, pointer) and the
 * render loop. Deliberately not React state: it changes every frame.
 */
export const store = {
  /** Continuous section index driven by scroll: 0 = hero … N-1 = contact. */
  section: 0,
  /** 0 → 1 camera fly-in after loading. */
  intro: 0,
  ready: false,
  /** Normalised pointer, -1..1. */
  pointer: new Vector2(),
  /** Pointer projected onto the ground (xz) + push strength in y. */
  pointerWorld: new Vector3(0, 0, 0),
  pointerActive: 0,
  /** Damped camera look-at point, used to aim the shadow camera. */
  camTarget: new Vector3(),
  portrait: false,
  reducedMotion: false,
}

export const SECTION_COUNT = 6

/** Fixed overlay that in-world HTML labels are portalled into (see App). */
export const worldUiRef: { current: HTMLDivElement | null } = { current: null }

/** 0..1 weight for how much `index` is the current section. */
export function sectionWeight(index: number, width = 0.6) {
  const d = Math.abs(store.section - index)
  return Math.max(0, 1 - d / width)
}

/** Tiny pub/sub so React UI can react to section changes without per-frame renders. */
type Listener = (active: number) => void
const listeners = new Set<Listener>()
let lastActive = -1
export function onActiveSection(fn: Listener) {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
export function emitActive() {
  const a = Math.round(store.section)
  if (a !== lastActive) {
    lastActive = a
    listeners.forEach((l) => l(a))
  }
}
