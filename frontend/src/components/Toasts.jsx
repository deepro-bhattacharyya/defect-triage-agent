// Dismissible toast banners for non-fatal warnings (e.g. a Jira write failed but
// triage still completed). Each toast carries an id and a message.
export default function Toasts({ toasts, onDismiss }) {
  if (!toasts.length) return null
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div key={t.id} className="toast">
          <span>⚠️ {t.message}</span>
          <button type="button" className="toast-x" onClick={() => onDismiss(t.id)} aria-label="Dismiss">
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
