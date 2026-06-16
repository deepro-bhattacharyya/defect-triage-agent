import { useState } from 'react'
import DefectForm from './components/DefectForm.jsx'
import ResultPanel from './components/ResultPanel.jsx'
import { triageDefect } from './api.js'

export default function App() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(payload) {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      setResult(await triageDefect(payload))
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
        <ResultPanel result={result} loading={loading} error={error} />
      </main>
    </>
  )
}
