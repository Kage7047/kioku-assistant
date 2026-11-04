import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import Panel from './Panel'

export default function Skills({ status }) {
  const [skills, setSkills] = useState([])
  const [people, setPeople] = useState([])
  useEffect(() => {
    api('/skills').then(setSkills).catch(() => {})
    api('/people?limit=12').then(setPeople).catch(() => {})
  }, [status?.people])
  return (
    <Panel area="skills" title="Skills & people" aside={`${skills.length} skills · ${status?.people ?? 0} people`}>
      <div className="tags" style={{ marginBottom: 12 }}>
        {skills.length === 0 && <span className="empty">No learned skills yet — Kioku proposes them from your week.</span>}
        {skills.map((s) => <span className="tag" key={s.name} title={s.when}><b>{s.name}</b></span>)}
      </div>
      <div className="tags">
        {people.map((p) => <span className="tag" key={p.id || p.name} title={p.context || ''}>{p.name}</span>)}
      </div>
    </Panel>
  )
}
