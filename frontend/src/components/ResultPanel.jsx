function Banner({ result }) {
  if (result.is_duplicate) {
    return <div className="banner dup">🔁 Duplicate of {result.duplicate_of} — analysis skipped</div>
  }
  if (result.is_regression) {
    return <div className="banner reg">⚠️ Regression of {result.regression_of} — previously resolved</div>
  }
  return null
}

export default function ResultPanel({ result, loading, error }) {
  return (
    <section className="card">
      <h2>Result</h2>

      {loading && <div className="loading">⏳ Triaging… (LLM steps can take a few seconds)</div>}
      {error && !loading && <div className="error">{error}</div>}
      {!loading && !error && !result && (
        <div className="placeholder">Submit a defect to see the triage outcome.</div>
      )}

      {result && !loading && (
        <div className="result">
          <Banner result={result} />

          <div className="badges">
            {result.severity && <span className={`badge ${result.severity}`}>{result.severity}</span>}
            {result.priority != null && <span className="badge status">P{result.priority}</span>}
            {result.status && <span className="badge status">{result.status}</span>}
          </div>

          <dl className="kv">
            {result.defect_id && (<><dt>Defect ID</dt><dd>{result.defect_id}</dd></>)}
            {result.assigned_team && (<><dt>Team</dt><dd>{result.assigned_team}</dd></>)}
            {result.assigned_to && (<><dt>Assignee</dt><dd>{result.assigned_to}</dd></>)}
            {result.category && (<><dt>Category</dt><dd>{result.category}</dd></>)}
            {result.component && (<><dt>Component</dt><dd>{result.component}</dd></>)}
            {result.root_cause && (<><dt>Root cause</dt><dd>{result.root_cause}</dd></>)}
          </dl>

          {Array.isArray(result.triage_notes) && result.triage_notes.length > 0 && (
            <>
              <p className="notes-title">Audit trail</p>
              <ul className="notes">
                {result.triage_notes.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  )
}
