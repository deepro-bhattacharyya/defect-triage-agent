import { useState } from 'react'
import { fetchJiraIssue } from '../api.js'

const EMPTY = {
  title: '',
  defect_id: '',
  environment: '',
  description: '',
  stack_trace: '',
  reporter: '',
}

const SAMPLE_DUPLICATE = {
  title: 'Applying a promo code at checkout causes a 500 error',
  defect_id: 'DEF-901',
  environment: 'production',
  description: 'Used a valid discount code at checkout and got a 500 error, and my cart emptied out.',
  stack_trace: '',
  reporter: 'customer-support',
}

// Read an image File into the {media_type, data(base64)} shape the API expects.
function fileToAttachment(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const base64 = String(reader.result).split(',')[1] // strip "data:...;base64,"
      resolve({ media_type: file.type, data: base64 })
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

// jiraConnected (Task 1): when true the primary input is a Jira ID + Fetch button
// that auto-populates every field; the manual form is the fallback when Jira is down.
export default function DefectForm({ onSubmit, loading, jiraConnected }) {
  const [fields, setFields] = useState(EMPTY)
  const [jiraImages, setJiraImages] = useState([]) // attachments pulled from Jira
  const [imageFile, setImageFile] = useState(null) // optional manual screenshot
  const [jiraId, setJiraId] = useState('')
  const [fetching, setFetching] = useState(false)
  const [fetchError, setFetchError] = useState(null)
  const [sourceJiraKey, setSourceJiraKey] = useState('') // set when fetched from Jira → write-back

  function update(key) {
    return (e) => setFields((f) => ({ ...f, [key]: e.target.value }))
  }

  async function handleFetch() {
    if (!jiraId.trim()) return
    setFetching(true)
    setFetchError(null)
    setJiraImages([])
    try {
      const d = await fetchJiraIssue(jiraId.trim())
      setFields({
        title: d.title || '',
        defect_id: d.defect_id || '',
        environment: d.environment || '',
        description: d.description || '',
        stack_trace: d.stack_trace || '',
        reporter: d.reporter || '',
      })
      setJiraImages(d.image_attachments || [])
      setSourceJiraKey(d.defect_id || jiraId.trim()) // mark as Jira-sourced → write-back
    } catch (e) {
      setFetchError(e.message)
    } finally {
      setFetching(false)
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const manual = imageFile ? [await fileToAttachment(imageFile)] : []
    onSubmit({
      ...fields,
      image_attachments: [...jiraImages, ...manual],
      source_jira_key: sourceJiraKey,
    })
  }

  return (
    <section className="card">
      <h2>Submit a defect</h2>

      {jiraConnected ? (
        <div className="jira-fetch">
          <label>
            Jira defect ID
            <div className="fetch-row">
              <input
                type="text"
                value={jiraId}
                onChange={(e) => setJiraId(e.target.value)}
                placeholder="SCRUM-42"
              />
              <button type="button" onClick={handleFetch} disabled={fetching || loading}>
                {fetching ? 'Fetching…' : 'Fetch'}
              </button>
            </div>
          </label>
          {fetchError && <div className="error">{fetchError}</div>}
          {jiraImages.length > 0 && (
            <div className="hint">📎 {jiraImages.length} image(s) pulled from Jira</div>
          )}
          <p className="hint">Fetched fields below are editable before you triage.</p>
        </div>
      ) : (
        <div className="hint">Jira not connected — enter the defect manually.</div>
      )}

      <form onSubmit={handleSubmit}>
        <label>
          Title <span className="req">*</span>
          <input type="text" required value={fields.title} onChange={update('title')}
            placeholder="Applying a promo code at checkout causes a 500 error" />
        </label>

        <div className="row">
          <label>
            Defect ID
            <input type="text" value={fields.defect_id} onChange={update('defect_id')} placeholder="DEF-901" />
          </label>
          <label>
            Environment
            <select value={fields.environment} onChange={update('environment')}>
              <option value="">—</option>
              <option value="production">production</option>
              <option value="staging">staging</option>
              <option value="development">development</option>
              <option value="test">test</option>
            </select>
          </label>
        </div>

        <label>
          Description
          <textarea rows="3" value={fields.description} onChange={update('description')}
            placeholder="What happened, steps to reproduce, impact…" />
        </label>

        <label>
          Stack trace
          <textarea rows="2" value={fields.stack_trace} onChange={update('stack_trace')} placeholder="(optional)" />
        </label>

        <div className="row">
          <label>
            Reporter
            <input type="text" value={fields.reporter} onChange={update('reporter')} placeholder="customer-support" />
          </label>
          <label>
            Screenshot (optional)
            <input type="file" accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(e) => setImageFile(e.target.files[0] || null)} />
          </label>
        </div>

        <div className="actions">
          <button type="submit" disabled={loading}>
            {loading ? 'Triaging…' : 'Triage defect'}
          </button>
          <button type="button" className="ghost" disabled={loading}
            onClick={() => { setFields(SAMPLE_DUPLICATE); setImageFile(null); setJiraImages([]); setSourceJiraKey('') }}>
            Load sample (duplicate)
          </button>
        </div>
      </form>
    </section>
  )
}
