import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { addDaysISO, fmtTime, todayISO } from '../api/format'

const variants = {
  primary: 'bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-indigo-300',
  secondary: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 disabled:opacity-50',
  danger: 'bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300',
  success: 'bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-emerald-300',
}
export function Button({ variant = 'primary', size = 'md', className = '', ...p }) {
  const sz = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-4 py-2 text-sm'
  return <button className={`rounded-lg font-medium transition disabled:cursor-not-allowed ${sz} ${variants[variant]} ${className}`} {...p} />
}

export const Card = ({ className = '', children }) => <div className={`rounded-xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>{children}</div>

export function Field({ label, hint, children }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}
const inputCls = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200'
export const Input = (p) => <input className={inputCls} {...p} />
export const Select = (p) => <select className={inputCls} {...p} />
export const Textarea = (p) => <textarea className={inputCls} rows={3} {...p} />

export function Alert({ kind = 'error', children }) {
  if (!children) return null
  const c = { error: 'border-red-200 bg-red-50 text-red-800', success: 'border-emerald-200 bg-emerald-50 text-emerald-800', info: 'border-sky-200 bg-sky-50 text-sky-800' }[kind]
  return <div role="alert" className={`rounded-lg border px-4 py-3 text-sm ${c}`}>{children}</div>
}

const badgeColors = {
  pending: 'bg-amber-100 text-amber-800', confirmed: 'bg-sky-100 text-sky-800', completed: 'bg-emerald-100 text-emerald-800',
  cancelled: 'bg-slate-200 text-slate-600', registered: 'bg-amber-100 text-amber-800', checked_in: 'bg-emerald-100 text-emerald-800', checked_out: 'bg-slate-200 text-slate-600',
}
export const Badge = ({ value }) => <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${badgeColors[value] || 'bg-slate-100'}`}>{String(value).replace('_', ' ')}</span>

export const Spinner = ({ text = 'Loading…' }) => <p className="py-6 text-center text-sm text-slate-500">{text}</p>

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const h = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4" onClick={onClose}>
      <div className="mt-10 w-full max-w-lg rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Pagination({ page, pageSize, total, onChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
      <span>{total} records</span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</Button>
        <span>Page {page} of {pages}</span>
        <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</Button>
      </div>
    </div>
  )
}

/** Date picker + live slot list from the server. `onPick(isoDateTime)` receives a server-provided slot. */
export function SlotPicker({ staffId, value, onPick, refreshKey = 0 }) {
  const [date, setDate] = useState(addDaysISO(1))
  const [slots, setSlots] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!staffId || !date) return
    let cancelled = false
    setSlots(null); setError('')
    api.get('/api/public/slots', { params: { staff_id: staffId, date } })
      .then((r) => !cancelled && setSlots(r.data.slots))
      .catch((e) => !cancelled && setError(errorMessage(e)))
    return () => { cancelled = true }
  }, [staffId, date, refreshKey])
  return (
    <div className="space-y-3">
      <Field label="Date"><Input type="date" min={todayISO()} value={date} onChange={(e) => { setDate(e.target.value); onPick('') }} /></Field>
      {error && <Alert>{error}</Alert>}
      {slots === null && !error && <Spinner text="Checking availability…" />}
      {slots?.length === 0 && <Alert kind="info">No free slots on this date. Please try another day.</Alert>}
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
        {slots?.map((s) => (
          <button key={s} type="button" onClick={() => onPick(s)}
            className={`rounded-lg border px-2 py-2 text-sm ${value === s ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-slate-300 bg-white hover:border-indigo-400'}`}>
            {fmtTime(s)}
          </button>
        ))}
      </div>
    </div>
  )
}
