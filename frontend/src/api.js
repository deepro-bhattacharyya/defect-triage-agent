// Streaming client for the FastAPI backend. POST /triage returns Server-Sent
// Events: `log` events as each node runs, then a final `result` (or `error`).
// Relative URL works via the Vite dev proxy and when served by the backend.

// --- Jira (Task 1) ---

export async function getJiraStatus() {
  try {
    const res = await fetch('/jira/status')
    if (!res.ok) return { connected: false }
    return await res.json()
  } catch {
    return { connected: false }
  }
}

export async function getHealth() {
  try {
    const res = await fetch('/health')
    if (!res.ok) return { status: 'down', llm_available: false }
    return await res.json()
  } catch {
    return { status: 'down', llm_available: false }
  }
}

export async function fetchJiraIssue(key) {
  const res = await fetch(`/jira/issue/${encodeURIComponent(key)}`)
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      detail = (await res.json()).detail || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return await res.json() // the mapped defect dict
}

// Read an SSE response body, dispatching each event to the given handlers.
async function consumeStream(res, { onLog, onResult, onWarning, onAssignmentRequired }) {
  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`
    try {
      detail = (await res.text()) || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)

      const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!dataLine) continue
      const evt = JSON.parse(dataLine.slice(5).trim())

      if (evt.type === 'log') onLog(evt)
      else if (evt.type === 'result') onResult(evt.state)
      else if (evt.type === 'warning') onWarning?.(evt.message)
      else if (evt.type === 'assignment_required') onAssignmentRequired?.(evt)
      else if (evt.type === 'error') throw new Error(evt.message)
    }
  }
}

export async function triageDefectStream(payload, handlers) {
  const res = await fetch('/triage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  await consumeStream(res, handlers)
}

// Resume a paused triage after the user picks an assignee; events continue into
// the same handlers (stitched into the same live-log feed by thread_id).
export async function resumeTriageStream(threadId, assignee, handlers) {
  const res = await fetch('/triage/resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: threadId, assignee }),
  })
  await consumeStream(res, handlers)
}
