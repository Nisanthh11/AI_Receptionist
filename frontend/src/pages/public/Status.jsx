import { useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { fmtDateTime } from '../../api/format'
import { Alert, Badge, Button, Card, Field, Input } from '../../components/ui'

export default function Status() {
  const [ref, setRef] = useState('')
  const [phone, setPhone] = useState('')
  const [res, setRes] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(''); setRes(null)
    try { setRes((await api.post('/api/public/appointments/lookup', { reference_code: ref, phone })).data) }
    catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }
  return (
    <div className="mx-auto max-w-lg space-y-4">
      <Card>
        <h1 className="text-2xl font-bold">Appointment status</h1>
        <form className="mt-4 space-y-4" onSubmit={submit}>
          <Field label="Reference code"><Input required placeholder="APT-XXXXXXXX" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
          <Field label="Phone number used when booking"><Input required type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
          <Alert>{error}</Alert>
          <Button type="submit" disabled={busy} className="w-full">{busy ? 'Checking…' : 'Check status'}</Button>
        </form>
      </Card>
      {res && (
        <Card>
          <div className="flex items-center justify-between"><span className="font-mono font-semibold">{res.reference_code}</span><Badge value={res.status} /></div>
          <p className="mt-3 text-sm text-slate-600">{res.message}</p>
          <p className="mt-3 text-sm"><b>{fmtDateTime(res.start_at)}</b> with {res.staff_name} ({res.department_name})</p>
        </Card>
      )}
    </div>
  )
}
