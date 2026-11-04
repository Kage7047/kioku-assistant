import { useState } from 'react'
import { api } from '../lib/api'
import Magnet from './rb/Magnet'
import Panel from './Panel'

export default function Approvals({ status, onChange }) {
  const [busy, setBusy] = useState(null)
  const items = status?.approvals || []

  async function act(id, verb) {
    setBusy(id)
    try { await api(`/approvals/${id}/${verb}`, { method: 'POST' }) } catch { /* expired: the refresh drops it */ }
    setBusy(null)
    onChange()
  }

  return (
    <Panel area="approvals" title="Waiting for you" aside={String(items.length)}>
      {items.length === 0 && <div className="empty">Nothing waiting. Outbound actions — sending, sharing, deleting outside the vault — stop here for one tap.</div>}
      {items.map((a) => (
        <article className="gate" key={a.id} aria-label={`Approval ${a.id}`}>
          <div className="kind">{a.kind === 'config-edit' ? 'self-edit · needs approval' : 'outbound · send gate'}</div>
          <div className="what">{a.desc}</div>
          <div className="why">id {a.id}{a.rationale ? ` · ${a.rationale}` : ''} · nothing runs without you</div>
          <div className="actions">
            <Magnet padding={40} magnetStrength={4}>
              <button className="btn primary" disabled={busy === a.id} onClick={() => act(a.id, 'approve')}>Approve</button>
            </Magnet>
            <button className="btn" disabled={busy === a.id} onClick={() => act(a.id, 'reject')}>Reject</button>
          </div>
        </article>
      ))}
    </Panel>
  )
}
