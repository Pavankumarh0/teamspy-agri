import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { SplitText } from 'gsap/SplitText'
import Lenis from 'lenis'
import { emitActive, store } from '../lib/store'
import { clamp, smoothstep } from '../lib/noise'

gsap.registerPlugin(ScrollTrigger, SplitText)

export let lenis: Lenis | null = null

export function scrollToId(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  if (lenis) lenis.scrollTo(el, { duration: 2.2, easing: (t) => 1 - Math.pow(1 - t, 4) })
  else el.scrollIntoView({ behavior: store.reducedMotion ? 'auto' : 'smooth' })
}

/**
 * Smooth scrolling + mapping of scroll position to `store.section`.
 * Each section's "anchor" is the scroll offset where it is centred in the
 * viewport; between anchors the camera holds on a shot, then glides.
 */
let controller: { start: () => void } | null = null

export function initScroll() {
  if (controller) return controller
  store.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!store.reducedMotion) {
    lenis = new Lenis({ lerp: 0.085, wheelMultiplier: 0.95, touchMultiplier: 1.4 })
    lenis.on('scroll', ScrollTrigger.update)
    gsap.ticker.add((time) => lenis?.raf(time * 1000))
    gsap.ticker.lagSmoothing(0)
    lenis.stop()
  }

  const sections = Array.from(document.querySelectorAll<HTMLElement>('[data-section]'))
  let anchors: number[] = []
  const measure = () => {
    const vh = window.innerHeight
    const max = document.documentElement.scrollHeight - vh
    anchors = sections.map((s) => {
      const top = s.getBoundingClientRect().top + window.scrollY
      return clamp(top + s.offsetHeight / 2 - vh / 2, 0, max)
    })
    for (let i = 1; i < anchors.length; i++) anchors[i] = Math.max(anchors[i], anchors[i - 1] + 1)
    update()
  }

  const update = () => {
    const y = lenis ? lenis.animatedScroll : window.scrollY
    let s = 0
    if (y >= anchors[anchors.length - 1]) s = anchors.length - 1
    else {
      for (let i = 0; i < anchors.length - 1; i++) {
        if (y < anchors[i + 1]) {
          const f = (y - anchors[i]) / (anchors[i + 1] - anchors[i])
          // hold on each shot for a moment, then glide to the next
          s = i + smoothstep(0.12, 0.88, clamp(f, 0, 1))
          break
        }
      }
    }
    store.section = s
    emitActive()
    document.documentElement.style.setProperty('--scroll', String(y / Math.max(1, document.documentElement.scrollHeight - window.innerHeight)))
  }

  measure()
  window.addEventListener('resize', measure)
  if (lenis) lenis.on('scroll', update)
  else window.addEventListener('scroll', update, { passive: true })
  ScrollTrigger.addEventListener('refresh', measure)

  controller = {
    start() {
      lenis?.start()
      measure()
      ScrollTrigger.refresh()
    },
  }
  return controller
}

/** Scroll-triggered reveals, split-text headings, counters and parallax. */
export function initRevealAnimations() {
  const ctx = gsap.context(() => {
    gsap.utils.toArray<HTMLElement>('[data-split]').forEach((el) => {
      const split = SplitText.create(el, { type: 'lines,words', mask: 'lines', linesClass: 'split-line' })
      gsap.from(split.words, {
        yPercent: 110,
        opacity: 0,
        duration: 1.1,
        ease: 'expo.out',
        stagger: 0.035,
        scrollTrigger: { trigger: el, start: 'top 82%', once: true },
      })
    })

    gsap.utils.toArray<HTMLElement>('[data-reveal]').forEach((el) => {
      const delay = Number(el.dataset.delay ?? 0)
      gsap.from(el, {
        y: 46,
        opacity: 0,
        filter: 'blur(8px)',
        duration: 1.15,
        delay,
        ease: 'power3.out',
        scrollTrigger: { trigger: el, start: 'top 88%', once: true },
      })
    })

    gsap.utils.toArray<HTMLElement>('[data-count]').forEach((el) => {
      const end = Number(el.dataset.count)
      const decimals = Number(el.dataset.decimals ?? 0)
      const obj = { v: 0 }
      gsap.to(obj, {
        v: end,
        duration: 2.4,
        ease: 'power2.out',
        scrollTrigger: { trigger: el, start: 'top 90%', once: true },
        onUpdate: () => {
          el.textContent = obj.v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
        },
      })
    })

    // entering the farm: the hero copy lifts away while the camera pushes in
    gsap.to('.hero-copy', {
      yPercent: -18,
      opacity: 0,
      ease: 'none',
      scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom 30%', scrub: true },
    })
    gsap.to('.hero-scrim', {
      opacity: 0,
      ease: 'none',
      scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: true },
    })
    gsap.to('.scroll-cue', {
      opacity: 0,
      y: 20,
      ease: 'none',
      scrollTrigger: { trigger: '.hero', start: 'top top', end: '25% top', scrub: true },
    })
    gsap.to('.hero-aside', {
      y: -140,
      opacity: 0,
      ease: 'none',
      scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom 40%', scrub: true },
    })
    // every panel floats at its own pace over the moving world
    gsap.utils.toArray<HTMLElement>('.section:not(.hero) .panel').forEach((el) => {
      gsap.fromTo(
        el,
        { y: 90 },
        { y: -90, ease: 'none', scrollTrigger: { trigger: el.parentElement, start: 'top bottom', end: 'bottom top', scrub: true } },
      )
    })

    gsap.utils.toArray<HTMLElement>('[data-parallax]').forEach((el) => {
      const amount = Number(el.dataset.parallax ?? 60)
      gsap.fromTo(
        el,
        { y: amount },
        { y: -amount, ease: 'none', scrollTrigger: { trigger: el, start: 'top bottom', end: 'bottom top', scrub: true } },
      )
    })
  })
  return () => ctx.revert()
}

/** Hero entrance, played as soon as the page is ready (no preloader). */
export function playIntro() {
  const tl = gsap.timeline({ defaults: { ease: 'expo.out' } })
  const title = document.querySelector<HTMLElement>('[data-hero-title]')
  if (title) {
    const split = SplitText.create(title, { type: 'lines,words', mask: 'lines', linesClass: 'split-line' })
    tl.from(split.words, { yPercent: 115, duration: 1.5, stagger: 0.06 }, 0.55)
  }
  tl.from('[data-intro]', { y: 34, opacity: 0, filter: 'blur(6px)', duration: 1.3, stagger: 0.09 }, 0.75)
  tl.from('.nav', { y: -30, opacity: 0, duration: 1.2 }, 0.4)
  tl.from('.hero-aside', { x: 40, opacity: 0, duration: 1.4 }, 1.3)
  tl.from('.rail', { opacity: 0, duration: 1.2 }, 1.6)
  return tl
}

/** Camera fly-in from the establishing shot, once the 3D world has rendered. */
export function playFlyIn() {
  gsap.to(store, { intro: 1, duration: store.reducedMotion ? 0.01 : 4.2, ease: 'none' })
}
