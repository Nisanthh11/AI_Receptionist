import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { fmtDateTime } from '../../api/format'
import { Alert, Badge, Button, Card, Field, Input, Select, SlotPicker } from '../../components/ui'

export default function Book() {
  const [depts, setDepts] = useState([])
  const [deptId, setDeptId] = useState('')
  const [staffId, setStaffId] = useState('')
  const [slot, setSlot] = useState('')
  const [f, setF] = useState({ full_name: '', phone: '', email: '', purpose: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const [loadError, setLoadError] = useState('')
  useEffect(() => {
    let cancelled = false
    setLoadError('')
    api.get('/api/public/departments')
      .then((r) => { if (!cancelled) setDepts(r.data || []) })
      .catch((e) => { if (!cancelled) setLoadError(errorMessage(e)) })
    return () => { cancelled = true }
  }, [refresh])
  const dept = depts.find((d) => String(d.id) === deptId)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const body = { full_name: f.full_name, phone: f.phone, purpose: f.purpose, staff_id: Number(staffId), start_at: slot, ...(f.email && { email: f.email }) }
      const { data } = await api.post('/api/public/appointments', body)
      setResult(data) // only shown after the server confirmed the saved booking
    } catch (err) {
      setError(errorMessage(err))
      if (err.response?.status === 409 || err.response?.status === 400) { setSlot(''); setRefresh((n) => n + 1) }
    } finally { setBusy(false) }
  }

  if (result) return (
    <Card className="mx-auto max-w-lg text-center">
      <div className="text-4xl">📅</div><h1 className="mt-2 text-xl font-bold">Appointment request saved</h1>
      <div className="mt-3"><Badge value={result.status} /></div>
      <p className="mt-3 text-sm text-slate-600">{result.message}</p>
      <dl className="mt-4 space-y-1 rounded-lg bg-slate-50 p-4 text-left text-sm">
        <div className="flex justify-between"><dt className="text-slate-500">Reference</dt><dd className="font-mono font-semibold">{result.reference_code}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">When</dt><dd>{fmtDateTime(result.start_at)}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">With</dt><dd>{result.staff_name}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Department</dt><dd>{result.department_name}</dd></div>
      </dl>
      <p className="mt-4 text-xs text-slate-500">Keep your reference code. Check progress any time on the <Link className="text-indigo-600 underline" to="/status">status page</Link> with your phone number.</p>
    </Card>
  )

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div><h1 className="text-2xl font-bold">Book an appointment</h1><p className="text-sm text-slate-500">Only slots that are genuinely free are shown. Your request is confirmed by the reception team.</p></div>
      {loadError ? (
        <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <span>{loadError}</span>
          <Button variant="secondary" size="sm" onClick={() => setRefresh((n) => n + 1)}>Retry</Button>
        </div>
      ) : null}
      <Card className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Department"><Select value={deptId} onChange={(e) => { setDeptId(e.target.value); setStaffId(''); setSlot('') }}><option value="">Select…</option>{depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
          <Field label="Person to meet"><Select value={staffId} disabled={!dept} onChange={(e) => { setStaffId(e.target.value); setSlot('') }}><option value="">Select…</option>{(dept?.staff || []).map((s) => <option key={s.id} value={s.id}>{s.full_name}{s.designation ? ` — ${s.designation}` : ''}</option>)}</Select></Field>
        </div>
        {staffId && <SlotPicker staffId={staffId} value={slot} onPick={setSlot} refreshKey={refresh} />}
      </Card>
      {slot && (
        <Card>
          <h2 className="mb-3 font-semibold">Your details — {fmtDateTime(slot)}</h2>
          <form className="space-y-4" onSubmit={submit}>
            <Field label="Full name"><Input required minLength={2} maxLength={100} value={f.full_name} onChange={set('full_name')} /></Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Phone number"><Input required type="tel" value={f.phone} onChange={set('phone')} /></Field>
              <Field label="E-mail (optional)"><Input type="email" value={f.email} onChange={set('email')} /></Field>
            </div>
            <Field label="Purpose of the appointment"><Input required maxLength={255} value={f.purpose} onChange={set('purpose')} /></Field>
            <Alert>{error}</Alert>
            <Button type="submit" disabled={busy} className="w-full">{busy ? 'Saving…' : 'Request appointment'}</Button>
          </form>
        </Card>
      )}
    </div>
  )
}
