/**
 * Badge.jsx — outcome and risk badge components.
 * Colors come from CSS variables matching the steering file design tokens.
 */

export function OutcomeBadge({ outcome }) {
  const map = {
    incident: { label: 'Incident',  cls: 'badge-incident' },
    success:  { label: 'Success',   cls: 'badge-success'  },
    pending:  { label: 'Analyzed',  cls: 'badge-analyzed' },
  }
  const { label, cls } = map[outcome?.toLowerCase()] ?? { label: outcome ?? '—', cls: 'badge-neutral' }
  return <span className={`outcome-badge ${cls}`}>{label}</span>
}

export function RiskBadge({ level }) {
  const map = {
    high:     { label: 'High',     cls: 'risk-badge-high'     },
    moderate: { label: 'Moderate', cls: 'risk-badge-moderate' },
    medium:   { label: 'Medium',   cls: 'risk-badge-moderate' },
    low:      { label: 'Low',      cls: 'risk-badge-low'      },
  }
  const { label, cls } = map[level?.toLowerCase()] ?? { label: level ?? '—', cls: 'risk-badge-low' }
  return <span className={`risk-badge-pill ${cls}`}>{label}</span>
}
