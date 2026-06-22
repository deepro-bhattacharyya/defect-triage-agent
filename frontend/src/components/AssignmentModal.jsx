import { useEffect, useState } from 'react'

// Human-in-the-loop assignee picker. Shown when the graph pauses at assign_defect
// (assignment_required). Confirm resumes the triage with the chosen assignee.
export default function AssignmentModal({ assignment, onConfirm }) {
  const [choice, setChoice] = useState('')

  useEffect(() => {
    // default to the first candidate whenever a new assignment appears
    setChoice(assignment?.candidates?.[0] || '')
  }, [assignment])

  if (!assignment) return null

  return (
    <div className="modal-overlay">
      <div className="modal assign" role="dialog" aria-modal="true">
        <h3>👤 Choose an assignee — {assignment.team}</h3>
        <p>Triage paused. Pick who should own this defect, then continue.</p>
        <div className="candidates">
          {assignment.candidates.map((c) => (
            <label key={c} className="candidate">
              <input type="radio" name="assignee" value={c}
                checked={choice === c} onChange={() => setChoice(c)} />
              <span>{c}</span>
            </label>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" disabled={!choice} onClick={() => onConfirm(choice)}>
            Assign &amp; continue
          </button>
        </div>
      </div>
    </div>
  )
}
