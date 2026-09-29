import { IconPulse, IconCube, IconDatabase, IconSettings } from './Icons.jsx'

const NAV_ITEMS = [
  { id: 'new-analysis',          label: 'New Analysis',           Icon: IconPulse    },
  { id: 'organisational-memory', label: 'Organisational Memory',  Icon: IconCube     },
  { id: 'deployments',           label: 'Deployments',            Icon: IconDatabase },
]

export default function Sidebar({ activePage, onNavigate }) {
  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="sidebar-brand">
        <span className="sidebar-brand-icon">
          <IconCube size={22} color="#22d3ee" />
        </span>
        <span className="sidebar-brand-name">DeployIntelligence</span>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        {NAV_ITEMS.map(({ id, label, Icon }) => {
          const active = activePage === id
          return (
            <button
              key={id}
              className={`sidebar-nav-item${active ? ' active' : ''}`}
              onClick={() => onNavigate(id)}
              aria-current={active ? 'page' : undefined}
            >
              <span className="sidebar-nav-icon">
                <Icon size={17} color={active ? '#fff' : '#9aa7b5'} />
              </span>
              <span className="sidebar-nav-label">{label}</span>
            </button>
          )
        })}
      </nav>

      {/* Footer — static, non-interactive */}
      <div className="sidebar-footer">
        <div className="sidebar-footer-settings">
          <IconSettings size={15} color="#9aa7b5" />
          <span>Acme Platform Team</span>
        </div>
        <div className="sidebar-footer-user">
          <div className="sidebar-footer-avatar" aria-hidden="true">N</div>
          <div className="sidebar-footer-info">
            <span className="sidebar-footer-name">Nehaa</span>
            <span className="sidebar-footer-team">Acme Platform Team</span>
          </div>
        </div>
      </div>
    </aside>
  )
}
