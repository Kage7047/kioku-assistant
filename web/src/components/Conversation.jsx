import { useEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { api, streamRun } from '../lib/api'
import { modelShort, renderInline } from '../lib/format'
import { reducedMotion } from '../lib/motion'
import ClickSpark from './rb/ClickSpark'
import Panel from './Panel'

const HINTS = ["what's blocking Jonas", 'that retry bug', 'remember: try Redis streams for the matcher', '/audit']

export default function Conversation({ onRun }) {
  const [msgs, setMsgs] = useState([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const thread = useRef(null)
  const file = useRef(null)
  const stop = useRef(null)

  useEffect(() => () => stop.current?.(), [])
  useEffect(() => {
    const el = thread.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: reducedMotion() ? 'auto' : 'smooth' })
    const last = el.lastElementChild
    if (last && !reducedMotion() && !last.dataset.seen) {
      last.dataset.seen = '1'
      gsap.from(last, { y: 10, autoAlpha: 0, duration: 0.35, ease: 'power2.out' })
    }
  }, [msgs])

  const patchLast = (fn) => setMsgs((m) => [...m.slice(0, -1), fn(m[m.length - 1])])

  async function send(input = text) {
    const q = input.trim()
    if (!q || busy) return
    setText('')
    setBusy(true)
    setMsgs((m) => [...m, { me: true, text: q }, { text: '', streaming: true, meta: 'routing…' }])
    try {
      const r = await api('/tasks', { method: 'POST', json: { kind: 'input', input: q, source: 'web' } })
      onRun?.()
      stop.current = streamRun(r.run_id, (ev) => {
        if (ev.type === 'start') patchLast((m) => ({ ...m, meta: `${modelShort(ev.model)} · ${ev.mode}` }))
        if (ev.type === 'text') patchLast((m) => ({ ...m, text: m.text + ev.text }))
        if (ev.type === 'done' || ev.type === 'error') {
          patchLast((m) => ({ ...m, text: ev.text || m.text || '(no reply)', streaming: false }))
          setBusy(false)
          onRun?.()
        }
      })
    } catch (e) {
      patchLast((m) => ({ ...m, text: `Could not send: ${e.message}`, streaming: false, meta: 'error' }))
      setBusy(false)
    }
  }

  async function upload(files) {
    for (const f of files) {
      const body = new FormData()
      body.append('file', f)
      setMsgs((m) => [...m, { me: true, text: `📎 ${f.name}` }])
      try {
        await api('/ingest', { method: 'POST', body })
        setMsgs((m) => [...m, { text: `Filing **${f.name}** to the vault — I'll digest it in the background.`, meta: 'ingest' }])
      } catch (e) {
        setMsgs((m) => [...m, { text: `Upload failed: ${e.message}`, meta: 'error' }])
      }
    }
    onRun?.()
  }

  return (
    <Panel area="chat" title="Conversation" aside="ask · plan · capture · automate">
      <div className="thread" ref={thread} role="log" aria-live="polite" aria-relevant="additions">
        {msgs.length === 0 && (
          <div className="empty">
            Ask about your notes, capture an idea, or try:
            <div className="tags" style={{ marginTop: 10 }}>
              {HINTS.map((h) => <button key={h} className="tag" onClick={() => send(h)}>{h}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.me ? 'me' : ''}`}>
            <span dangerouslySetInnerHTML={{ __html: renderInline(m.text) }} />
            {m.streaming && <span className="caret" aria-hidden="true" />}
            {!m.me && m.meta && <span className="meta"><b>{m.meta}</b></span>}
          </div>
        ))}
      </div>
      <form className="composer" id="composer" onSubmit={(e) => { e.preventDefault(); send() }}>
        <label className="sr" htmlFor="msg">Message Kioku</label>
        <textarea id="msg" rows={1} value={text} placeholder="Talk to Kioku…" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
        <input ref={file} type="file" hidden multiple onChange={(e) => { upload([...e.target.files]); e.target.value = '' }} />
        <button type="button" className="btn icon" aria-label="Attach a file" onClick={() => file.current?.click()}>＋</button>
        <ClickSpark sparkColor="#f0a43a" sparkCount={10} sparkRadius={22}>
          <button type="submit" className="btn primary" disabled={busy}>{busy ? '…' : 'Send ↵'}</button>
        </ClickSpark>
      </form>
    </Panel>
  )
}
