import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { ErrorBoundary } from './ErrorBoundary'

function SidebarShell({ brand, items, bottomSection, footerText, children }) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const loc = useLocation()

  useEffect(() => {
    setMobileOpen(false)
  }, [loc.pathname])

  const navContent = (onNavClick) => (
    <div className="flex h-full flex-col justify-between">
      <div>
        {/* Brand */}
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-4 min-w-0">
          <Link
            to={brand.to}
            onClick={onNavClick}
            className="flex items-center gap-3 min-w-0 flex-1 group"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 border border-indigo-100 text-xl shadow-xs">
              <span aria-hidden>🛎️</span>
            </div>
            <div className="min-w-0 flex-1">
              <span className="block text-sm font-bold text-slate-900 leading-snug break-words group-hover:text-indigo-600 transition">
                {brand.name}
              </span>
            </div>
          </Link>
          {onNavClick && (
            <button
              type="button"
              onClick={onNavClick}
              className="ml-2 shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 md:hidden"
              aria-label="Close menu"
            >
              ✕
            </button>
          )}
        </div>

        {/* Navigation Items */}
        <nav className="space-y-1 px-3 py-4">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavClick}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3.5 py-2.5 text-sm font-medium transition duration-150 ${
                  isActive
                    ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-xs'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`
              }
            >
              {item.icon && <span className="text-base shrink-0" aria-hidden>{item.icon}</span>}
              <span className="truncate">{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Bottom User / Profile / Auth Section */}
      <div className="border-t border-slate-200 p-4 min-w-0">
        {bottomSection}
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-slate-50/50">
      {/* Mobile Top Header */}
      <header className="sticky top-0 z-40 flex items-center justify-between border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur md:hidden">
        <Link to={brand.to} className="flex items-center gap-2.5 min-w-0 flex-1 mr-2">
          <span className="text-xl shrink-0" aria-hidden>🛎️</span>
          <span className="text-sm font-bold text-slate-900 truncate">{brand.name}</span>
        </Link>
        <button
          type="button"
          className="shrink-0 rounded-lg border border-slate-300 p-2 text-slate-600 hover:bg-slate-100"
          onClick={() => setMobileOpen(true)}
          aria-expanded={mobileOpen}
          aria-label="Open navigation menu"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </header>

      {/* Mobile Backdrop & Drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileOpen(false)}
          />
          <div className="fixed inset-y-0 left-0 z-50 w-80 max-w-[85vw] bg-white shadow-2xl">
            {navContent(() => setMobileOpen(false))}
          </div>
        </div>
      )}

      {/* Desktop Sticky Sidebar */}
      <aside className="hidden md:fixed md:inset-y-0 md:left-0 md:z-30 md:flex md:w-72 md:flex-col border-r border-slate-200 bg-white">
        {navContent()}
      </aside>

      {/* Main Content Area */}
      <div className="md:pl-72 flex flex-col min-h-screen min-w-0">
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 md:px-8">
          {children}
        </main>
        {footerText && (
          <footer className="border-t border-slate-200 py-6 text-center text-xs text-slate-500">
            {footerText}
          </footer>
        )}
      </div>
    </div>
  )
}

