import { useState, useEffect } from 'react'
import { getMemoryOverview } from '../api.js'
import { RiskBadge, OutcomeBadge } from '../components/Badge.jsx'
import { IconSearch, IconAlertTriangle, IconCheckCircle, IconInfo, IconBrain } from '../components/Icons.jsx'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleDateString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric',
    })
  } catch {
    return iso
  }
}

function RiskIcon({ level }) {
  const l = level?.toLowerCase()
  if (l === 'high')     return <IconAlertTriangle size={18} color="#ef4444" />
  if (l === 'moderate') return <IconAlertTriangle size={18} color="#f59e0b" />
  return <IconCheckCircle size={18} color="#22c55e" />
}

function riskAccent(level) {
  const l = level?.toLowerCase()
  if (l === 'high')     return '#ef4444'
  if (l === 'moderate') return '#f59e0b'
  return '#22c55e'
}

// ── Patterns tab ─────────────────────────────────────────────────────────────

function PatternCard({ pattern }) {
  const accent = riskAccent(pattern.risk_label)
  return (
    <div className="pattern-card" style={{ '--accent-left': accent }}>
      <div className="pattern-card-accent" />
      <div className="pattern-card-body">
        <div className="pattern-card-header">
          <div className="pattern-risk-icon">
            <RiskIcon level={pattern.risk_label} />
          </div>
          <div className="pattern-card-meta">
            <div className="pattern-name">{pattern.name}</div>
            <div className="pattern-stats">
              Observed in {pattern.total} deployment{pattern.total !== 1 ? 's' : ''} —{' '}
              {pattern.incidents} caused incident{pattern.incidents !== 1 ? 's' : ''}
            </div>
          </div>
          <RiskBadge level={pattern.risk_label} />
        </div>

        <div className="pattern-details">
          <div className="pattern-detail-row">
            <span className="pattern-detail-label">Typical Trigger</span>
            <span className="pattern-detail-value">
              {pattern.typical_trigger || <em className="none-recorded">None recorded</em>}
            </span>
          </div>
          <div className="pattern-detail-row">
            <span className="pattern-detail-label">Impact</span>
            <span className="pattern-detail-value">
              {pattern.impact || <em className="none-recorded">None recorded</em>}
            </span>
          </div>
          <div className="pattern-detail-row">
            <span className="pattern-detail-label">Recommended Mitigation</span>
            <span className="pattern-detail-value">
              {pattern.mitigation || <em className="none-recorded">None recorded</em>}
            </span>
          </div>
        </div>

        {/* Evidence lineage */}
        <div className="pattern-lineage">
          <span className="pattern-lineage-label">Evidence lineage</span>
          <div className="pattern-lineage-chips">
            {pattern.source_deployments?.length > 0
              ? pattern.source_deployments.map(id => {
                  // Determine outcome chip color from ledger ID convention:
                  // We only know the IDs here; use neutral chip with ID label.
                  return (
                    <span key={id} className="lineage-chip">#{id}</span>
                  )
                })
              : <em className="none-recorded">No source deployments</em>
            }
          </div>

          {pattern.learned_from_feedback && (
            <span className="lineage-feedback-badge">
              Learned from feedback
            </span>
          )}

          {pattern.last_updated && (
            <span className="pattern-updated">Updated {fmtDate(pattern.last_updated)}</span>
          )}
        </div>
      </div>
    </div>
  )
}

function PatternsTab({ patterns, query }) {
  const q = query.trim().toLowerCase()
  const filtered = q
    ? patterns.filter(p =>
        p.name?.toLowerCase().includes(q) ||
        p.typical_trigger?.toLowerCase().includes(q) ||
        p.mitigation?.toLowerCase().includes(q)
      )
    : patterns

  // Sort highest incident rate first (already sorted by API but keep safe)
  const sorted = [...filtered].sort((a, b) => {
    const ra = a.total > 0 ? a.incidents / a.total : 0
    const rb = b.total > 0 ? b.incidents / b.total : 0
    return rb - ra
  })

  if (sorted.length === 0) {
    return (
      <div className="state-empty">
        <IconInfo size={28} color="#9aa7b5" />
        <p>{q ? `No patterns match "${q}".` : 'No patterns recorded yet.'}</p>
      </div>
    )
  }

  return (
    <div className="patterns-list">
      {sorted.map(p => <PatternCard key={p.key} pattern={p} />)}
    </div>
  )
}

// ── Lessons tab ──────────────────────────────────────────────────────────────

