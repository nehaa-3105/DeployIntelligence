import { useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import NewAnalysis from './pages/NewAnalysis.jsx'
import Deployments from './pages/Deployments.jsx'
import OrganisationalMemory from './pages/OrganisationalMemory.jsx'

const DEFAULT_FORM = {
  deployment_id:          '297',
  service:                'payment-service',
  migration_type:         'schema',
  change_type:            'infra',
  connection_pool_change: true,
  dependencies_changed:   true,
}

/**
 * App — root component.
 *
 * New Analysis state is kept here so navigating away and back
 * preserves the form, results, feedback, and rerun state.
 * Phase 3 wires in the real NewAnalysis page.
 */
export default function App() {
  // Page routing — no router library
  const [page, setPage] = useState('new-analysis')

  // New Analysis state — persisted across page switches
  const [form,           setForm]           = useState(DEFAULT_FORM)
  const [analysisResult, setAnalysisResult] = useState(null)
  const [firstSnapshot,  setFirstSnapshot]  = useState(null)
  const [feedbackResult, setFeedbackResult] = useState(null)
  const [rerunResult,    setRerunResult]    = useState(null)

  function renderPage() {
    switch (page) {
      case 'organisational-memory':
        return <OrganisationalMemory />
      case 'deployments':
        return <Deployments />
      case 'new-analysis':
      default:
        return (
          <NewAnalysis
            form={form}                 setForm={setForm}
            analysisResult={analysisResult} setAnalysisResult={setAnalysisResult}
            firstSnapshot={firstSnapshot}   setFirstSnapshot={setFirstSnapshot}
            feedbackResult={feedbackResult} setFeedbackResult={setFeedbackResult}
            rerunResult={rerunResult}       setRerunResult={setRerunResult}
          />
        )
    }
  }

  return (
    <div className="app-layout">
      <Sidebar activePage={page} onNavigate={setPage} />
      <main className="app-main" id="main-content">
        {renderPage()}
      </main>
    </div>
  )
}
