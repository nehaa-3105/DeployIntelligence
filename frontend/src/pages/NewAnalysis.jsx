import { useState, useEffect } from 'react'
import { analyzeDeployment, submitFeedback, getDeployments } from '../api.js'
import { OutcomeBadge, RiskBadge } from '../components/Badge.jsx'
import DetailDrawer from '../components/DetailDrawer.jsx'
import {
  IconPulse, IconBrain, IconAlertTriangle, IconCheckCircle,
  IconInfo, IconDatabase,
} from '../components/Icons.jsx'

// ── Helpers ──────────────────────────────────────────────────────────────────

const MIGRATION_TYPES = ['schema', 'read-replica', 'config-only', 'infra-only', 'code-only']
const CHANGE_TYPES    = ['infra', 'config', 'code', 'schema']

const DEFAULT_FORM = {
  deployment_id:          '297',
  service:                'payment-service',
  migration_type:         'schema',
  change_type:            'infra',
  connection_pool_change: true,
  dependencies_changed:   true,
}

function riskColor(level) {
  const l = level?.toLowerCase()
  if (l === 'high')              return 'var(--red)'
  if (l === 'medium' || l === 'moderate') return 'var(--amber)'
  return 'var(--green)'
}

function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch { return iso }
}

// ── Step indicator ────────────────────────────────────────────────────────────

const STEPS = [
  'Deployment Details',
  'Analysis Results',
  'Outcome & Learning',
  'Memory Updated',
]

function Stepper({ active }) {
  return (
    <div className="stepper" aria-label="Progress">
      {STEPS.map((label, i) => {
        const done = i < active
        const cur  = i === active
        return (
          <div key={label} className={`stepper-step${done ? ' done' : ''}${cur ? ' active' : ''}`}>
            <div className="stepper-dot">
              {done ? <IconCheckCircle size={12} color="#fff" /> : <span>{i + 1}</span>}
            </div>
            <span className="stepper-label">{label}</span>
            {i < STEPS.length - 1 && <div className="stepper-line" />}
          </div>
        )
      })}
    </div>
  )
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ title, sub }) {
  return (
    <div className="na-section-header">
      <h2 className="na-section-title">{title}</h2>
      {sub && <p className="na-section-sub">{sub}</p>}
    </div>
  )
}

// ── Deployment Details form ───────────────────────────────────────────────────

