import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'
import { reducedMotion } from '../lib/motion'

/** Month-to-date spend as an area line; draws itself in once. */
export default function Sparkline({ points = [], label }) {
  const path = useRef(null)
  const w = 300, h = 70
  const ys = points.map((p) => p.spend || 0)
  const max = Math.max(1e-6, ...ys)
  const xy = ys.map((y, i) => [ys.length < 2 ? 0 : (i / (ys.length - 1)) * w, h - 6 - (y / max) * (h - 14)])
  const line = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')

  useEffect(() => {
    const el = path.current
    if (!el || reducedMotion() || !line) return
    const len = el.getTotalLength()
    gsap.fromTo(el, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 1.4, ease: 'power2.inOut' })
  }, [line])

  if (ys.length < 2) return <div className="empty" style={{ height: h }}>Spend history appears after a few runs.</div>
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <defs>
        <linearGradient id="sparkfill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="var(--accent)" stopOpacity="0.28" />
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${w},${h} L0,${h} Z`} fill="url(#sparkfill)" />
      <path ref={path} d={line} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
