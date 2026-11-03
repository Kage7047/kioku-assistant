import { useEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { api } from '../lib/api'
import { usd } from '../lib/format'
import { reducedMotion } from '../lib/motion'

export default function Header({ status, onToggle }) {
  const [now, setNow] = useState(() => new Date())
  const pulse = useRef(null)
  const paused = !!status?.paused
  const b = status?.budget
  const live = (status?.connectors || []).filter((c) => c.state !== 'off').length

  useEffect(() => { const t = setInterval(() => setNow(new Date()), 30_000); return () => clearInterval(t) }, [])
  useEffect(() => {
    if (paused || reducedMotion() || !pulse.current) return
    const tw = gsap.to(pulse.current, { boxShadow: '0 0 0 10px rgba(240,164,58,0)', repeat: -1, duration: 1.8, ease: 'power2.out' })
    return () => tw.kill()
  }, [paused])

  async function toggle() {
    if (!paused && !window.confirm('Pause Kioku? It stops running and spending until you resume.')) return
    await api(paused ? '/resume' : '/pause', { method: 'POST' }).catch(() => {})
    onToggle()
  }

  return (
    <header className="top">
      <div className="brand">
        <span ref={pulse} className={`pulse ${paused ? 'paused' : ''}`} aria-hidden="true" />
        <h1>Kioku</h1>
        <span className="kanji" lang="ja">記憶</span>
      </div>
      <p className="state" aria-live="polite">
        is <b>{status ? (paused ? 'paused' : 'awake') : '…'}</b> · watching {live} signals
      </p>
      <span className="spacer" />
      {b && (
        <span className="chip" title={`${Math.round(b.fraction * 100)}% of the monthly credit used`}>
          <span className={`dot ${b.mode === 'normal' ? '' : 'warn'}`} /> budget {b.mode} · {usd(b.remaining)} left
        </span>
      )}
      <button className="chip" onClick={toggle} aria-pressed={paused}>{paused ? '▶ resume' : '⏸ pause'}</button>
      <time className="state" dateTime={now.toISOString()}>
        {now.toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase()} · {now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
      </time>
    </header>
  )
}
