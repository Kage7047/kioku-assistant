import CountUp from './rb/CountUp'
import Sparkline from './Sparkline'
import Panel from './Panel'
import { usd } from '../lib/format'

const TIERS = ['haiku', 'sonnet', 'opus', 'fable']

export default function Credit({ status }) {
  const b = status?.budget
  const byModel = Object.entries(status?.spend_by_model || {})          // {model: usd}
  const spentFor = (t) => byModel.filter(([m]) => m.includes(t)).reduce((s, [, c]) => s + Number(c || 0), 0)
  return (
    <Panel area="credit" title="Agent credit" aside={b ? <span className={`mode ${b.mode === 'normal' ? '' : 'warn'}`}>{b.mode}</span> : null}>
      {!b ? <div className="empty">Loading…</div> : (
        <>
          <div className="row">
            <span className="big" aria-label={`${usd(b.remaining)} left this cycle`}>
              $<CountUp to={b.remaining} decimals={2} duration={1.2} trigger="load" />
            </span>
            <span>{usd(b.spend)} of {usd(b.credit, 0)} used</span>
          </div>
          <div className="row"><span>left this cycle</span><span>{Math.round(b.fraction * 100)}%</span></div>
          <Sparkline points={status.spend_series} label="Month-to-date spend" />
          <div className="tiers">
            {TIERS.map((t) => (
              <div className="tier" key={t}><b>{t}</b>{spentFor(t) ? usd(spentFor(t)) : '—'}</div>
            ))}
          </div>
        </>
      )}
    </Panel>
  )
}
