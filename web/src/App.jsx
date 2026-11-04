import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { gsap } from 'gsap'
import { useGSAP } from '@gsap/react'
import { api, getToken, onTokenChange, setToken } from './lib/api'
import { usePoll } from './lib/usePoll'
import { reducedMotion, setMotion, useReducedMotionState } from './lib/motion'
import { startSmoothScroll, stopSmoothScroll } from './lib/smooth'
import TokenGate from './components/TokenGate'
import Header from './components/Header'
import Conversation from './components/Conversation'
import LiveRuns from './components/LiveRuns'
import Credit from './components/Credit'
import Approvals from './components/Approvals'
import Activity from './components/Activity'
import Brain from './components/Brain'
import Skills from './components/Skills'

gsap.registerPlugin(useGSAP)

const useToken = () => useSyncExternalStore(onTokenChange, getToken, () => '')

export default function App() {
  const token = useToken()
  const [rejected, setRejected] = useState(false)
  if (!token || rejected) {
    return <TokenGate failed={rejected} onSubmit={(t) => { setRejected(false); setToken(t) }} />
  }
  return <Dashboard key={token} onUnauthorized={() => setRejected(true)} />
}

function Dashboard({ onUnauthorized }) {
  const token = useToken()
  const status = usePoll(() => api('/status'), 8000, [token])
  const runs = usePoll(() => api('/runs?limit=8'), 4000, [token])
  const reduced = useReducedMotionState()
  const root = useRef(null)

  useEffect(() => {
    if (reduced) return stopSmoothScroll()
    startSmoothScroll()
    return stopSmoothScroll
  }, [reduced])

  useGSAP(() => {
    if (reducedMotion() || !status.data || !root.current) return
    gsap.from('.panel', { y: 24, autoAlpha: 0, duration: 0.7, ease: 'power3.out', stagger: 0.06 })
  }, { scope: root, dependencies: [!!status.data] })

  const unauthorized = status.unauthorized || runs.unauthorized
  useEffect(() => { if (unauthorized) onUnauthorized() }, [unauthorized, onUnauthorized])

  const refreshAll = () => { status.refresh(); runs.refresh() }

  return (
    <div className="shell" ref={root}>
      <a className="skip" href="#composer">Skip to the conversation</a>
      <Header status={status.data} onToggle={refreshAll} />
      <main className="grid" aria-busy={!status.data}>
        <Conversation onRun={refreshAll} />
        <LiveRuns runs={runs.data} />
        <Credit status={status.data} />
        <Approvals status={status.data} onChange={refreshAll} />
        <Activity status={status.data} />
        <Brain vault={status.data?.vault} />
        <Skills status={status.data} />
      </main>
      <footer className="foot">
        <span>Kioku · 記憶 — files are truth, the database is an index</span>
        <span>
          <button onClick={() => setMotion(reduced)}>{reduced ? 'Turn motion on' : 'Reduce motion'}</button>
          {' · '}
          <button onClick={() => setToken('')}>Sign out</button>
        </span>
      </footer>
    </div>
  )
}
