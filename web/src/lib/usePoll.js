import { useCallback, useEffect, useRef, useState } from 'react'
import { Unauthorized } from './api'

/** Poll an async loader; pauses while the tab is hidden. Unauthorized is surfaced, not retried. */
export function usePoll(loader, ms, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const saved = useRef(loader)
  saved.current = loader

  const refresh = useCallback(async () => {
    try {
      setData(await saved.current())
      setError(null)
    } catch (e) {
      setError(e)
    }
  }, [])

  useEffect(() => {
    let timer
    const tick = async () => {
      if (!document.hidden) await refresh()
      timer = setTimeout(tick, ms)
    }
    tick()
    return () => clearTimeout(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error, refresh, unauthorized: error instanceof Unauthorized }
}
