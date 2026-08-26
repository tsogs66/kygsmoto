import { NavLink, Route, Routes } from 'react-router-dom'
import { useState } from 'react'
import DashboardPage from './pages/DashboardPage'
import InventoryPage from './pages/InventoryPage'
import SalesPage from './pages/SalesPage'
import PurchasesPage from './pages/PurchasesPage'
import ReportsPage from './pages/ReportsPage'
import ImportPage from './pages/ImportPage'
import StockIntelligencePage from './pages/StockIntelligencePage'
import JobQueuePage from './pages/JobQueuePage'

const links = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/inventory', label: 'Inventory' },
  { to: '/sales', label: 'Sales / POS' },
  { to: '/job-queue', label: 'Job Queue' },
  { to: '/purchases', label: 'Purchases' },
  { to: '/stock-intelligence', label: 'Stock Intelligence' },
  { to: '/reports', label: 'Reports' },
  { to: '/import', label: 'Sales File Import' },
]

export default function App() {
  const [open, setOpen] = useState(false)

  return (
    <div className="app-shell">
      {open && <div className="backdrop" onClick={() => setOpen(false)} />}
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">
            KYG<span>SMOTO</span>
          </div>
          <div className="brand-sub">Sales · Inventory · Reports</div>
        </div>
        <nav className="nav-links" onClick={() => setOpen(false)}>
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end}>
              {link.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main">
        <button className="btn secondary mobile-toggle" onClick={() => setOpen(true)} style={{ marginBottom: '0.8rem' }}>
          Menu
        </button>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/sales" element={<SalesPage />} />
          <Route path="/job-queue" element={<JobQueuePage />} />
          <Route path="/purchases" element={<PurchasesPage />} />
          <Route path="/stock-intelligence" element={<StockIntelligencePage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/import" element={<ImportPage />} />
        </Routes>
      </main>
    </div>
  )
}
