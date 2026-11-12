import { Component, Suspense, lazy, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { detectQuality, hasWebGL } from './lib/quality'
import { store, worldUiRef } from './lib/store'
import { initRevealAnimations, initScroll, playFlyIn, playIntro } from './ui/scroll'
import { Nav } from './ui/Nav'
import { Contact, Fields, Hero, Impact, Pasture, Technology } from './ui/Sections'

const Experience = lazy(() => import('./three/Experience').then((m) => ({ default: m.Experience })))

/** If WebGL fails at runtime, fall back to the static painted backdrop instead of a blank page. */
class SceneBoundary extends Component<{ children: ReactNode; onError: () => void }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch(err: unknown) {
    console.error('3D scene failed, showing fallback.', err)
    this.props.onError()
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}

export default function App() {
  const quality = useMemo(detectQuality, [])
  const [webgl, setWebgl] = useState(() => hasWebGL())
  const scroll = useRef<ReturnType<typeof initScroll> | null>(null)

  useEffect(() => {
    document.body.classList.toggle('no-webgl', !webgl)
  }, [webgl])

  useEffect(() => {
    scroll.current = initScroll()
    const cleanupReveal = initRevealAnimations()

    const onMove = (e: PointerEvent) => {
      store.pointer.set((e.clientX / window.innerWidth) * 2 - 1, -(e.clientY / window.innerHeight) * 2 + 1)
      if (e.pointerType === 'mouse') store.pointerActive = 1
    }
    window.addEventListener('pointermove', onMove, { passive: true })

    // No preloader: the page plays its entrance as soon as the fonts are in (so the
    // split headline measures correctly), and is scrollable straight away.
    const begin = () => {
      if (store.ready) return
      store.ready = true
      document.body.classList.add('is-ready')
      playIntro()
      scroll.current?.start()
    }
    const fallback = window.setTimeout(begin, 1200)
    document.fonts.ready.then(begin, begin)

    // The 3D world fades in over the painted backdrop once it has rendered.
    const onScene = () => {
      document.body.classList.add('scene-on')
      playFlyIn()
    }
    window.addEventListener('scene-ready', onScene, { once: true })

    return () => {
      window.clearTimeout(fallback)
      cleanupReveal()
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('scene-ready', onScene)
    }
  }, [])

  return (
    <>
      <div className="backdrop" aria-hidden />
      {webgl && (
        <SceneBoundary onError={() => setWebgl(false)}>
          <Suspense fallback={null}>
            <Experience quality={quality} />
          </Suspense>
        </SceneBoundary>
      )}
      <div
        className="world-ui"
        ref={(el) => {
          worldUiRef.current = el
        }}
      />
      <div className="overlay-vignette" aria-hidden />
      <div className="overlay-grain" aria-hidden />

      <Nav />
      <main className="content">
        <Hero />
        <Fields />
        <Pasture />
        <Technology />
        <Impact />
        <Contact />
      </main>
    </>
  )
}
