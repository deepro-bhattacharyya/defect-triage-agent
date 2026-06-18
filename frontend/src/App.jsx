import { useState } from 'react'
import DefectForm from './components/DefectForm.jsx'
import LogFeed from './components/LogFeed.jsx'
import ResultPanel from './components/ResultPanel.jsx'
import { triageDefectStream } from './api.js'

export default function App() {
  const [result, setResult] = useState(null)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(payload) {
    setLoading(true)
    setError(null)
    setResult(null)
    setLogs([])
    try {
      await triageDefectStream(payload, {
        onLog: (evt) => setLogs((prev) => [...prev, evt]),
        onResult: (state) => setResult(state),
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <header className="topbar">
        <h1>🐞 DefectTriageBot</h1>
        <span className="subtitle">
          LLM-powered defect triage — severity, routing &amp; duplicate detection
        </span>
      </header>

      <main className="layout">
        <DefectForm onSubmit={handleSubmit} loading={loading} />
        <div className="right-col">
          <LogFeed logs={logs} loading={loading} />
          <ResultPanel result={result} loading={loading} error={error} />
        </div>
      </main>
    </>
  )
}
