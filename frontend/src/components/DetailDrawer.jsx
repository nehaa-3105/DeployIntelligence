import { IconX } from './Icons.jsx'
import { OutcomeBadge } from './Badge.jsx'

/**
 * DetailDrawer — slide-in panel showing a single deployment record.
 * Uses already-loaded row data; makes no additional API calls.
 */
export default function DetailDrawer({ record, onClose }) {
  if (!record) return null

  function fmt(v) {
    if (v === null || v === undefined || v === '') return <span className="drawer-empty">—</span>
    if (typeof v === 'boolean') return v ? 'Yes' : 'No'
    return String(v)
  }

  const fields = [
    { label: 'Deployment ID',    value: record.deployment_id },
    { label: 'Service',          value: record.service },
    { label: 'Migration Type',   value: record.migration_type },
    { label: 'Change Type',      value: record.change_type },
    { label: 'Outcome',          value: <OutcomeBadge outcome={record.outcome} /> },
    { label: 'Date',             value: record.timestamp ? fmtDate(record.timestamp) : null },
    { label: 'Root Cause',       value: record.root_cause },
    { label: 'Resolution',       value: record.resolution },
    { label: 'Notes',            value: record.notes },
  ]

  return (
    <>
      {/* Backdrop */}
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />

      {/* Panel */}
      <div className="drawer" role="dialog" aria-modal="true"
        aria-label={`Deployment #${record.deployment_id} details`}>
        <div className="drawer-header">
          <div>
            <p className="drawer-label">Deployment</p>
            <h2 className="drawer-title">#{record.deployment_id}</h2>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close">
            <IconX size={18} />
          </button>
        </div>

        <div className="drawer-body">
          {fields.map(({ label, value }) => (
            <div key={label} className="drawer-field">
              <span className="drawer-field-label">{label}</span>
              <span className="drawer-field-value">{fmt(value)}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric',
    })
  } catch {
    return iso
  }
}