function DeploymentForm({ form, setForm, onSubmit, loading, services }) {
  function handleField(e) {
    const { name, value, type, checked } = e.target
    setForm(f => ({ ...f, [name]: type === 'checkbox' ? checked : value }))
  }

  return (
    <div className="na-card">
      <SectionHeader
        title="Deployment Details"
        sub="Describe the proposed deployment to analyse."
      />
      <form onSubmit={onSubmit} className="na-form-grid">
        <div className="na-field">
          <label htmlFor="na-dep-id">Deployment ID</label>
          <input id="na-dep-id" name="deployment_id" value={form.deployment_id}
            onChange={handleField} placeholder="297" />
        </div>

        <div className="na-field">
          <label htmlFor="na-service">Service</label>
          {/* Free-text with datalist — options from ledger */}
          <input id="na-service" name="service" value={form.service}
            onChange={handleField} list="na-service-list"
            placeholder="payment-service" required />
          <datalist id="na-service-list">
            {services.map(s => <option key={s} value={s} />)}
          </datalist>
        </div>

        <div className="na-field">
          <label htmlFor="na-migration">Migration Type</label>
          <select id="na-migration" name="migration_type" value={form.migration_type}
            onChange={handleField} required>
            {MIGRATION_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <div className="na-field">
          <label htmlFor="na-change">Change Type</label>
          <select id="na-change" name="change_type" value={form.change_type}
            onChange={handleField}>
            {CHANGE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <div className="na-field na-field--full">
          <label>Signals</label>
          <label className="na-toggle">
            <input type="checkbox" name="connection_pool_change"
              checked={form.connection_pool_change} onChange={handleField} />
            <span>Connection pool change</span>
            <span className="na-toggle-hint">Deployment modifies pool settings</span>
          </label>
          <label className="na-toggle">
            <input type="checkbox" name="dependencies_changed"
              checked={form.dependencies_changed ?? false} onChange={handleField} />
            <span>Dependencies changed</span>
            <span className="na-toggle-hint">Upstream/downstream services affected</span>
          </label>
        </div>

        <div className="na-form-actions">
          <button type="submit" className="btn-analyze" disabled={loading}>
            {loading
              ? <><span className="spinner" style={{ width: 16, height: 16 }} /> Analysing…</>
              : <><IconPulse size={16} /> Analyze Deployment</>}
          </button>
        </div>
      </form>
    </div>
  )
}

// ── Baseline panel ────────────────────────────────────────────────────────────

function BaselinePanel({ baseline }) {
  return (
    <div className="analysis-panel analysis-panel--baseline">
      <div className="analysis-panel-header">
        <span className="analysis-panel-label">Baseline</span>
        <RiskBadge level={baseline.risk_assessment} />
      </div>
      <p className="analysis-mode-note">Current deployment only — no historical memory</p>
      <div className="analysis-text-block">
        <div className="analysis-text-label">Summary</div>
        <p className="analysis-text">{baseline.summary}</p>
      </div>
      <div className="analysis-text-block">
        <div className="analysis-text-label">Recommendation</div>
        <p className="analysis-text">{baseline.recommendation}</p>
      </div>
    </div>
  )
}

// ── Memory panel hero ─────────────────────────────────────────────────────────

function MemoryHero({ memoryInformed }) {
  const ps = memoryInformed.pattern_summary
  const hasSimilar = ps && ps.total_similar > 0

  return (
    <div className="memory-hero">
      <div className="memory-hero-hindsight">
        <IconBrain size={16} color="#22d3ee" />
        <span>Hindsight</span>
      </div>
      {hasSimilar
        ? <p className="memory-hero-headline">I've seen this before.</p>
        : <p className="memory-hero-headline memory-hero-headline--none">No similar deployments in memory yet.</p>
      }
      {ps && hasSimilar && (
        <p className="memory-hero-sub">{ps.headline}</p>
      )}
    </div>
  )
}

// ── Memory-informed panel ─────────────────────────────────────────────────────

function MemoryPanel({ memoryInformed, memoryRecords, hindsightStatus }) {
  const ps = memoryInformed.pattern_summary

  return (
    <div className="analysis-panel analysis-panel--memory">
      <div className="analysis-panel-header">
        <span className="analysis-panel-label analysis-panel-label--memory">
          <IconBrain size={14} color="#22d3ee" />
          Memory-Informed
        </span>
        <RiskBadge level={memoryInformed.risk_assessment} />
      </div>

      <div className="memory-records-badge">
        <IconBrain size={13} color="#22d3ee" />
        Hindsight memory — {memoryRecords} deployment record{memoryRecords !== 1 ? 's' : ''}
      </div>

      {hindsightStatus === 'unavailable' && (
        <div className="na-warning">
          <IconAlertTriangle size={14} color="#f59e0b" />
          Hindsight unavailable — memory recall was skipped.
        </div>
      )}

      <MemoryHero memoryInformed={memoryInformed} />

      <div className="analysis-text-block">
        <div className="analysis-text-label">Summary</div>
        <p className="analysis-text">{memoryInformed.summary}</p>
      </div>
      <div className="analysis-text-block">
        <div className="analysis-text-label">Recommendation</div>
        <p className="analysis-text memory-recommendation">{memoryInformed.recommendation}</p>
      </div>

      {ps && (
        <div className="memory-stats-row">
          <div className="memory-stat">
            <span className="memory-stat-val">{ps.total_similar}</span>
            <span className="memory-stat-key">Similar</span>
          </div>
          <div className="memory-stat">
            <span className="memory-stat-val" style={{ color: 'var(--red)' }}>{ps.total_incidents}</span>
            <span className="memory-stat-key">Incidents</span>
          </div>
          <div className="memory-stat">
            <span className="memory-stat-val" style={{ color: 'var(--green)' }}>{ps.total_successes}</span>
            <span className="memory-stat-key">Successes</span>
          </div>
          <div className="memory-stat">
            <span className="memory-stat-val">{ps.confidence_label}</span>
            <span className="memory-stat-key">Confidence</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Recalled deployment card ──────────────────────────────────────────────────

function RecalledDeployment({ dep }) {
  const isIncident = dep.outcome === 'incident'
  const accentColor = isIncident ? 'var(--red)' : 'var(--green)'

  return (
    <div className="recalled-card" style={{ '--rc-accent': accentColor }}>
      <div className="recalled-card-accent" />
      <div className="recalled-card-body">
        <div className="recalled-header">
          <div>
            <span className="recalled-id">Deployment #{dep.deployment_id}</span>
            <span className="recalled-service"> · {dep.service}</span>
          </div>
          <OutcomeBadge outcome={dep.outcome} />
        </div>

        <div className="recalled-signals">
          <span className="recalled-signals-label">{dep.similarity_score}/5 signals</span>
          {dep.matched_signals?.map(s => (
            <span key={s} className="recalled-signal-chip">{s}</span>
          ))}
        </div>

        {dep.root_cause && (
          <div className="recalled-field">
            <span className="recalled-field-label">Root cause</span>
            <span className="recalled-field-value">{dep.root_cause}</span>
          </div>
        )}

        {dep.resolution && (
          <div className="recalled-field">
            <span className="recalled-field-label">Previous fix</span>
            <span className="recalled-field-value">{dep.resolution}</span>
          </div>
        )}

        {/* Hindsight evidence — only from API, never fabricated */}
        {dep.hindsight_status === 'recalled' && dep.hindsight_evidence?.length > 0 && (
          <div className="recalled-evidence">
            <div className="recalled-evidence-label">
              <IconBrain size={12} color="#22d3ee" />
              Recalled from Hindsight
            </div>
            {dep.hindsight_evidence.map((ev, i) => (
              <p key={i} className="recalled-evidence-text">{ev.text}</p>
            ))}
          </div>
        )}

        {dep.hindsight_status === 'empty' && (
          <div className="na-status-note">
            <IconInfo size={13} color="#9aa7b5" />
            No Hindsight evidence indexed yet for this deployment.
          </div>
        )}
        {dep.hindsight_status === 'unavailable' && (
          <div className="na-warning">
            <IconAlertTriangle size={13} color="#f59e0b" />
            Hindsight recall unavailable for this candidate.
          </div>
        )}
        {dep.hindsight_status === 'not_recalled' && (
          <div className="na-status-note">
            <IconInfo size={13} color="#9aa7b5" />
            Hindsight recall not attempted for this candidate.
          </div>
        )}
      </div>
    </div>
  )
}

// ── Historical table ──────────────────────────────────────────────────────────

function HistoricalTable({ candidates, signalLegend, onViewRecord }) {
  if (!candidates || candidates.length === 0) {
    return (
      <div className="state-empty">
        <IconDatabase size={28} color="#9aa7b5" />
        <p>No similar historical deployments found.</p>
      </div>
    )
  }

  return (
    <>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Outcome</th>
              <th>Service</th>
              <th>Signals</th>
              <th>Key Note</th>
              <th>View</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map(dep => (
              <tr key={dep.deployment_id}>
                <td className="td-id">#{dep.deployment_id}</td>
                <td><OutcomeBadge outcome={dep.outcome} /></td>
                <td>{dep.service}</td>
                <td>
                  <span className="signals-score">{dep.similarity_score}/5</span>
                  {dep.matched_signals?.slice(0, 3).map(s => (
                    <span key={s} className="recalled-signal-chip" style={{ fontSize: '.7rem' }}>{s}</span>
                  ))}
                </td>
                <td className="td-muted td-key-note">{dep.key_note || '—'}</td>
                <td>
                  <button className="btn-view" onClick={() => onViewRecord(dep)}
                    aria-label={`View deployment #${dep.deployment_id}`}>
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Signal legend — from API, not hardcoded */}
      {signalLegend?.length > 0 && (
        <div className="signal-legend">
          <div className="signal-legend-title">Signal legend</div>
          <div className="signal-legend-items">
            {signalLegend.map(s => (
              <div key={s.signal} className="signal-legend-item">
                <span className="signal-legend-key">{s.signal}</span>
                <span className="signal-legend-desc">{s.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

// ── Outcome panel ─────────────────────────────────────────────────────────────

function OutcomePanel({ form, onSubmit, loading, error }) {
  const [outcome,  setOutcome]  = useState(null)
  const [notes,    setNotes]    = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    if (!outcome) return
    onSubmit({ outcome, notes })
  }

  return (
    <div className="na-card">
      <SectionHeader
        title="Deployment Outcome & Learning"
        sub="Tell us how this deployment actually performed so the system can learn."
      />

      <form onSubmit={handleSubmit} className="outcome-form">
        <div className="outcome-options">
          <button
            type="button"
            className={`outcome-option outcome-option--success${outcome === 'success' ? ' selected' : ''}`}
            onClick={() => setOutcome('success')}
          >
            <IconCheckCircle size={20} color={outcome === 'success' ? '#fff' : '#22c55e'} />
            <div>
              <div className="outcome-option-label">Successful</div>
              <div className="outcome-option-desc">Deployment completed without issues.</div>
            </div>
          </button>

          <button
            type="button"
            className={`outcome-option outcome-option--incident${outcome === 'incident' ? ' selected' : ''}`}
            onClick={() => setOutcome('incident')}
          >
            <IconAlertTriangle size={20} color={outcome === 'incident' ? '#fff' : '#ef4444'} />
            <div>
              <div className="outcome-option-label">Incident</div>
              <div className="outcome-option-desc">Deployment caused an incident.</div>
            </div>
          </button>
        </div>

        <div className="outcome-notes">
          <label htmlFor="outcome-notes" className="outcome-notes-label">
            Notes <span className="outcome-notes-optional">(optional)</span>
          </label>
          <textarea
            id="outcome-notes"
            className="outcome-textarea"
            placeholder={outcome === 'incident'
              ? 'Describe what happened — this becomes the root cause stored in memory.'
              : 'Any observations about this deployment…'}
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={3}
          />
        </div>

        {error && (
          <div className="state-error" style={{ marginBottom: 12 }}>
            <strong>Could not record outcome</strong>
            <span>{error}</span>
          </div>
        )}

        <button
          type="submit"
          className="btn-submit-outcome"
          disabled={!outcome || loading}
        >
          {loading
            ? <><span className="spinner" style={{ width: 15, height: 15 }} /> Storing and indexing in Hindsight…</>
            : 'Submit Outcome'}
        </button>
      </form>
    </div>
  )
}

// ── Memory Updated card ───────────────────────────────────────────────────────

function MemoryUpdatedCard({ feedbackResult, onRerun, rerunLoading }) {
  const sm = feedbackResult.stored_memory

  return (
    <div className="na-card na-card--memory">
      <div className="memory-updated-header">
        <IconBrain size={20} color="#22d3ee" />
        <h3 className="memory-updated-title">Memory Updated</h3>
      </div>

      <div className="memory-count-row">
        <span className="memory-count">{feedbackResult.memory_records_before}</span>
        <span className="memory-count-arrow">→</span>
        <span className="memory-count memory-count--after">{feedbackResult.memory_records_after}</span>
        <span className="memory-count-label">deployment records in Hindsight</span>
      </div>

      {!feedbackResult.hindsight_indexed && (
        <div className="na-warning" style={{ marginBottom: 12 }}>
          <IconAlertTriangle size={14} color="#f59e0b" />
          Hindsight indexing in progress. Evidence will appear in the next analysis.
        </div>
      )}

      <div className="stored-memory-card">
        <div className="stored-memory-row">
          <span className="stored-memory-label">Deployment</span>
          <span className="stored-memory-val">#{sm.deployment_id}</span>
        </div>
        <div className="stored-memory-row">
          <span className="stored-memory-label">Service</span>
          <span className="stored-memory-val">{sm.service}</span>
        </div>
        <div className="stored-memory-row">
          <span className="stored-memory-label">Migration</span>
          <span className="stored-memory-val">{sm.migration_type}</span>
        </div>
        <div className="stored-memory-row">
          <span className="stored-memory-label">Change</span>
          <span className="stored-memory-val">{sm.change_type}</span>
        </div>
        <div className="stored-memory-row">
          <span className="stored-memory-label">Pool change</span>
          <span className="stored-memory-val">{sm.connection_pool_change ? 'Yes' : 'No'}</span>
        </div>
        <div className="stored-memory-row">
          <span className="stored-memory-label">Outcome</span>
          <span className="stored-memory-val"><OutcomeBadge outcome={sm.outcome} /></span>
        </div>
        {sm.lesson && (
          <div className="stored-memory-row stored-memory-row--lesson">
            <span className="stored-memory-label">Lesson</span>
            <span className="stored-memory-val">{sm.lesson}</span>
          </div>
        )}
        {sm.hindsight_evidence_preview && (
          <div className="stored-memory-row stored-memory-row--evidence">
            <span className="stored-memory-label">Hindsight preview</span>
            <span className="stored-memory-val stored-memory-val--evidence">
              {sm.hindsight_evidence_preview}
            </span>
          </div>
        )}
      </div>

      <p className="memory-learned">The system has learned from this deployment.</p>

      <button
        className="btn-rerun"
        onClick={onRerun}
        disabled={rerunLoading}
      >
        {rerunLoading
          ? <><span className="spinner" style={{ width: 15, height: 15 }} /> Running…</>
          : <>Re-run Analysis with Updated Memory →</>}
      </button>
    </div>
  )
}

// ── Before/After comparison ───────────────────────────────────────────────────

function diffValue(a, b) {
  if (a === b) return false
  return true
}

function ComparisonRow({ label, before, after }) {
  const changed = diffValue(String(before), String(after))
  return (
    <tr className={changed ? 'rerun-row--changed' : ''}>
      <td className="rerun-td-label">{label}</td>
      <td className="rerun-td-val">{before ?? '—'}</td>
      <td className={`rerun-td-val${changed ? ' rerun-val--new' : ''}`}>{after ?? '—'}</td>
    </tr>
  )
}

function RerunComparison({ firstResult, rerunResult }) {
  const fm = firstResult.memory_informed
  const rm = rerunResult.memory_informed
  const fps = fm.pattern_summary
  const rps = rm.pattern_summary

  // New evidence: IDs in rerun but not in first
  const firstIds  = new Set((fm.historical_deployments || []).map(d => d.deployment_id))
  const rerunIds  = new Set((rm.historical_deployments || []).map(d => d.deployment_id))
  const newIds    = [...rerunIds].filter(id => !firstIds.has(id))
  const newDeps   = (rm.historical_deployments || []).filter(d => newIds.includes(d.deployment_id))

  const incidentRateFirst = fps && fps.total_similar > 0
    ? `${Math.round((fps.total_incidents / fps.total_similar) * 100)}%` : '—'
  const incidentRateRerun = rps && rps.total_similar > 0
    ? `${Math.round((rps.total_incidents / rps.total_similar) * 100)}%` : '—'

  return (
    <div className="na-card">
      <SectionHeader
        title="Before / After Memory Update"
        sub="Changes highlighted in cyan."
      />
      <div className="table-wrap" style={{ marginBottom: 24 }}>
        <table className="data-table rerun-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>First Run</th>
              <th>After Memory Update</th>
            </tr>
          </thead>
          <tbody>
            <ComparisonRow label="Similar deployments" before={fps?.total_similar} after={rps?.total_similar} />
            <ComparisonRow label="Incidents" before={fps?.total_incidents} after={rps?.total_incidents} />
            <ComparisonRow label="Successes" before={fps?.total_successes} after={rps?.total_successes} />
            <ComparisonRow label="Incident rate" before={incidentRateFirst} after={incidentRateRerun} />
            <ComparisonRow label="Risk level" before={fm.risk_assessment} after={rm.risk_assessment} />
            <ComparisonRow label="Confidence" before={fps?.confidence_label} after={rps?.confidence_label} />
          </tbody>
        </table>
      </div>

      {newDeps.length > 0 && (
        <>
          <div className="rerun-new-evidence-label">
            <IconBrain size={14} color="#22d3ee" />
            New evidence ({newDeps.length} deployment{newDeps.length !== 1 ? 's' : ''} added to memory)
          </div>
          {newDeps.map(dep => (
            <RecalledDeployment key={dep.deployment_id} dep={dep} />
          ))}
        </>
      )}

      {newDeps.length === 0 && (
        <div className="na-status-note">
          <IconInfo size={14} color="#9aa7b5" />
          No new deployments added to similar candidates after memory update.
        </div>
      )}
    </div>
  )
}

// ── Updated Memory-Informed result ────────────────────────────────────────────

function UpdatedResult({ rerunResult }) {
  const m = rerunResult.memory_informed
  const [drawerDep, setDrawerDep] = useState(null)

  return (
    <>
      <div className="na-panels-row">
        <BaselinePanel baseline={rerunResult.baseline} />
        <MemoryPanel
          memoryInformed={m}
          memoryRecords={rerunResult.memory_records}
          hindsightStatus={rerunResult.hindsight_status}
        />
      </div>

      {m.historical_deployments?.slice(0, 2).map(dep => (
        <RecalledDeployment key={dep.deployment_id} dep={dep} />
      ))}

      <HistoricalTable
        candidates={m.historical_deployments}
        signalLegend={rerunResult.signal_legend}
        onViewRecord={dep => setDrawerDep({
          deployment_id: dep.deployment_id,
          service: dep.service,
          migration_type: dep.migration_type,
          change_type: dep.change_type,
          outcome: dep.outcome,
          timestamp: dep.timestamp,
          root_cause: dep.root_cause,
          resolution: dep.resolution,
          notes: dep.key_note,
        })}
      />

      {drawerDep && (
        <DetailDrawer record={drawerDep} onClose={() => setDrawerDep(null)} />
      )}
    </>
  )
}

// ── Main NewAnalysis page ─────────────────────────────────────────────────────

export default function NewAnalysis({
  form, setForm,
  analysisResult, setAnalysisResult,
  firstSnapshot, setFirstSnapshot,
  feedbackResult, setFeedbackResult,
  rerunResult, setRerunResult,
}) {
  const [services,        setServices]        = useState([])
  const [analyzeLoading,  setAnalyzeLoading]  = useState(false)
  const [analyzeError,    setAnalyzeError]    = useState(null)
  const [feedbackLoading, setFeedbackLoading] = useState(false)
  const [feedbackError,   setFeedbackError]   = useState(null)
  const [rerunLoading,    setRerunLoading]    = useState(false)
  const [drawerDep,       setDrawerDep]       = useState(null)

  // Load services for datalist from Deployments API
  useEffect(() => {
    getDeployments()
      .then(rows => {
        // Build service list for datalist
        const unique = [...new Set(rows.map(r => r.service).filter(Boolean))]
        setServices(unique.sort())

        // Compute default deployment ID:
        // Use "297" if #297 has no recorded outcome (not in ledger, or outcome is
        // "pending"/absent). Otherwise use max(existing numeric IDs) + 1.
        const rec297 = rows.find(r => r.deployment_id === '297')
        const has297Known = rec297 &&
          rec297.outcome &&
          rec297.outcome !== 'pending'

        let defaultId
        if (!has297Known) {
          defaultId = '297'
        } else {
          const numericIds = rows
            .map(r => parseInt(r.deployment_id, 10))
            .filter(n => !isNaN(n))
          const maxId = numericIds.length > 0 ? Math.max(...numericIds) : 0
          defaultId = String(maxId + 1)
        }

        // Only overwrite the form ID if it still holds the mount-time initial
        // value (i.e. the user has not already changed it before the API responded).
        setForm(f =>
          f.deployment_id === DEFAULT_FORM.deployment_id
            ? { ...f, deployment_id: defaultId }
            : f
        )
      })
      .catch(() => {})
  }, [])

  // Determine the stepper step
  let stepperActive = 0
  if (rerunResult)    stepperActive = 3
  else if (feedbackResult) stepperActive = 3
  else if (analysisResult) stepperActive = 1

  // ── Analyze ──────────────────────────────────────────────────────────────
  async function handleAnalyze(e) {
    e.preventDefault()
    if (!form.service.trim()) { setAnalyzeError('Service is required.'); return }
    setAnalyzeLoading(true)
    setAnalyzeError(null)
    setAnalysisResult(null)
    setFirstSnapshot(null)
    setFeedbackResult(null)
    setRerunResult(null)
    try {
      const payload = {
        deployment_id:          form.deployment_id,
        service:                form.service.trim(),
        migration_type:         form.migration_type,
        connection_pool_change: form.connection_pool_change,
        change_type:            form.change_type,
        dependencies_changed:   form.dependencies_changed,
        rerun:                  false,
      }
      const data = await analyzeDeployment(payload)
      setAnalysisResult(data)
      setFirstSnapshot(data)
    } catch (err) {
      setAnalyzeError(err.message)
    } finally {
      setAnalyzeLoading(false)
    }
  }

  // ── Feedback ──────────────────────────────────────────────────────────────
  async function handleFeedback({ outcome, notes }) {
    setFeedbackLoading(true)
    setFeedbackError(null)
    try {
      const payload = {
        deployment_id:          form.deployment_id,
        outcome,
        notes,
        service:                form.service.trim(),
        migration_type:         form.migration_type,
        change_type:            form.change_type,
        connection_pool_change: form.connection_pool_change,
        dependencies_changed:   form.dependencies_changed,
      }
      const data = await submitFeedback(payload)
      setFeedbackResult(data)
    } catch (err) {
      setFeedbackError(err.message)
    } finally {
      setFeedbackLoading(false)
    }
  }

  // ── Re-run ────────────────────────────────────────────────────────────────
  async function handleRerun() {
    setRerunLoading(true)
    try {
      const payload = {
        deployment_id:          form.deployment_id,
        service:                form.service.trim(),
        migration_type:         form.migration_type,
        connection_pool_change: form.connection_pool_change,
        change_type:            form.change_type,
        dependencies_changed:   form.dependencies_changed,
        rerun:                  true,
      }
      const data = await analyzeDeployment(payload)
      setRerunResult(data)
    } catch (err) {
      setFeedbackError(err.message)
    } finally {
      setRerunLoading(false)
    }
  }

  function openDrawer(dep) {
    setDrawerDep({
      deployment_id: dep.deployment_id,
      service:       dep.service,
      migration_type: dep.migration_type,
      change_type:   dep.change_type,
      outcome:       dep.outcome,
      timestamp:     dep.timestamp,
      root_cause:    dep.root_cause,
      resolution:    dep.resolution,
      notes:         dep.key_note,
    })
  }

  return (
    <div className="page-content">
      <div className="page-header">
        <div>
          <h1 className="page-title">New Analysis</h1>
          <p className="page-subtitle">Analyze a proposed deployment using organisational memory.</p>
        </div>
      </div>

      <Stepper active={stepperActive} />

      {/* ── Deployment form ── */}
      <DeploymentForm
        form={form} setForm={setForm}
        onSubmit={handleAnalyze}
        loading={analyzeLoading}
        services={services}
      />

      {analyzeError && (
        <div className="state-error" style={{ marginTop: 16 }}>
          <strong>Analysis failed</strong>
          <span>{analyzeError}</span>
        </div>
      )}

      {analyzeLoading && (
        <div className="state-loading" style={{ marginTop: 24 }}>
          <div className="spinner" />
          <span>Running baseline and memory-informed analysis…</span>
        </div>
      )}

      {/* ── Analysis results ── */}
      {analysisResult && !analyzeLoading && (
        <>
          <div className="na-panels-row">
            <BaselinePanel baseline={analysisResult.baseline} />
            <MemoryPanel
              memoryInformed={analysisResult.memory_informed}
              memoryRecords={analysisResult.memory_records}
              hindsightStatus={analysisResult.hindsight_status}
            />
          </div>

          {/* Top 2 recalled deployments */}
          {analysisResult.memory_informed.historical_deployments?.slice(0, 2).map(dep => (
            <RecalledDeployment key={dep.deployment_id} dep={dep} />
          ))}

          {/* Historical table */}
          <div className="na-card">
            <SectionHeader title="Similar Historical Deployments" />
            {analysisResult.hindsight_status === 'unavailable' && (
              <div className="na-warning" style={{ marginBottom: 12 }}>
                <IconAlertTriangle size={14} color="#f59e0b" />
                Hindsight was unavailable during this analysis.
              </div>
            )}
            <HistoricalTable
              candidates={analysisResult.memory_informed.historical_deployments}
              signalLegend={analysisResult.signal_legend}
              onViewRecord={openDrawer}
            />
          </div>
        </>
      )}

      {/* ── Outcome feedback ── */}
      {analysisResult && !analyzeLoading && !feedbackResult && (
        <OutcomePanel
          form={form}
          onSubmit={handleFeedback}
          loading={feedbackLoading}
          error={feedbackError}
        />
      )}

      {/* ── Memory Updated ── */}
      {feedbackResult && !feedbackLoading && (
        <MemoryUpdatedCard
          feedbackResult={feedbackResult}
          onRerun={handleRerun}
          rerunLoading={rerunLoading}
        />
      )}

      {/* ── Re-run comparison ── */}
      {rerunResult && firstSnapshot && (
        <>
          <RerunComparison
            firstResult={firstSnapshot}
            rerunResult={rerunResult}
          />
          <div className="na-card">
            <SectionHeader
              title="Updated Memory-Informed Analysis"
              sub="Re-run result incorporating the newly recorded outcome."
            />
            <UpdatedResult rerunResult={rerunResult} />
          </div>
        </>
      )}

      {/* Detail drawer */}
      {drawerDep && (
        <DetailDrawer record={drawerDep} onClose={() => setDrawerDep(null)} />
      )}
    </div>
  )
}
