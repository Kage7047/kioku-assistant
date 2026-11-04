import { useRef, useState } from 'react'
import SplitText from './rb/SplitText'

export default function TokenGate({ onSubmit, failed }) {
  const [value, setValue] = useState('')
  const input = useRef(null)
  return (
    <div className="gatewall">
      <form onSubmit={(e) => { e.preventDefault(); if (value.trim()) onSubmit(value.trim()) }}>
        <SplitText text="Kioku" tag="h1" splitType="chars" delay={70} duration={1} trigger="load" textAlign="center" />
        <p>記憶 — enter the dashboard token to continue.</p>
        <label className="sr" htmlFor="token">Dashboard token</label>
        <input id="token" ref={input} type="password" autoComplete="current-password" autoFocus
          value={value} onChange={(e) => setValue(e.target.value)} placeholder="token" />
        <div className="err" role="alert">{failed ? 'That token was not accepted.' : ''}</div>
        <button className="btn primary" type="submit" style={{ width: '100%' }}>Open command center</button>
      </form>
    </div>
  )
}
