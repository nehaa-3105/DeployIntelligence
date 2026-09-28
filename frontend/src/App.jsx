import { useState } from 'react'
import { analyzeDeployment, submitFeedback } from './api.js'

// ── Risk badge ──────────────────────────────────────────────────────────────
function RiskBadge({ level }) {
  const cls = {
    high:   'risk-badge risk-high',
    medium: 'risk-badge risk-medium',
    low:    'risk-badge risk-low',
  }[level?.toLowerCase()] ?? 'risk-badge risk-medium'

  const icon = { high: '⚠', medium: '◆', low: '✓' }[level?.toLowerCase()] ?? '◆'

  return (
    <span className={cls}>
      {icon} {level?.toUpperCase() ?? '—'} RISK
    </span>
  )
}

// ── Historical deployment card ───────────────────────────────────────────────
function DeploymentCard({ dep }) {
  const outcomeClass = dep.outcome === 'incident' ? 'outcome-incident' : 'outcome-success'

  return (
    <div className="deployment-card">
      <div className="dep-header">
        <span className="dep-id">Deployment #{dep.deployment_id}</span>
        <span className={`dep-outcome ${outcomeClass}`}>{dep.outcome}</span>
      </div>

      <div className="dep-field">
        <strong>Service:</strong> {dep.service}
      </div>
      <div className="dep-field">
        <strong>Migration:</strong> {dep.migration_type}
      </div>
      <div className="dep-field">
        <strong>Pool change:</strong> {dep.connection_pool_change ? 'Yes' : 'No'}
      </div>
      <div className="dep-field">
        <strong>Similarity:</strong> {dep.similarity_score}/5 signals matched
      </div>

      {dep.matched_signals?.length > 0 && (
        <div className="signal-chips">
          {dep.matched_signals.map(s => (
            <span key={s} className="chip">{s}</span>
          ))}
        </div>
      )}

      {dep.hindsight_evidence?.length > 0 && (
        <div className="evidence-block">
          {dep.hindsight_evidence.map((txt, i) => (
            <p key={i}>{txt}</p>
          ))}
        </div>
      )}

      {/* For deployment #184 with no hindsight evidence yet, show known facts */}
      {dep.deployment_id === '184' && dep.outcome === 'incident' &&
        dep.hindsight_evidence?.length === 0 && (
        <div className="evidence-block">
          <p>Root cause: connection pool exhaustion under post-migration traffic spike.</p>
          <p>Resolution: staged rollout with connection pool size monitoring.</p>
          <p>Recovery time: 18 minutes.</p>
        </div>
      )}
    </div>
  )
}

// ── Analysis panel ───────────────────────────────────────────────────────────
function AnalysisPanel({ result, side }) {
  const isMemory = side === 'memory'

  return (
    <div className="card">
      <div className="card-title">
        {isMemory ? 'Memory-Informed Analysis' : 'Baseline Analysis'}
        <span className={`badge ${isMemory ? 'badge-memory' : 'badge-baseline'}`}>
          {isMemory ? 'memory' : 'baseline'}
        </span>
      </div>

      <div className={`mode-callout ${isMemory ? 'memory-callout' : ''}`}>
        {isMemory
          ? '⟳ Current deployment + relevant organisational memory'
          : '○ Current deployment only — no historical memory used'}
      </div>

      <RiskBadge level={result.risk_level} />

      <div className="analysis-section">
        <h4>Summary</h4>
        <p>{result.reasoning}</p>
      </div>

      <hr className="divider" />

      <div className="analysis-section">
        <h4>Recommendation</h4>
        <p>{result.recommendation}</p>
      </div>

      {isMemory && (
        <>
          <hr className="divider" />
          <div className="evidence-header">
            Historical Evidence ({result.historical_deployments?.length ?? 0} similar deployment
            {result.historical_deployments?.length !== 1 ? 's' : ''})
          </div>

          {result.historical_deployments?.length > 0
            ? result.historical_deployments.map(dep => (
                <DeploymentCard key={dep.deployment_id} dep={dep} />
              ))
            : (
              <p className="no-history">
                No sufficiently similar historical deployments found in memory.
              </p>
            )
          }
        </>
      )}
    </div>
  )
}

