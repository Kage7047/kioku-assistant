import SpotlightCard from './rb/SpotlightCard'

/** A dashboard card: SpotlightCard surface + a labelled region with a mono heading. */
export default function Panel({ area, title, aside, children, className = '' }) {
  const id = `h-${area}`
  return (
    <SpotlightCard className={`panel ${area} ${className}`} spotlightColor="rgba(240, 164, 58, 0.12)" intensity={0.12}>
      <section aria-labelledby={id} style={{ display: 'contents' }}>
        <h2 id={id}>{title}{aside ? <small>{aside}</small> : null}</h2>
        {children}
      </section>
    </SpotlightCard>
  )
}
