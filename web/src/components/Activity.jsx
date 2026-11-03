import { ago } from '../lib/format'
import Panel from './Panel'

export default function Activity({ status }) {
  const conns = status?.connectors || []
  const sched = status?.schedules || []
  const v = status?.vault
  return (
    <Panel area="activity" title="Activity" aside="proactive">
      <ul className="feed">
        {v && <li><span className="ico" /> Vault: {v.files} notes, {v.orphans} orphans, {v.dead_links} dead links<span className="when">{ago(status.vault_observed_at)}</span></li>}
        {sched.slice(0, 4).map((s, i) => (
          <li key={`s${i}`}><span className="ico" /> {s.name || s.prompt || 'schedule'}<span className="when">{s.cron || s.when || ''}</span></li>
        ))}
        {conns.map((c) => (
          <li key={c.name}>
            <span className={`ico ${c.state === 'off' ? 'off' : ''}`} />
            {c.name} — {c.state === 'off' ? 'not connected' : c.state}
            <span className="when">{c.last_seen ? ago(c.last_seen) : '—'}</span>
          </li>
        ))}
        {!status && <li className="empty">Loading…</li>}
      </ul>
    </Panel>
  )
}