export function PublicLayout() {
  const { user, logout } = useAuth()
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
    { to: '/', label: 'Home', icon: '🏠', end: true },
    { to: '/chat', label: 'Ask Receptionist', icon: '💬' },
    { to: '/call', label: 'Call Receptionist', icon: '📞' },
    { to: '/book', label: 'Book Appointment', icon: '📅' },
    { to: '/status', label: 'Check Status', icon: '🔍' },
    ...(user ? [{ to: '/my-appointments', label: 'My Appointments', icon: '📋' }] : []),
    { to: '/register', label: 'Visitor Registration', icon: '📝' },
    { to: '/directory', label: 'Directory & FAQ', icon: '🏢' },
    ...(user ? [{ to: '/profile', label: 'My Profile', icon: '👤' }] : []),
  ]

  const bottomSection = user ? (
    user.role === 'admin' || user.role === 'receptionist' ? (
      <div className="space-y-2">
        <Link
          to="/admin"
          className="flex items-center justify-center gap-2 rounded-lg bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 transition"
        >
          <span>🛡️</span>
          <span>Staff Dashboard</span>
        </Link>
        <div className="flex items-center justify-between pt-1">
          <div className="truncate">
            <p className="text-xs font-bold text-slate-800 truncate">{user.name}</p>
            <p className="text-[11px] text-slate-500 capitalize">{user.role}</p>
          </div>
          <button
            onClick={logout}
            className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-red-50 hover:text-red-700 transition"
          >
            Sign Out
          </button>
        </div>
      </div>
    ) : (
      <div className="space-y-2">
        <Link
          to="/profile"
          className="flex items-center gap-3 rounded-lg p-2 hover:bg-slate-100 transition"
          title="View My Profile"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-sm font-bold text-indigo-700">
            {user.name ? user.name.charAt(0).toUpperCase() : '👤'}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-slate-800 truncate">{user.name}</p>
            <p className="text-xs text-slate-500 truncate">{user.email || 'My Profile'}</p>
          </div>
        </Link>
        <button
          onClick={logout}
          className="flex items-center justify-center gap-2 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-red-50 hover:text-red-700 hover:border-red-200 transition"
        >
          <span>🚪</span>
          <span>Sign Out</span>
        </button>
      </div>
    )
  ) : (
    <div className="space-y-2">
      <Link
        to="/admin/login"
        className="flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 transition shadow-xs"
      >
        <span>🔑</span>
        <span>Sign In / Register</span>
      </Link>
      <p className="text-center text-[11px] text-slate-400">
        Track bookings & manage profile
      </p>
    </div>
  )

  const footerText = [org.address, org.working_hours, org.contact_phone].filter(Boolean).join(' · ')

  return (
    <SidebarShell
      brand={{ name: org.organization_name || 'AI Receptionist', to: '/' }}
      items={items}
      bottomSection={bottomSection}
      footerText={footerText}
    >
      <ErrorBoundary>
        <Outlet context={{ org }} />
      </ErrorBoundary>
    </SidebarShell>
  )
}

export function ProtectedRoute({ children, adminOnly = false, staffOnly = false }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/admin/login" replace />
  if (adminOnly && user.role !== 'admin') return <Navigate to="/admin" replace />
  if (staffOnly && user.role !== 'admin' && user.role !== 'receptionist') {
    return <Navigate to="/my-appointments" replace />
  }
  return children
}

export function AdminLayout() {
  const { user, logout, isAdmin } = useAuth()
  const items = [
    { to: '/admin', label: 'Dashboard', icon: '📊', end: true },
    { to: '/admin/appointments', label: 'Appointments', icon: '📅' },
    { to: '/admin/visitors', label: 'Visitors', icon: '👥' },
    { to: '/admin/directory', label: 'Departments & Staff', icon: '🏢' },
    { to: '/admin/content', label: 'FAQs & Info', icon: '📚' },
    { to: '/admin/analytics', label: 'Analytics', icon: '📈' },
    ...(isAdmin ? [{ to: '/admin/users', label: 'Users', icon: '⚙️' }] : []),
  ]

  const bottomSection = (
    <div className="space-y-2">
      <Link
        to="/"
        className="flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100 transition"
      >
        <span>←</span>
        <span>Public Reception</span>
      </Link>
      <div className="flex items-center justify-between pt-1">
        <div className="truncate">
          <p className="text-xs font-bold text-slate-800 truncate">{user?.name}</p>
          <p className="text-[11px] text-slate-500 capitalize">{user?.role}</p>
        </div>
        <button
          onClick={logout}
          className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-red-50 hover:text-red-700 transition"
        >
          Sign Out
        </button>
      </div>
    </div>
  )

  return (
    <SidebarShell brand={{ name: 'Reception Admin', to: '/admin' }} items={items} bottomSection={bottomSection}>
      <ErrorBoundary>
        <Outlet />
      </ErrorBoundary>
    </SidebarShell>
  )
}
