import { useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { Alert, Button, Card, Field, Input, Select } from '../../components/ui'

export default function Register() {
  const [staff, setStaff] = useState([])
  const [f, setF] = useState({ full_name: '', phone: '', email: '', purpose: '', staff_id: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [done, setDone] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoadError('')
    api.get('/api/public/departments')
      .then((r) => {
        if (!cancelled && r.data) {
          setStaff(r.data.flatMap((d) => (d.staff || []).map((s) => ({ ...s, dept: d.name }))))
        }
      })
      .catch((e) => {
        if (!cancelled) setLoadError(errorMessage(e))
      })
    return () => { cancelled = true }
  }, [reloadKey])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const body = { full_name: f.full_name, phone: f.phone, purpose: f.purpose, ...(f.email && { email: f.email }), ...(f.staff_id && { staff_id: Number(f.staff_id) }) }
      const { data } = await api.post('/api/public/visitors/register', body)
      setDone(data)
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  if (done) return (
    <Card className="mx-auto max-w-lg text-center"><div className="text-4xl">✅</div><h1 className="mt-2 text-xl font-bold">Registration received</h1>
      <p className="mt-2 text-sm text-slate-600">{done.message}</p>
      <p className="mt-4 rounded-lg bg-slate-100 p-3 font-mono text-lg">{done.reference_code}</p></Card>
  )
  return (
    <Card className="mx-auto max-w-lg">
      <h1 className="text-2xl font-bold">Visitor registration</h1>
      <p className="mb-4 mt-1 text-sm text-slate-500">We only ask for what we need. Your details are visible to authorised staff only.</p>
      <form className="space-y-4" onSubmit={submit}>
        <Field label="Full name"><Input required minLength={2} maxLength={100} value={f.full_name} onChange={set('full_name')} /></Field>
        <Field label="Phone number" hint="Digits with optional + country code"><Input required type="tel" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="E-mail (optional)"><Input type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="Purpose of visit"><Input required maxLength={255} value={f.purpose} onChange={set('purpose')} /></Field>
        <Field label="Who are you here to meet? (optional)">
          <Select value={f.staff_id} onChange={set('staff_id')}><option value="">Not sure / no one in particular</option>
            {staff.map((s) => <option key={s.id} value={s.id}>{s.full_name} — {s.dept}</option>)}</Select>
        </Field>
        {loadError && (
          <div className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <span>Unable to load staff directory: {loadError}</span>
            <Button type="button" variant="secondary" size="sm" onClick={() => setReloadKey((k) => k + 1)}>Retry</Button>
          </div>
        )}
        <Alert>{error}</Alert>
        <Button type="submit" disabled={busy} className="w-full">{busy ? 'Submitting…' : 'Register'}</Button>
      </form>
    </Card>
  )
}
