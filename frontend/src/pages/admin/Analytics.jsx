import { useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { Alert, Card, Select, Spinner } from '../../components/ui'

function Bars({ rows, color }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  return <ul className="space-y-2">{rows.map((r) => (
    <li key={r.label} className="text-sm"><div className="mb-0.5 flex justify-between"><span>{r.label}</span><span className="font-medium">{r.value}</span></div>
      <div className="h-2 rounded bg-slate-100"><div className={`h-2 rounded ${color}`} style={{ width: `${(r.value / max) * 100}%` }} /></div></li>))}</ul>
}

export default function Analytics() {
  const [days, setDays] = useState(14)
  const [d, setD] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    setD(null)
    api.get('/api/admin/analytics', { params: { days } })
      .then((r) => { if (!cancelled) setD(r.data) })
      .catch((e) => { if (!cancelled) setError(errorMessage(e)) })
    return () => { cancelled = true }
  }, [days])
  if (error) return <Alert>{error}</Alert>
  const max = d ? Math.max(1, ...d.daily.map((x) => Math.max(x.appointments, x.visits))) : 1
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-bold">Analytics</h1><div className="w-40"><Select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Range">{[7, 14, 30, 90].map((n) => <option key={n} value={n}>Last {n} days</option>)}</Select></div></div>
      {!d ? <Spinner /> : <>
        <div className="grid gap-6 md:grid-cols-2">
          <Card><h2 className="mb-3 font-semibold">Appointments by status (all time)</h2><Bars color="bg-indigo-500" rows={Object.entries(d.appointments_by_status).map(([label, value]) => ({ label, value }))} /></Card>
          <Card><h2 className="mb-3 font-semibold">Appointments by department (all time)</h2>
            {d.appointments_by_department.length === 0 ? <p className="text-sm text-slate-500">No data yet.</p> : <Bars color="bg-emerald-500" rows={d.appointments_by_department.map((x) => ({ label: x.department, value: x.appointments }))} />}</Card>
        </div>
        <Card>
          <h2 className="mb-1 font-semibold">Daily activity</h2><p className="mb-3 text-xs text-slate-500">Appointments by scheduled date · visits by check-in date</p>
          <div className="flex h-40 items-end gap-1 overflow-x-auto" role="img" aria-label="Daily appointments and visits chart">
            {d.daily.map((x) => (
              <div key={x.date} className="flex min-w-[14px] flex-1 flex-col items-center justify-end gap-0.5" title={`${x.date}: ${x.appointments} appointments, ${x.visits} visits`}>
                <div className="flex h-32 items-end gap-0.5"><div className="w-1.5 rounded-t bg-indigo-500" style={{ height: `${(x.appointments / max) * 100}%` }} /><div className="w-1.5 rounded-t bg-emerald-500" style={{ height: `${(x.visits / max) * 100}%` }} /></div>
                <span className="text-[9px] text-slate-400">{x.date.slice(8)}</span></div>))}
          </div>
          <p className="mt-2 text-xs"><span className="mr-3 text-indigo-600">■ Appointments</span><span className="text-emerald-600">■ Visits</span></p>
        </Card>
        <Card><h2 className="font-semibold">Average visit length</h2><p className="mt-1 text-3xl font-bold">{d.average_visit_minutes ?? '—'}{d.average_visit_minutes != null && <span className="text-base font-normal text-slate-500"> min</span>}</p><p className="text-xs text-slate-500">Based on {d.completed_visits_in_range} completed visit(s) in the range.</p></Card>
      </>}
    </div>
  )
}
