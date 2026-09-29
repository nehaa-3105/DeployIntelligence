import { useState, useEffect } from 'react'
import { getDeployments } from '../api.js'
import { OutcomeBadge } from '../components/Badge.jsx'
import DetailDrawer from '../components/DetailDrawer.jsx'
import { IconSearch, IconEye, IconDatabase } from '../components/Icons.jsx'

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

export default function Deployments() {
  const [rows,    setRows]    = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [query,   setQuery]   = useState('')
  const [drawer,  setDrawer]  = useState(null)   // selected row

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getDeployments()
      .then(data => { if (!cancelled) setRows(data) })
      .catch(e  => { if (!cancelled) setError(e.message) })
      .finally(()=> { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // Client-side filter
  const q = query.trim().toLowerCase()
  const filtered = q
    ? rows.filter(r =>
        r.deployment_id?.toLowerCase().includes(q) ||
        r.service?.toLowerCase().includes(q)       ||
        r.migration_type?.toLowerCase().includes(q)||
        r.change_type?.toLowerCase().includes(q)   ||
        r.outcome?.toLowerCase().includes(q)
      )
    : rows

  return (
    <div className="page-content">
      {/* Page header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Deployments</h1>
          <p className="page-subtitle">All deployments in your organisation.</p>
        </div>
      </div>

      {/* Search */}
      <div className="search-bar">
        <span className="search-icon"><IconSearch size={15} color="#9aa7b5" /></span>
        <input
          className="search-input"
          placeholder="Search deployments..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          aria-label="Search deployments"
        />
      </div>

      {/* States */}
      {loading && (
        <div className="state-loading">
          <div className="spinner" />
          <span>Loading deployments…</span>
        </div>
      )}

      {error && !loading && (
        <div className="state-error">
          <strong>Failed to load deployments</strong>
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <div className="state-empty">
          <IconDatabase size={32} color="#9aa7b5" />
          <p>No deployments recorded yet.</p>
          <p className="state-empty-sub">Run ingestion to seed the ledger.</p>
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <>
          {filtered.length === 0 ? (
            <div className="state-empty">
              <p>No deployments match <em>"{query}"</em>.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Service</th>
                    <th>Migration Type</th>
                    <th>Change Type</th>
                    <th>Outcome</th>
                    <th>Date</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(row => (
                    <tr key={row.deployment_id}>
                      <td className="td-id">#{row.deployment_id}</td>
                      <td>{row.service}</td>
                      <td><span className="tag">{row.migration_type}</span></td>
                      <td><span className="tag">{row.change_type}</span></td>
                      <td><OutcomeBadge outcome={row.outcome} /></td>
                      <td className="td-muted">{fmtDate(row.timestamp)}</td>
                      <td>
                        <button
                          className="btn-view"
                          onClick={() => setDrawer(row)}
                          aria-label={`View deployment #${row.deployment_id}`}
                        >
                          <IconEye size={14} />
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* Detail drawer */}
      {drawer && (
        <DetailDrawer record={drawer} onClose={() => setDrawer(null)} />
      )}
    </div>
  )
}
