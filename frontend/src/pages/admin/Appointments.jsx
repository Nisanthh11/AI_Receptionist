import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { fmtDateTime } from '../../api/format'
import { Alert, Badge, Button, Field, Input, Modal, Pagination, Select, SlotPicker, Spinner } from '../../components/ui'

const PAGE_SIZE = 15

export default function Appointments() {
  const [filters, setFilters] = useState({ q: '', status: '', department_id: '', booking_source: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [depts, setDepts] = useState([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(null) // {type: 'cancel'|'reschedule', appt}
  const [reason, setReason] = useState('')
  const [slot, setSlot] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    const params = { page, page_size: PAGE_SIZE, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) }
    api.get('/api/admin/appointments', { params }).then((r) => { setData(r.data); setError('') }).catch((e) => setError(errorMessage(e)))
  }, [filters, page])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])
  useEffect(() => {
    let cancelled = false
    api.get('/api/admin/departments')
      .then((r) => { if (!cancelled) setDepts(r.data) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])
  const setF = (k) => (e) => { setFilters({ ...filters, [k]: e.target.value }); setPage(1) }

  async function act(fn, okMsg) {
    setBusy(true); setError(''); setNotice('')
    try { await fn(); setNotice(okMsg); setModal(null); setReason(''); setSlot(''); load() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  const setStatus = (a, status) => act(() => api.patch(`/api/admin/appointments/${a.id}/status`, { status }), `${a.reference_code} marked ${status}.`)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Appointments</h1>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => act(() => api.post('/api/admin/appointments/reminders/process'), 'Checked and processed due reminders.')}>
          Process Reminders
        </Button>
      </div>
      <div className="grid gap-3 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-6">
        <Field label="Search"><Input placeholder="Name, phone, reference…" value={filters.q} onChange={setF('q')} /></Field>
        <Field label="Status"><Select value={filters.status} onChange={setF('status')}><option value="">All Statuses</option>{['pending', 'confirmed', 'completed', 'cancelled'].map((s) => <option key={s}>{s}</option>)}</Select></Field>
        <Field label="Channel"><Select value={filters.booking_source} onChange={setF('booking_source')}><option value="">All Channels</option><option value="website">Web Form</option><option value="browser_voice">Voice Call</option><option value="telephone">Telephone Call</option><option value="admin">Admin Desk</option></Select></Field>
        <Field label="Department"><Select value={filters.department_id} onChange={setF('department_id')}><option value="">All</option>{depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
        <Field label="From"><Input type="date" value={filters.date_from} onChange={setF('date_from')} /></Field>
        <Field label="To"><Input type="date" value={filters.date_to} onChange={setF('date_to')} /></Field>
      </div>
      <Alert>{error}</Alert><Alert kind="success">{notice}</Alert>
      {!data ? <Spinner /> : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">When</th><th className="p-3">Visitor</th><th className="p-3">With</th><th className="p-3">Purpose</th><th className="p-3">Status & Channel</th><th className="p-3">Actions</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.length === 0 && <tr><td colSpan="6" className="p-6 text-center text-slate-500">No appointments match.</td></tr>}
              {data.items.map((a) => (
                <tr key={a.id}>
                  <td className="p-3 whitespace-nowrap">{fmtDateTime(a.start_at)}<div className="font-mono text-xs text-slate-400">{a.reference_code}</div></td>
                  <td className="p-3">{a.visitor.full_name}<div className="text-xs text-slate-500">{a.visitor.phone}</div></td>
                  <td className="p-3">{a.staff.full_name}<div className="text-xs text-slate-500">{a.department.name}</div></td>
                  <td className="p-3 max-w-[200px] truncate" title={a.purpose}>{a.purpose}</td>
                  <td className="p-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge value={a.status} />
                      <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border ${
                        a.booking_source === 'browser_voice'
                          ? 'bg-purple-50 text-purple-700 border-purple-200'
                          : a.booking_source === 'telephone'
                          ? 'bg-blue-50 text-blue-700 border-blue-200'
                          : a.booking_source === 'admin'
                          ? 'bg-amber-50 text-amber-700 border-amber-200'
                          : 'bg-slate-50 text-slate-600 border-slate-200'
                      }`}>
                        {a.booking_source === 'browser_voice' ? '🎙️ Voice' : a.booking_source === 'telephone' ? '📞 Phone' : a.booking_source === 'admin' ? '🛡️ Admin' : '🌐 Web'}
                      </span>
                    </div>
                    {a.cancelled_reason && <div className="text-xs text-slate-500 mt-0.5">{a.cancelled_reason}</div>}
                    {a.reminders && a.reminders.length > 0 && (
                      <div className="mt-1.5 flex flex-col gap-0.5">
                        <div className="font-semibold text-slate-400 text-[10px] uppercase">Reminders</div>
                        <div className="flex flex-wrap gap-1">
                          {a.reminders.map((r) => (
                            <span
                              key={r.id}
                              className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium border ${
                                r.status === 'sent'
                                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                  : r.status === 'failed'
                                  ? 'bg-rose-50 text-rose-700 border-rose-200'
                                  : r.status === 'processing'
                                  ? 'bg-amber-50 text-amber-700 border-amber-200 animate-pulse'
                                  : r.status === 'cancelled' || r.status === 'skipped'
                                  ? 'bg-slate-50 text-slate-400 border-slate-200 line-through'
                                  : 'bg-indigo-50 text-indigo-700 border-indigo-200'
                              }`}
                              title={r.last_error ? `Error: ${r.last_error}` : r.sent_at ? `Sent at ${fmtDateTime(r.sent_at)}` : `Scheduled for ${fmtDateTime(r.scheduled_for)}`}
                            >
                              {r.reminder_type}: {r.status}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </td>
                  <td className="p-3"><div className="flex flex-wrap gap-1">
                    {a.status === 'pending' && <Button size="sm" variant="success" disabled={busy} onClick={() => setStatus(a, 'confirmed')}>Confirm</Button>}
                    {a.status === 'confirmed' && <Button size="sm" disabled={busy} onClick={() => setStatus(a, 'completed')}>Complete</Button>}
                    {['pending', 'confirmed'].includes(a.status) && <>
                      <Button size="sm" variant="secondary" onClick={() => { setModal({ type: 'reschedule', a }); setSlot('') }}>Reschedule</Button>
                      <Button size="sm" variant="danger" onClick={() => setModal({ type: 'cancel', a })}>Cancel</Button></>}
                  </div></td>
                </tr>))}
            </tbody>
          </table>
        </div>)}
      {data && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />}

      {modal?.type === 'cancel' && (
        <Modal title={`Cancel ${modal.a.reference_code}`} onClose={() => setModal(null)}>
          <Field label="Reason (optional)"><Input maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" onClick={() => setModal(null)}>Keep appointment</Button>
            <Button variant="danger" disabled={busy} onClick={() => act(() => api.post(`/api/admin/appointments/${modal.a.id}/cancel`, reason ? { reason } : {}), 'Appointment cancelled.')}>Cancel appointment</Button></div>
        </Modal>)}
      {modal?.type === 'reschedule' && (
        <Modal title={`Reschedule ${modal.a.reference_code}`} onClose={() => setModal(null)}>
          <p className="mb-3 text-sm text-slate-500">Currently {fmtDateTime(modal.a.start_at)} with {modal.a.staff.full_name}. Choose a free slot:</p>
          <SlotPicker staffId={modal.a.staff.id} value={slot} onPick={setSlot} />
          <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" onClick={() => setModal(null)}>Close</Button>
            <Button disabled={!slot || busy} onClick={() => act(() => api.post(`/api/admin/appointments/${modal.a.id}/reschedule`, { start_at: slot }), 'Appointment rescheduled.')}>Reschedule</Button></div>
        </Modal>)}
    </div>
  )
}
