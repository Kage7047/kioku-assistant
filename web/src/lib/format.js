export function ago(iso) {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

export const usd = (v, d = 2) => `$${Number(v || 0).toFixed(d)}`

export function modelShort(m = '') {
  const hit = ['haiku', 'sonnet', 'opus', 'fable'].find((k) => m.includes(k))
  return hit || m || '—'
}

/** Minimal, safe markdown: escape first, then bold, inline code and links to vault paths. */
export function renderInline(text = '') {
  const esc = text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  return esc
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\b([\w-]+\/[\w./-]+\.md)\b/g, '<span class="path">$1</span>')
}
