/**
 * api.js — thin fetch wrapper for the Deployment Memory FastAPI backend.
 *
 * Base URL is read from VITE_API_BASE_URL env var.
 * In development (Vite proxy configured in vite.config.js) this is empty
 * and all requests go to the same origin, which Vite proxies to localhost:8000.
 */

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

async function request(path, options = {}) {
  const url = `${BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch (_) { /* ignore */ }
    throw new Error(detail)
  }
  return res.json()
}

/**
 * POST /analyze
 * @param {Object} payload  - { deployment_id, service, migration_type,
 *                             connection_pool_change, change_type,
 *                             dependencies_changed }
 * @returns {Promise<{deployment_id, baseline, memory_informed}>}
 */
export function analyzeDeployment(payload) {
  return request('/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/**
 * POST /feedback
 * @param {Object} payload  - { deployment_id, outcome, service, migration_type,
 *                             connection_pool_change, root_cause, resolution,
 *                             recovery_time_minutes }
 * @returns {Promise<{status, message}>}
 */
export function submitFeedback(payload) {
  return request('/feedback', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/**
 * GET /health
 * @returns {Promise<{status}>}
 */
export function checkHealth() {
  return request('/health')
}
