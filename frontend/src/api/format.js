// The API sends naive local times ("2026-10-23T10:00:00"); the browser shows them exactly as given.
export const fmtDateTime = (v) => (v ? new Date(v).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—')
export const fmtTime = (v) => (v ? new Date(v).toLocaleTimeString([], { timeStyle: 'short' }) : '—')
export const fmtDate = (v) => (v ? new Date(v).toLocaleDateString([], { dateStyle: 'medium' }) : '—')
export const fmtSlotRange = (start, end) => {
  if (!start) return '—'
  if (!end) return fmtTime(start)
  return `${fmtTime(start)} – ${fmtTime(end)}`
}
const pad = (n) => String(n).padStart(2, '0')
export const toISODate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export const todayISO = () => toISODate(new Date())
export const addDaysISO = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return toISODate(d) }
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
