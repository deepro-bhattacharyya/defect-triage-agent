// Blocking modal for fatal errors (e.g. Gemini quota exhausted, missing API key).
export default function ErrorModal({ message, onClose }) {
  if (!message) return null
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" role="alertdialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>⚠️ Something needs attention</h3>
        <p>{message}</p>
        <div className="modal-actions">
          <button type="button" onClick={onClose}>Dismiss</button>
        </div>
      </div>
    </div>
  )
}
