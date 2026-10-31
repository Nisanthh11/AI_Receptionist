import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { fmtDateTime } from '../../api/format'
import { Alert, Badge, Button, Card, Field, Input, Select, SlotPicker } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

export default function Book() {
  const { user } = useAuth()
  const [depts, setDepts] = useState([])
  const [deptId, setDeptId] = useState('')
  const [staffId, setStaffId] = useState('')
  const [slot, setSlot] = useState('')
  const [slotObj, setSlotObj] = useState(null)
  const [f, setF] = useState({ full_name: '', phone: '', email: '', purpose: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const [loadError, setLoadError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (user) {
      setF((prev) => ({
        ...prev,
        full_name: prev.full_name || user.name || '',
        email: prev.email || user.email || '',
        phone: prev.phone || user.phone || '',
      }))
    }
  }, [user])

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
    const targetStaffId = (staffId && staffId !== 'any') ? Number(staffId) : (slotObj?.staff_id || null)

    // Pre-validate slot availability right before booking submission
    try {
      const checkDate = slot.split('T')[0]
      const checkParams = { date: checkDate }
      if (targetStaffId) {
        checkParams.staff_id = targetStaffId
      } else if (deptId) {
        checkParams.department_id = deptId
      }
      const checkRes = await api.get('/api/public/slots', { params: checkParams })
      const isStillAvailable = checkRes.data.slots?.includes(slot)
      if (!isStillAvailable) {
        setError('This appointment slot was just taken by another visitor. Please select a different available slot.')
        setSlot('')
        setSlotObj(null)
        setRefresh((n) => n + 1)
        setBusy(false)
        return
      }
    } catch {
      // Allow database transaction to enforce final atomicity if network check fails
    }

    try {
      const body = {
        full_name: f.full_name,
        phone: f.phone,
        purpose: f.purpose,
        start_at: slot,
        ...(targetStaffId ? { staff_id: targetStaffId } : { department_id: Number(deptId) }),
        ...(f.email && { email: f.email }),
      }
      const { data } = await api.post('/api/public/appointments', body)
      setResult(data) // only shown after the server confirmed the saved booking
    } catch (err) {
      setError(errorMessage(err))
      if (err.response?.status === 409 || err.response?.status === 400) {
        setSlot('')
        setSlotObj(null)
        setRefresh((n) => n + 1)
      }
    } finally {
      setBusy(false)
    }
  }

  function handleCopy() {
    if (!result?.reference_code) return
    navigator.clipboard.writeText(result.reference_code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    }).catch(() => {})
  }

  if (result) return (
    <Card className="mx-auto max-w-xl text-center">
      <div className="text-4xl">📅</div>
      <h1 className="mt-2 text-xl font-bold">Appointment request saved</h1>
      
      <div className="mt-2">
        <Badge value={result.status} />
      </div>

      <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-left text-sm text-amber-900">
        <p className="font-semibold text-amber-950">⏳ Pending Staff Approval</p>
        <p className="mt-1 text-xs text-amber-800 leading-relaxed">
          Your appointment request has been recorded in the system and is awaiting review and confirmation by the reception team. You will be notified once it is approved.
        </p>
      </div>

      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-left">
        <div className="flex items-center justify-between border-b border-slate-200 pb-3">
          <div>
            <span className="block text-xs font-medium text-slate-500 uppercase tracking-wider">Reference Code</span>
            <span className="font-mono text-lg font-bold text-indigo-700">{result.reference_code}</span>
          </div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={handleCopy}
            className="flex items-center gap-1.5 font-medium"
          >
            {copied ? '✓ Copied' : '📋 Copy code'}
          </Button>
        </div>

        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between"><dt className="text-slate-500">Scheduled for</dt><dd className="font-medium text-slate-800">{fmtDateTime(result.start_at)}</dd></div>
          <div className="flex justify-between"><dt className="text-slate-500">Staff member</dt><dd className="font-medium text-slate-800">{result.staff_name}</dd></div>
          <div className="flex justify-between"><dt className="text-slate-500">Department</dt><dd className="font-medium text-slate-800">{result.department_name}</dd></div>
          <div className="flex justify-between"><dt className="text-slate-500">Current status</dt><dd className="font-medium capitalize text-amber-700">{result.status}</dd></div>
        </dl>
      </div>

      {result.message && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3 text-left text-xs text-slate-600 shadow-xs">
          <p className="font-semibold text-slate-700 mb-1">Notification Status:</p>
          <p>{result.message}</p>
        </div>
      )}

      <div className="mt-5 rounded-lg bg-indigo-50/70 p-3 text-left text-xs text-indigo-900 border border-indigo-100">
        <p className="font-semibold mb-1">Checking appointment status:</p>
        <p>
          You can check the status of your appointment at any time on the{' '}
          <Link to="/status" className="font-semibold text-indigo-700 underline hover:text-indigo-900">
            Check Status page
          </Link>{' '}
          using your reference code <code className="rounded bg-indigo-100 px-1 py-0.5 font-mono">{result.reference_code}</code> and your registered phone number.
        </p>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        {user ? (
          <Link to="/my-appointments">
            <Button variant="primary">View in My Appointments</Button>
          </Link>
        ) : (
          <Link to="/status">
            <Button variant="primary">Check Status Now</Button>
          </Link>
        )}
        <Button
          variant="secondary"
          onClick={() => {
            setResult(null)
            setSlot('')
            setSlotObj(null)
            setF({ full_name: user?.name || '', phone: '', email: user?.email || '', purpose: '' })
          }}
        >
          Book another appointment
        </Button>
      </div>
    </Card>
  )

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="text-2xl font-bold">Book an appointment</h1>
        <p className="text-sm text-slate-500">
          Only slots that are genuinely free are shown. Your request is confirmed by the reception team.
        </p>
        {!user ? (
          <div className="mt-2 text-xs text-slate-500">
            Booking as guest. Have an account?{' '}
            <Link to="/admin/login" className="text-indigo-600 underline hover:text-indigo-800">
              Sign in
            </Link>{' '}
            to automatically link appointments to your account.
          </div>
        ) : (
          <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1 text-xs text-indigo-700 border border-indigo-100">
            <span>✓ Logged in as <strong>{user.name}</strong> ({user.email || user.role}). Bookings will be linked to your account.</span>
          </div>
        )}
      </div>

      {loadError ? (
        <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <span>{loadError}</span>
          <Button variant="secondary" size="sm" onClick={() => setRefresh((n) => n + 1)}>Retry</Button>
        </div>
      ) : null}

      <Card className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="1. Department">
            <Select
              value={deptId}
              onChange={(e) => {
                setDeptId(e.target.value)
                setStaffId('')
                setSlot('')
                setSlotObj(null)
              }}
            >
              <option value="">Select department…</option>
              {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </Field>
          <Field label="2. Person to meet">
            <Select
              value={staffId}
              disabled={!dept}
              onChange={(e) => {
                setStaffId(e.target.value)
                setSlot('')
                setSlotObj(null)
              }}
            >
              <option value="">Select person to meet…</option>
              {dept && <option value="any">Any available staff member (Auto-assign)</option>}
              {(dept?.staff || []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.full_name}{s.designation ? ` — ${s.designation}` : ''}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {deptId && (
          <div className="pt-2">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-700">3. Live available time slots</span>
              {staffId === 'any' && (
                <span className="text-xs font-medium text-indigo-600">Showing all free slots in {dept?.name}</span>
              )}
            </div>
            <SlotPicker
              staffId={staffId}
              departmentId={deptId}
              value={slot}
              onPick={setSlot}
              onSlotSelect={setSlotObj}
              refreshKey={refresh}
            />
          </div>
        )}
      </Card>

      {slot && (
        <Card>
          <h2 className="mb-3 font-semibold text-slate-800">
            4. Your details — {fmtDateTime(slot)}
            {slotObj?.staff_name && (
              <span className="ml-2 text-sm font-normal text-slate-500">with {slotObj.staff_name}</span>
            )}
          </h2>
          <form className="space-y-4" onSubmit={submit}>
            <Field label="Full name">
              <Input required minLength={2} maxLength={100} value={f.full_name} onChange={set('full_name')} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Phone number">
                <Input required type="tel" placeholder="+91..." value={f.phone} onChange={set('phone')} />
              </Field>
              <Field label="E-mail (optional)">
                <Input type="email" placeholder="name@example.com" value={f.email} onChange={set('email')} />
              </Field>
            </div>
            <Field label="Purpose of the appointment">
              <Input required maxLength={255} placeholder="Brief reason for your visit" value={f.purpose} onChange={set('purpose')} />
            </Field>
            <Alert>{error}</Alert>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? 'Saving…' : 'Request appointment'}
            </Button>
          </form>
        </Card>
      )}
    </div>
  )
}
