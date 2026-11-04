import { useSyncExternalStore } from 'react'

/**
 * Single source of truth for motion preference.
 * Default follows the OS setting. A visitor (or a demo link with ?motion=on) can override it,
 * and the choice is remembered.
 */
const KEY = 'kioku-motion'
const mq = typeof window !== 'undefined' ? window.matchMedia('(prefers-reduced-motion: reduce)') : null
const listeners = new Set()

function readOverride() {
  try {
    const q = new URLSearchParams(window.location.search).get('motion')
    if (q === 'on' || q === 'off') {
      localStorage.setItem(KEY, q)
      return q
    }
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}
let override = typeof window !== 'undefined' ? readOverride() : null

export const reducedMotion = () => (override === 'on' ? false : override === 'off' ? true : !!mq?.matches)

function apply() {
  if (typeof document !== 'undefined') document.documentElement.dataset.motion = reducedMotion() ? 'off' : 'on'
}
const emit = () => listeners.forEach((l) => l())
mq?.addEventListener?.('change', () => {
  apply()
  emit()
})
apply()

export function setMotion(on) {
  override = on ? 'on' : 'off'
  try {
    localStorage.setItem(KEY, override)
  } catch {
    /* storage unavailable, the choice just won't persist */
  }
  apply()
  emit()
}

const subscribe = (cb) => (listeners.add(cb), () => listeners.delete(cb))
export const useReducedMotionState = () => useSyncExternalStore(subscribe, reducedMotion, () => false)
