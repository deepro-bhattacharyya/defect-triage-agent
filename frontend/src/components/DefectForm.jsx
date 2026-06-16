import { useState } from 'react'

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

export default function DefectForm({ onSubmit, loading }) {
  const [fields, setFields] = useState(EMPTY)
  const [imageFile, setImageFile] = useState(null)

  function update(key) {
    return (e) => setFields((f) => ({ ...f, [key]: e.target.value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const payload = { ...fields }
    payload.image_attachments = imageFile ? [await fileToAttachment(imageFile)] : []
    onSubmit(payload)
  }

  return (
    <section className="card">
      <h2>Submit a defect</h2>
      <form onSubmit={handleSubmit}>
        <label>
          Title <span className="req">*</span>
          <input
            type="text"
            required
            value={fields.title}
            onChange={update('title')}
            placeholder="Applying a promo code at checkout causes a 500 error"
          />
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
            <input
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(e) => setImageFile(e.target.files[0] || null)}
            />
          </label>
        </div>

        <div className="actions">
          <button type="submit" disabled={loading}>
            {loading ? 'Triaging…' : 'Triage defect'}
          </button>
          <button
            type="button"
            className="ghost"
            disabled={loading}
            onClick={() => { setFields(SAMPLE_DUPLICATE); setImageFile(null) }}
          >
            Load sample (duplicate)
          </button>
        </div>
      </form>
    </section>
  )
}