// ── Feedback section ─────────────────────────────────────────────────────────
function FeedbackSection({ deploymentInfo, onFeedbackSent }) {
  const [selected, setSelected] = useState(null)   // 'success' | 'incident'
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit() {
    if (!selected) return
    setSubmitting(true)
    setError(null)
    try {
      await submitFeedback({
        deployment_id:        deploymentInfo.deployment_id,
        outcome:              selected,
        service:              deploymentInfo.service,
        migration_type:       deploymentInfo.migration_type,
        connection_pool_change: deploymentInfo.connection_pool_change,
        root_cause:           selected === 'incident'
                                ? 'Outcome reported via UI'
                                : '',
        resolution:           '',
        recovery_time_minutes: 0,
      })
      setDone(true)
      onFeedbackSent?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card">
      <div className="card-title">Deployment Outcome</div>

      {done ? (
        <div className="success-box">
          ✓ Outcome recorded as <strong>{selected}</strong> for deployment
          #{deploymentInfo.deployment_id}. Future analyses will reflect this result.
        </div>
      ) : (
        <>
          <p style={{ color: 'var(--text-muted)', fontSize: '.9rem', marginBottom: '4px' }}>
            How did this deployment actually perform?
          </p>

          <div className="feedback-row">
            <button
              className={`btn-success ${selected === 'success' ? 'selected' : ''}`}
              onClick={() => setSelected('success')}
              disabled={submitting}
            >
              ✓ Successful
            </button>
            <button
              className={`btn-danger ${selected === 'incident' ? 'selected' : ''}`}
              onClick={() => setSelected('incident')}
              disabled={submitting}
            >
              ✗ Incident
            </button>

            {selected && (
              <button
                className="btn-primary"
                onClick={handleSubmit}
                disabled={submitting}
              >
                {submitting ? 'Saving…' : 'Submit Outcome'}
              </button>
            )}
          </div>

          {error && (
            <div className="error-box" style={{ marginTop: '12px' }}>
              <strong>Failed to record outcome</strong>{error}
            </div>
          )}

          {selected && !submitting && (
            <p className="feedback-note">
              Submitting <strong>{selected}</strong> for deployment #{deploymentInfo.deployment_id}.
              This calls the Phase 5 feedback function and stores the result in organisational memory.
            </p>
          )}
        </>
      )}
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────────────────
const MIGRATION_TYPES = [
  'schema',
  'read-replica',
  'config-only',
  'infra-only',
  'code-only',
]

const CHANGE_TYPES = ['infra', 'config', 'code', 'schema']

const DEMO_DEFAULTS = {
  deployment_id:        '297',
  service:              'payment-service',
  migration_type:       'schema',
  connection_pool_change: true,
  change_type:          'infra',
  dependencies_changed: true,
}

export default function App() {
  // Form state — pre-filled with the #297 demo values
  const [form, setForm] = useState(DEMO_DEFAULTS)

  // Analysis state
  const [loading, setLoading]   = useState(false)
  const [result,  setResult]    = useState(null)   // { deployment_id, baseline, memory_informed }
  const [error,   setError]     = useState(null)

  function handleField(e) {
    const { name, value, type, checked } = e.target
    setForm(f => ({
      ...f,
      [name]: type === 'checkbox' ? checked : value,
    }))
  }

  async function handleAnalyze(e) {
    e.preventDefault()

    if (!form.service.trim()) {
      setError('Service name is required.')
      return
    }
    if (!form.migration_type) {
      setError('Migration type is required.')
      return
    }

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const data = await analyzeDeployment({
        deployment_id:        form.deployment_id,
        service:              form.service.trim(),
        migration_type:       form.migration_type,
        connection_pool_change: form.connection_pool_change,
        change_type:          form.change_type,
        dependencies_changed: form.dependencies_changed,
      })
      setResult(data)
    } catch (e) {
      if (e.message.includes('fetch') || e.message.includes('Failed to fetch')) {
        setError('Cannot reach the backend. Make sure the API is running on port 8000.')
      } else {
        setError(e.message)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      {/* ── Header ── */}
      <div className="header">
        <h1>Deployment Intelligence</h1>
        <p>Analyze a proposed deployment using organisational memory.</p>
      </div>

      {/* ── Input form ── */}
      <div className="card">
        <div className="card-title">Proposed Deployment</div>
        <form onSubmit={handleAnalyze}>
          <div className="form-grid">

            <div className="field">
              <label htmlFor="deployment_id">Deployment ID</label>
              <input
                id="deployment_id"
                name="deployment_id"
                value={form.deployment_id}
                onChange={handleField}
                placeholder="297"
              />
            </div>

            <div className="field">
              <label htmlFor="service">Service *</label>
              <input
                id="service"
                name="service"
                value={form.service}
                onChange={handleField}
                placeholder="payment-service"
                required
              />
            </div>

            <div className="field">
              <label htmlFor="migration_type">Migration Type *</label>
              <select
                id="migration_type"
                name="migration_type"
                value={form.migration_type}
                onChange={handleField}
                required
              >
                {MIGRATION_TYPES.map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="change_type">Change Type</label>
              <select
                id="change_type"
                name="change_type"
                value={form.change_type}
                onChange={handleField}
              >
                {CHANGE_TYPES.map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>

            <div className="field field-full">
              <label>Signals</label>
              <div className="toggle-row">
                <input
                  type="checkbox"
                  id="connection_pool_change"
                  name="connection_pool_change"
                  checked={form.connection_pool_change}
                  onChange={handleField}
                />
                <label htmlFor="connection_pool_change">
                  Connection pool change (deployment modifies pool settings)
                </label>
              </div>
              <div className="toggle-row" style={{ marginTop: 8 }}>
                <input
                  type="checkbox"
                  id="dependencies_changed"
                  name="dependencies_changed"
                  checked={form.dependencies_changed ?? false}
                  onChange={handleField}
                />
                <label htmlFor="dependencies_changed">
                  Dependencies changed (upstream/downstream services affected)
                </label>
              </div>
            </div>

            <div className="form-actions">
              <button
                type="submit"
                className="btn-primary"
                disabled={loading}
              >
                {loading ? 'Analyzing…' : 'Analyze Deployment'}
              </button>
            </div>

          </div>
        </form>
      </div>

      {/* ── Error state ── */}
      {error && (
        <div className="error-box" style={{ marginTop: 20 }}>
          <strong>Analysis failed</strong>{error}
        </div>
      )}

      {/* ── Loading state ── */}
      {loading && (
        <div className="loading-wrap">
          <div className="spinner" />
          <span>Running baseline and memory-informed analysis…</span>
        </div>
      )}

      {/* ── Results ── */}
      {result && !loading && (
        <>
          <div className="results-grid" style={{ marginTop: 24 }}>
            <AnalysisPanel result={result.baseline}       side="baseline" />
            <AnalysisPanel result={result.memory_informed} side="memory" />
          </div>

          <FeedbackSection
            deploymentInfo={{
              deployment_id:        result.deployment_id,
              service:              form.service,
              migration_type:       form.migration_type,
              connection_pool_change: form.connection_pool_change,
            }}
          />
        </>
      )}
    </div>
  )
}
