// Thin client over the Kioku API. The token lives in localStorage (per browser) and is sent as a
// bearer header; EventSource cannot set headers, so the stream URL carries it as ?token=.
const KEY = 'kioku_token'
const listeners = new Set()

export const getToken = () => {
  try { return localStorage.getItem(KEY) || '' } catch { return '' }
}
export function setToken(t) {
  try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY) } catch { /* private mode */ }
  listeners.forEach((l) => l())
}
export const onTokenChange = (cb) => (listeners.add(cb), () => listeners.delete(cb))

export class Unauthorized extends Error {}

export async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  const tok = getToken()
  if (tok) headers.Authorization = `Bearer ${tok}`
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    opts = { ...opts, body: JSON.stringify(opts.json) }
  }
  const r = await fetch(path, { ...opts, headers })
  if (r.status === 401) throw new Unauthorized()
  if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => '')}`.trim())
  const type = r.headers.get('content-type') || ''
  return type.includes('json') ? r.json() : r.text()
}

/** Follow a run's events. Returns a function that stops listening. */
export function streamRun(runId, onEvent) {
  const tok = getToken()
  const es = new EventSource(`/tasks/${runId}/stream${tok ? `?token=${encodeURIComponent(tok)}` : ''}`)
  const handle = (e) => {
    try {
      const ev = JSON.parse(e.data)
      onEvent(ev)
      if (ev.type === 'done') es.close()
    } catch { /* keep-alive or malformed line */ }
  }
  es.addEventListener('run', handle)
  es.onmessage = handle
  es.onerror = () => { es.close(); onEvent({ type: 'error' }) }
  return () => es.close()
}
