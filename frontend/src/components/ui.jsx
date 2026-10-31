import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { addDaysISO, fmtSlotRange, fmtTime, todayISO } from '../api/format'

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

/** Live slot picker from server. Supports staffId and/or departmentId. Disables unavailable/booked slots with reason. */
export function SlotPicker({ staffId, departmentId, value, onPick, refreshKey = 0, onSlotSelect }) {
  const [date, setDate] = useState(addDaysISO(1))
  const [slotsData, setSlotsData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [localRefresh, setLocalRefresh] = useState(0)

  useEffect(() => {
    const hasStaff = Boolean(staffId)
    const hasDept = Boolean(departmentId)
    if (!hasStaff && !hasDept) return
    if (!date) return

    let cancelled = false
    setLoading(true)
    setError('')
    setSlotsData(null)

    const params = { date }
    if (staffId && staffId !== 'any') {
      params.staff_id = staffId
    }
    if (departmentId) {
      params.department_id = departmentId
    }

    api.get('/api/public/slots', { params })
      .then((r) => {
        if (!cancelled) {
          setSlotsData(r.data)
          setLoading(false)
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(errorMessage(e))
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [staffId, departmentId, date, refreshKey, localRefresh])

  const allSlots = slotsData?.all_slots || (slotsData?.slots ? slotsData.slots.map((s) => ({ start_at: s, is_available: true })) : null)
  const availableCount = slotsData?.slots?.length || 0

  return (
    <div className="space-y-3.5 rounded-xl border border-slate-200/80 bg-slate-50/50 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-full sm:w-60">
          <Field label="Appointment Date">
            <Input
              type="date"
              min={todayISO()}
              value={date}
              onChange={(e) => {
                setDate(e.target.value)
                onPick('')
                onSlotSelect?.(null)
              }}
            />
          </Field>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden sm:flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 border border-emerald-200">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
            </span>
            Live Availability
          </div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setLocalRefresh((n) => n + 1)}
            disabled={loading}
            title="Refresh available slots"
            className="flex items-center gap-1"
          >
            <span>↻</span> Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <span>{error}</span>
          <Button type="button" variant="secondary" size="sm" onClick={() => setLocalRefresh((n) => n + 1)}>Retry</Button>
        </div>
      )}

      {loading && !error && <Spinner text="Checking live slot availability…" />}

      {!loading && allSlots && allSlots.length === 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-center text-sm text-amber-900">
          No working hours or appointment slots scheduled for this date. Please select another date.
        </div>
      )}

      {!loading && allSlots && allSlots.length > 0 && availableCount === 0 && (
        <Alert kind="info">
          All appointment slots on this date are fully booked or unavailable. Please choose another date.
        </Alert>
      )}

      {!loading && allSlots && allSlots.length > 0 && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
            {allSlots.map((item) => {
              const isSelected = value === item.start_at
              const isAvailable = Boolean(item.is_available)
              const timeRange = fmtSlotRange(item.start_at, item.end_at)

              let reasonLabel = 'Unavailable'
              if (item.reason === 'booked') reasonLabel = 'Booked'
              else if (item.reason === 'break') reasonLabel = 'Break'
              else if (item.reason === 'past') reasonLabel = 'Past'
              else if (item.reason === 'lead_time') reasonLabel = 'Lead time'

              if (!isAvailable) {
                return (
                  <div
                    key={item.start_at}
                    className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-slate-100/70 p-2 text-center text-xs text-slate-400 cursor-not-allowed select-none"
                    title={`Slot ${timeRange} is ${reasonLabel.toLowerCase()}`}
                    aria-disabled="true"
                  >
                    <span className="font-mono text-xs line-through text-slate-400">{timeRange}</span>
                    <span className="mt-0.5 inline-block rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                      {reasonLabel}
                    </span>
                  </div>
                )
              }

              return (
                <button
                  key={item.start_at}
                  type="button"
                  onClick={() => {
                    onPick(item.start_at)
                    onSlotSelect?.(item)
                  }}
                  className={`group flex flex-col items-center justify-center rounded-lg border p-2 text-center text-xs transition font-medium focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                    isSelected
                      ? 'border-indigo-600 bg-indigo-600 text-white shadow-sm ring-2 ring-indigo-300'
                      : 'border-slate-300 bg-white text-slate-800 hover:border-indigo-500 hover:bg-indigo-50/50 hover:text-indigo-900 shadow-xs'
                  }`}
                >
                  <span className={`font-mono text-xs font-semibold ${isSelected ? 'text-white' : 'text-slate-900 group-hover:text-indigo-950'}`}>
                    {timeRange}
                  </span>
                  {item.staff_name && (!staffId || staffId === 'any') && (
                    <span className={`mt-0.5 max-w-full truncate text-[10px] ${isSelected ? 'text-indigo-100' : 'text-slate-500 group-hover:text-indigo-700'}`}>
                      with {item.staff_name}
                    </span>
                  )}
                  <span className={`mt-0.5 inline-block text-[10px] font-medium ${isSelected ? 'text-indigo-100' : 'text-emerald-600'}`}>
                    {isSelected ? '✓ Selected' : '● Available'}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200/60 pt-2 text-[11px] text-slate-500">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-emerald-500"></span> Available
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-indigo-600"></span> Selected
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-slate-300"></span> Booked / Break
              </span>
            </div>
            {availableCount > 0 && (
              <span className="font-medium text-slate-600">
                {availableCount} {availableCount === 1 ? 'slot available' : 'slots available'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
