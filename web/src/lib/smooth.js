import Lenis from 'lenis'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

import { reducedMotion } from './motion'

export const prefersReducedMotion = reducedMotion

let lenis = null

/** One Lenis instance, driven by the GSAP ticker so ScrollTrigger and Lenis never drift apart. */
export function startSmoothScroll() {
  if (lenis || prefersReducedMotion()) return null
  lenis = new Lenis({ lerp: 0.09, smoothWheel: true, wheelMultiplier: 0.95 })
  lenis.on('scroll', ScrollTrigger.update)
  const tick = (time) => lenis.raf(time * 1000)
  gsap.ticker.add(tick)
  gsap.ticker.lagSmoothing(0)
  lenis.__tick = tick
  return lenis
}

export function stopSmoothScroll() {
  if (!lenis) return
  gsap.ticker.remove(lenis.__tick)
  lenis.destroy()
  lenis = null
}

export const getLenis = () => lenis

export function scrollToTarget(target, offset = 0) {
  const el = typeof target === 'string' ? document.querySelector(target) : target
  if (!el) return
  if (lenis) lenis.scrollTo(el, { offset, duration: 1.4, easing: (t) => 1 - Math.pow(1 - t, 4) })
  else el.scrollIntoView({ behavior: 'auto', block: 'start' })
  // keep keyboard users in the right place
  if (el.id) {
    el.setAttribute('tabindex', '-1')
    el.focus({ preventScroll: true })
  }
}
