import { useEffect, useRef } from 'react'

// Live feed of node breadcrumbs as the graph executes (streamed via SSE).
// Hidden until the first run; auto-scrolls as new lines arrive.
export default function LogFeed({ logs, loading }) {
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [logs])

  if (!loading && logs.length === 0) return null

  return (
    <section className="card">
      <h2>
        Live log
        {loading && <span className="pulse"> ● running</span>}
      </h2>
      <ul className="logfeed">
        {logs.map((evt, i) => (
          <li key={i} className="logline">
            <span className="lognode">{evt.node}</span>
            <span className="logtext">{evt.line}</span>
          </li>
        ))}
        {loading && (
          <li className="logwait">
            <span className="dot" /> waiting for next step…
          </li>
        )}
        <li ref={endRef} />
      </ul>
    </section>
  )
}
