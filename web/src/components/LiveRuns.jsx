import { useRef } from 'react'
import { gsap } from 'gsap'
import { useGSAP } from '@gsap/react'
import { ago, modelShort, usd } from '../lib/format'
import { reducedMotion } from '../lib/motion'
import Panel from './Panel'

export default function LiveRuns({ runs }) {
  const list = useRef(null)
  const seen = useRef(new Set())
  const today = (runs || []).filter((r) => r.created_at && new Date(r.created_at).toDateString() === new Date().toDateString())
  const spent = today.reduce((s, r) => s + (r.cost_usd || 0), 0)

  useGSAP(() => {
    if (!runs || reducedMotion()) return
    const fresh = runs.filter((r) => !seen.current.has(r.id)).map((r) => `[data-run="${r.id}"]`)
    if (seen.current.size && fresh.length) gsap.from(fresh.join(','), { x: -12, autoAlpha: 0, duration: 0.45, stagger: 0.05 })
    runs.forEach((r) => seen.current.add(r.id))
  }, { scope: list, dependencies: [runs] })

  return (
    <Panel area="runs" title="Live runs" aside={`${today.length} today · ${usd(spent, 2)}`}>
      <div ref={list}>
        {!runs && <div className="empty">Loading…</div>}
        {runs?.length === 0 && <div className="empty">No runs yet — ask something.</div>}
        {runs?.map((r) => (
          <div className="run" key={r.id} data-run={r.id}>
            <div style={{ minWidth: 0 }}>
              <div className="title" title={r.input}>{r.input || r.kind}</div>
              <div className="sub">{r.kind} · {modelShort(r.model)} · {ago(r.created_at)}</div>
            </div>
            <span className={`badge ${r.status}`}>{r.status}</span>
            <span className="cost">{usd(r.cost_usd, 3)}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
