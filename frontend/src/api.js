// Thin client for the FastAPI backend. Relative URLs work both via the Vite dev
// proxy (npm run dev) and when the built app is served by the backend itself.

export async function triageDefect(payload) {
  const res = await fetch('/triage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body)
    } catch {
      detail = (await res.text()) || detail
    }
    if (/RESOURCE_EXHAUSTED|429|quota/i.test(detail)) {
      throw new Error(
        'Gemini free-tier quota exhausted (20 requests/day). Try a duplicate defect ' +
          '(it skips the LLM), or retry after the daily reset.',
      )
    }
    throw new Error(detail)
  }
  return res.json()
}
