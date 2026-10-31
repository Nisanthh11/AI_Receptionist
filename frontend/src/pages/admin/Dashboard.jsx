import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { fmtDateTime, fmtTime } from '../../api/format'
import { Alert, Badge, Card, Spinner } from '../../components/ui'

const Stat = ({ label, value, to }) => (
  <Link to={to}><Card className="hover:border-indigo-300"><p className="text-sm text-slate-500">{label}</p><p className="mt-1 text-3xl font-bold">{value}</p></Card></Link>
)

export default function Dashboard() {
  const [d, setD] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    api.get('/api/admin/dashboard')
      .then((r) => { if (!cancelled) setD(r.data) })
      .catch((e) => { if (!cancelled) setError(errorMessage(e)) })
    return () => { cancelled = true }
  }, [])
  if (error) return <Alert>{error}</Alert>
  if (!d) return <Spinner />
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        {d.ai_responder && (
          <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs shadow-sm">
            <span className={`inline-block h-2 w-2 rounded-full ${d.ai_responder.provider === 'gemini' ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'}`}></span>
            <span className="font-medium text-slate-700">AI Chatbot:</span>
            <span className="text-slate-600">
              {d.ai_responder.provider === 'gemini' ? `Google Gemini (${d.ai_responder.model})` : 'Rule-based Fallback'}
            </span>
          </div>
        )}
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Today's appointments" value={d.today_count} to="/admin/appointments" />
        <Stat label="Pending appointments" value={d.pending_appointments} to="/admin/appointments" />
        <Stat label="Total visitors" value={d.total_visitors} to="/admin/visitors" />
        <Stat label="On site now" value={d.visitors_on_site} to="/admin/visitors" />
      </div>
      {d.visitors_waiting_check_in > 0 && <Alert kind="info">{d.visitors_waiting_check_in} registered visitor(s) are waiting to be checked in.</Alert>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-semibold">Today's schedule</h2>
          {d.today_appointments.length === 0 ? <p className="text-sm text-slate-500">No appointments today.</p> : (
            <ul className="divide-y divide-slate-100">{d.today_appointments.map((a) => (
              <li key={a.id} className="flex items-center justify-between py-2 text-sm">
                <span><b>{fmtTime(a.start_at)}</b> · {a.visitor.full_name} <span className="text-slate-500">with {a.staff.full_name}</span></span><Badge value={a.status} />
              </li>))}</ul>)}
        </Card>
        <Card>
          <h2 className="mb-3 font-semibold">Recent activity</h2>
          {d.recent_activity.length === 0 ? <p className="text-sm text-slate-500">Nothing yet.</p> : (
            <ul className="space-y-2 text-sm">{d.recent_activity.map((n) => <li key={n.id}><span className="text-xs text-slate-400">{fmtDateTime(n.created_at)}</span><br />{n.message}</li>)}</ul>)}
          <p className="mt-3 text-xs text-slate-400">In-app records only. No e-mail, SMS or push notifications are sent.</p>
        </Card>
      </div>
    </div>
  )
}
