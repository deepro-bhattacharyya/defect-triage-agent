import { useEffect, useRef, useState } from 'react'
import DefectForm from './components/DefectForm.jsx'
import LogFeed from './components/LogFeed.jsx'
import ResultPanel from './components/ResultPanel.jsx'
import ErrorModal from './components/ErrorModal.jsx'
import AssignmentModal from './components/AssignmentModal.jsx'
import Toasts from './components/Toasts.jsx'
import { getHealth, getJiraStatus, resumeTriageStream, triageDefectStream } from './api.js'

const MISSING_KEY_MSG =
  'No Gemini API key configured on the server (GOOGLE_API_KEY). Analysis and ' +
  'prioritization will fail — set the key in .env and restart the backend. ' +
  'Duplicate defects still work (they skip the LLM).'

export default function App() {
  const [result, setResult] = useState(null)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null) // fatal → blocking modal
  const [toasts, setToasts] = useState([]) // non-fatal warnings → dismissible
  const [assignment, setAssignment] = useState(null) // assignment_required → picker modal
  const [jiraConnected, setJiraConnected] = useState(false)
  const toastId = useRef(0)

  function addToast(message) {
    toastId.current += 1
    const id = toastId.current
    setToasts((prev) => [...prev, { id, message }])
  }
  function dismissToast(id) {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }

  useEffect(() => {
    getHealth().then((h) => {
      if (!h.llm_available) setError(MISSING_KEY_MSG)
    })
    getJiraStatus().then((s) => setJiraConnected(!!s.connected))
  }, [])

  // Shared handlers — logs accumulate across the initial run AND the resume,
  // so everything lands in the same live-log feed.
  const handlers = {
    onLog: (evt) => setLogs((prev) => [...prev, evt]),
    onResult: (state) => setResult(state),
    onWarning: (msg) => addToast(msg),
    onAssignmentRequired: (evt) =>
      setAssignment({ thread_id: evt.thread_id, team: evt.team, candidates: evt.candidates }),
  }

  async function handleSubmit(payload) {
    setLoading(true)
    setError(null)
    setResult(null)
    setLogs([])
    setAssignment(null)
    try {
      await triageDefectStream(payload, handlers)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleAssign(assignee) {
    const pending = assignment
    setAssignment(null)
    setLoading(true)
    try {
      await resumeTriageStream(pending.thread_id, assignee, handlers)
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
        <DefectForm onSubmit={handleSubmit} loading={loading} jiraConnected={jiraConnected} />
        <div className="right-col">
          <LogFeed logs={logs} loading={loading} />
          <ResultPanel result={result} loading={loading} />
        </div>
      </main>

      <Toasts toasts={toasts} onDismiss={dismissToast} />
      <AssignmentModal assignment={assignment} onConfirm={handleAssign} />
      <ErrorModal message={error} onClose={() => setError(null)} />
    </>
  )
}
