// Streaming client for the FastAPI backend. POST /triage returns Server-Sent
// Events: `log` events as each node runs, then a final `result` (or `error`).
// Relative URL works via the Vite dev proxy and when served by the backend.

export async function triageDefectStream(payload, { onLog, onResult }) {
  const res = await fetch('/triage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

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

    // SSE frames are separated by a blank line.
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)

      const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!dataLine) continue
      const evt = JSON.parse(dataLine.slice(5).trim())

      if (evt.type === 'log') onLog(evt)
      else if (evt.type === 'result') onResult(evt.state)
      else if (evt.type === 'error') throw new Error(evt.message)
    }
  }
}
