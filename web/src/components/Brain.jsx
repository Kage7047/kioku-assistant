import { useEffect, useMemo, useRef } from 'react'
import { gsap } from 'gsap'
import { reducedMotion } from '../lib/motion'
import Panel from './Panel'

const HUES = ['#f0a43a', '#a99bff', '#93c47d', '#e7765a', '#7cc4d6', '#d9b26f', '#c98bd6', '#8fa3bf']

/** The vault as a living graph: one cluster per top-level folder, one dot per note (capped),
 *  orphans drift unlinked at the edge. Built from /status → vault.by_dir, not decoration. */
function layout(byDir = {}, orphans = 0, width = 900, height = 260) {
  const dirs = Object.entries(byDir).map(([d, n]) => [d.split('/')[0] || '.', n])
  const merged = {}
  dirs.forEach(([d, n]) => { merged[d] = (merged[d] || 0) + n })
  const entries = Object.entries(merged).sort((a, b) => b[1] - a[1]).slice(0, 8)
  const nodes = [], links = []
  entries.forEach(([dir, count], i) => {
    const cx = ((i + 0.5) / entries.length) * width
    const cy = height / 2 + Math.sin(i * 1.7) * height * 0.18
    const hub = { x: cx, y: cy, r: 4 + Math.min(6, Math.sqrt(count)), hue: HUES[i % HUES.length], label: dir, hub: true }
    nodes.push(hub)
    const shown = Math.min(count, 18)
    for (let k = 0; k < shown; k++) {
      const a = (k / shown) * Math.PI * 2 + i
      const rad = 22 + (k % 3) * 14
      const n = { x: cx + Math.cos(a) * rad, y: cy + Math.sin(a) * rad * 0.8, r: 2.2, hue: hub.hue, phase: k * 0.7 + i }
      nodes.push(n)
      links.push([hub, n])
    }
    if (i > 0) links.push([nodes.find((x) => x.label === entries[i - 1][0]), hub])
  })
  for (let k = 0; k < Math.min(orphans, 12); k++) {
    nodes.push({ x: 20 + ((k * 73) % (width - 40)), y: k % 2 ? 14 : height - 14, r: 1.8, hue: '#6f6556', phase: k })
  }
  return { nodes, links }
}

export default function Brain({ vault }) {
  const canvas = useRef(null)
  const graph = useMemo(() => layout(vault?.by_dir, vault?.orphans), [vault])

  useEffect(() => {
    const el = canvas.current
    if (!el) return
    const ctx = el.getContext('2d')
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    let w = 0, h = 0
    const size = () => {
      const r = el.getBoundingClientRect(); w = r.width; h = r.height
      el.width = w * dpr; el.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    size()
    const ink = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#a39684'
    const draw = (t = 0) => {
      ctx.clearRect(0, 0, w, h)
      const sx = w / 900, sy = h / 260
      const pos = (n) => [n.x * sx + (n.hub ? 0 : Math.sin(t + (n.phase || 0)) * 2), n.y * sy + (n.hub ? 0 : Math.cos(t * 0.8 + (n.phase || 0)) * 2)]
      ctx.lineWidth = 1
      graph.links.forEach(([a, b]) => {
        if (!a || !b) return
        const [ax, ay] = pos(a), [bx, by] = pos(b)
        ctx.strokeStyle = 'rgba(163,150,132,0.18)'
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke()
      })
      graph.nodes.forEach((n) => {
        const [x, y] = pos(n)
        ctx.fillStyle = n.hue
        ctx.globalAlpha = n.hub ? 1 : 0.75
        ctx.beginPath(); ctx.arc(x, y, n.r, 0, Math.PI * 2); ctx.fill()
        if (n.hub) {
          ctx.globalAlpha = 1; ctx.fillStyle = ink; ctx.font = '11px JetBrains Mono, monospace'
          ctx.fillText(n.label, x + n.r + 6, y + 4)
        }
      })
      ctx.globalAlpha = 1
    }
    const ro = new ResizeObserver(() => { size(); draw() })
    ro.observe(el)
    if (reducedMotion()) { draw(); return () => ro.disconnect() }
    const tick = (time) => draw(time * 0.9)
    gsap.ticker.add(tick)
    return () => { gsap.ticker.remove(tick); ro.disconnect() }
  }, [graph])

  const folders = Object.keys(vault?.by_dir || {}).length
  return (
    <Panel area="brain" title="Knowledge graph" aside="living">
      <div className="stats" aria-live="polite">
        <span><b>{vault?.files ?? '—'}</b>notes</span>
        <span><b>{folders || '—'}</b>folders</span>
        <span><b>{vault?.orphans ?? '—'}</b>orphans</span>
        <span><b>{vault?.dead_links ?? '—'}</b>dead links</span>
      </div>
      <canvas ref={canvas} role="img" aria-label={`Vault graph: ${vault?.files ?? 0} notes across ${folders} folders`} />
    </Panel>
  )
}