function LessonsTab({ lessons, query }) {
  const q = query.trim().toLowerCase()
  const filtered = q
    ? lessons.filter(l =>
        l.deployment_id?.toLowerCase().includes(q) ||
        l.lesson?.toLowerCase().includes(q)        ||
        l.service?.toLowerCase().includes(q)
      )
    : lessons

  if (filtered.length === 0) {
    return (
      <div className="state-empty">
        <IconInfo size={28} color="#9aa7b5" />
        <p>{q ? `No lessons match "${q}".` : 'No lessons recorded yet.'}</p>
      </div>
    )
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Lesson</th>
            <th>Service</th>
            <th>Outcome</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(l => (
            <tr key={`${l.deployment_id}-${l.recorded_at}`}>
              <td className="td-id">#{l.deployment_id}</td>
              <td className="td-lesson">{l.lesson}</td>
              <td>{l.service}</td>
              <td><OutcomeBadge outcome={l.outcome} /></td>
              <td className="td-muted">{fmtDate(l.recorded_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── By Service tab ────────────────────────────────────────────────────────────

function ByServiceTab({ byService, query }) {
  const q = query.trim().toLowerCase()
  const filtered = q
    ? byService.filter(s => s.service?.toLowerCase().includes(q))
    : byService

  if (filtered.length === 0) {
    return (
      <div className="state-empty">
        <IconInfo size={28} color="#9aa7b5" />
        <p>{q ? `No services match "${q}".` : 'No service data recorded yet.'}</p>
      </div>
    )
  }

  return (
    <div className="by-service-list">
      {filtered.map(s => {
        const incidentRate = s.total > 0 ? s.incidents / s.total : 0
        const barColor = incidentRate >= 0.67 ? '#ef4444' : incidentRate >= 0.33 ? '#f59e0b' : '#22c55e'
        return (
          <div key={s.service} className="service-row">
            <div className="service-row-name">{s.service}</div>
            <div className="service-row-stats">
              <span className="service-stat-total">{s.total} deployments</span>
              <span className="service-stat-inc" style={{ color: '#ef4444' }}>
                {s.incidents} incident{s.incidents !== 1 ? 's' : ''}
              </span>
              <span className="service-stat-suc" style={{ color: '#22c55e' }}>
                {s.successes} success{s.successes !== 1 ? 'es' : ''}
              </span>
            </div>
            <div className="service-row-bar-wrap">
              <div
                className="service-row-bar"
                style={{ width: `${Math.round(incidentRate * 100)}%`, background: barColor }}
              />
            </div>
            <div className="service-row-ids">
              {s.deployment_ids?.map(id => (
                <span key={id} className="lineage-chip">#{id}</span>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

const TABS = ['Patterns', 'Lessons', 'By Service']

export default function OrganisationalMemory() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [tab,     setTab]     = useState('Patterns')
  const [query,   setQuery]   = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getMemoryOverview()
      .then(d => { if (!cancelled) setData(d) })
      .catch(e => { if (!cancelled) setError(e.message) })
      .finally(()=> { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="page-content">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Organisational Memory</h1>
          <p className="page-subtitle">Patterns and lessons learned from past deployments.</p>
        </div>
        {/* Search (top-right) */}
        <div className="search-bar search-bar--inline">
          <span className="search-icon"><IconSearch size={15} color="#9aa7b5" /></span>
          <input
            className="search-input"
            placeholder="Search patterns, services..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            aria-label="Search patterns and services"
          />
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="state-loading">
          <div className="spinner" />
          <span>Loading organisational memory…</span>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="state-error">
          <strong>Failed to load memory overview</strong>
          <span>{error}</span>
        </div>
      )}

      {/* Content */}
      {!loading && !error && data && (
        <>
          {/* Tabs */}
          <div className="tabs">
            {TABS.map(t => (
              <button
                key={t}
                className={`tab-btn${tab === t ? ' tab-btn--active' : ''}`}
                onClick={() => setTab(t)}
              >
                {t}
                {t === 'Patterns' && data.patterns?.length > 0 &&
                  <span className="tab-count">{data.patterns.length}</span>}
                {t === 'Lessons' && data.lessons?.length > 0 &&
                  <span className="tab-count">{data.lessons.length}</span>}
              </button>
            ))}
          </div>

          <div className="tab-content">
            {tab === 'Patterns'   && <PatternsTab  patterns={data.patterns   ?? []} query={query} />}
            {tab === 'Lessons'    && <LessonsTab   lessons={data.lessons     ?? []} query={query} />}
            {tab === 'By Service' && <ByServiceTab byService={data.by_service ?? []} query={query} />}
          </div>

          {/* Footer */}
          <div className="memory-footer">
            <IconBrain size={14} color="#22d3ee" />
            <span>
              Backed by <strong>{data.memory_records}</strong> deployment record{data.memory_records !== 1 ? 's' : ''} retained in Hindsight
            </span>
          </div>
        </>
      )}
    </div>
  )
}
