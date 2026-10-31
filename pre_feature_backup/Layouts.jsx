import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { ErrorBoundary } from './ErrorBoundary'

const link = ({ isActive }) => `rounded-lg px-3 py-2 text-sm font-medium ${isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100'}`

function Shell({ brand, items, right, children }) {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => {
    setOpen(false)
  }, [loc.pathname])
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to={brand.to} className="flex items-center gap-2 text-lg font-bold text-indigo-700"><span aria-hidden>🛎️</span>{brand.name}</Link>
          <button className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm md:hidden" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Toggle menu">Menu</button>
          <nav className="hidden items-center gap-1 md:flex">{items.map((i) => <NavLink key={i.to} to={i.to} end={i.end} className={link}>{i.label}</NavLink>)}{right}</nav>
        </div>
        {open && <nav className="flex flex-col gap-1 border-t border-slate-100 px-4 pb-3 md:hidden">{items.map((i) => <NavLink key={i.to} to={i.to} end={i.end} className={link}>{i.label}</NavLink>)}{right}</nav>}
      </header>
      {children}
    </div>
  )
}

export function PublicLayout() {
  const [org, setOrg] = useState({})
  useEffect(() => {
    let cancelled = false
    api.get('/api/public/organization')
      .then((r) => {
        if (!cancelled && r.data) setOrg(r.data)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])
  const items = [
    { to: '/', label: 'Home', end: true }, { to: '/chat', label: 'Ask Reception' }, { to: '/book', label: 'Book Appointment' },
    { to: '/status', label: 'Check Status' }, { to: '/register', label: 'Visitor Registration' }, { to: '/directory', label: 'Directory & FAQ' },
  ]
  return (
    <Shell brand={{ name: org.organization_name || 'Reception', to: '/' }} items={items} right={<Link to="/admin" className="ml-2 rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-100">Staff login</Link>}>
      <main className="mx-auto max-w-6xl px-4 py-8"><ErrorBoundary><Outlet context={{ org }} /></ErrorBoundary></main>
      <footer className="border-t border-slate-200 py-6 text-center text-xs text-slate-500">
        {[org.address, org.working_hours, org.contact_phone].filter(Boolean).join(' · ')}
      </footer>
    </Shell>
  )
}

export function ProtectedRoute({ children, adminOnly = false }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/admin/login" replace />
  if (adminOnly && user.role !== 'admin') return <Navigate to="/admin" replace />
  return children
}

export function AdminLayout() {
  const { user, logout, isAdmin } = useAuth()
  const items = [
    { to: '/admin', label: 'Dashboard', end: true }, { to: '/admin/appointments', label: 'Appointments' }, { to: '/admin/visitors', label: 'Visitors' },
    { to: '/admin/directory', label: 'Departments & Staff' }, { to: '/admin/content', label: 'FAQs & Info' }, { to: '/admin/analytics', label: 'Analytics' },
    ...(isAdmin ? [{ to: '/admin/users', label: 'Users' }] : []),
  ]
  return (
    <Shell brand={{ name: 'Reception Admin', to: '/admin' }} items={items}
      right={<span className="ml-2 flex items-center gap-2 text-xs text-slate-500">{user.name} ({user.role})<button onClick={logout} className="rounded-lg border border-slate-300 px-2 py-1 text-slate-700 hover:bg-slate-50">Sign out</button></span>}>
      <main className="mx-auto max-w-6xl px-4 py-6"><ErrorBoundary><Outlet /></ErrorBoundary></main>
    </Shell>
  )
}
