import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { WEEKDAYS } from '../../api/format'
import { Alert, Badge, Button, Card, Field, Input, Modal, Select, Spinner, Textarea } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

const t5 = (t) => (t || '').slice(0, 5)

function DeptForm({ dept, onClose, onSaved }) {
  const [f, setF] = useState({ name: '', description: '', location: '', phone: '', working_hours: '', is_active: true, ...dept })
  const [error, setError] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function submit(e) {
    e.preventDefault()
    const body = { name: f.name, is_active: f.is_active, ...Object.fromEntries(['description', 'location', 'phone', 'working_hours'].map((k) => [k, f[k] || null])) }
    try { dept?.id ? await api.put(`/api/admin/departments/${dept.id}`, body) : await api.post('/api/admin/departments', body); onSaved() } catch (err) { setError(errorMessage(err)) }
  }
  return (
    <Modal title={dept?.id ? 'Edit department' : 'New department'} onClose={onClose}>
      <form className="space-y-3" onSubmit={submit}>
        <Field label="Name"><Input required value={f.name} onChange={set('name')} /></Field>
        <Field label="Description"><Textarea value={f.description || ''} onChange={set('description')} /></Field>
        <div className="grid grid-cols-2 gap-3"><Field label="Location"><Input value={f.location || ''} onChange={set('location')} /></Field><Field label="Phone"><Input value={f.phone || ''} onChange={set('phone')} /></Field></div>
        <Field label="Working hours"><Input value={f.working_hours || ''} onChange={set('working_hours')} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Active (shown to visitors)</label>
        <Alert>{error}</Alert><div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Close</Button><Button type="submit">Save</Button></div>
      </form>
    </Modal>
  )
}

function StaffForm({ member, depts, onClose, onSaved }) {
  const [f, setF] = useState({ department_id: depts[0]?.id || '', full_name: '', designation: '', email: '', is_active: true, ...member })
  const [windows, setWindows] = useState((member?.availability || []).map((w) => ({ weekday: w.weekday, start_time: t5(w.start_time), end_time: t5(w.end_time) })))
  const [error, setError] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const upd = (i, k, v) => setWindows(windows.map((w, j) => (j === i ? { ...w, [k]: v } : w)))
  async function submit(e) {
    e.preventDefault(); setError('')
    try {
      const body = { department_id: Number(f.department_id), full_name: f.full_name, is_active: f.is_active, designation: f.designation || null, email: f.email || null }
      const { data } = member?.id ? await api.put(`/api/admin/staff/${member.id}`, body) : await api.post('/api/admin/staff', body)
      await api.put(`/api/admin/staff/${data.id}/availability`, { windows: windows.map((w) => ({ ...w, weekday: Number(w.weekday), start_time: `${w.start_time}:00`, end_time: `${w.end_time}:00` })) })
      onSaved()
    } catch (err) { setError(errorMessage(err)) }
  }
  return (
    <Modal title={member?.id ? 'Edit staff member' : 'New staff member'} onClose={onClose}>
      <form className="space-y-3" onSubmit={submit}>
        <Field label="Department"><Select value={f.department_id} onChange={set('department_id')}>{depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
        <Field label="Full name"><Input required value={f.full_name} onChange={set('full_name')} /></Field>
        <div className="grid grid-cols-2 gap-3"><Field label="Designation"><Input value={f.designation || ''} onChange={set('designation')} /></Field><Field label="E-mail (internal only)"><Input type="email" value={f.email || ''} onChange={set('email')} /></Field></div>
        <div>
          <div className="mb-1 flex items-center justify-between text-sm font-medium">Weekly availability<Button type="button" size="sm" variant="secondary" onClick={() => setWindows([...windows, { weekday: 0, start_time: '09:00', end_time: '17:00' }])}>+ Add window</Button></div>
          {windows.length === 0 && <p className="text-xs text-slate-500">No windows: this person cannot be booked.</p>}
          {windows.map((w, i) => (
            <div key={i} className="mb-2 grid grid-cols-[1fr_auto_auto_auto] items-center gap-2">
              <Select value={w.weekday} onChange={(e) => upd(i, 'weekday', e.target.value)} aria-label="Weekday">{WEEKDAYS.map((d, n) => <option key={d} value={n}>{d}</option>)}</Select>
              <Input type="time" value={w.start_time} onChange={(e) => upd(i, 'start_time', e.target.value)} aria-label="Start" /><Input type="time" value={w.end_time} onChange={(e) => upd(i, 'end_time', e.target.value)} aria-label="End" />
              <button type="button" className="text-red-600" onClick={() => setWindows(windows.filter((_, j) => j !== i))} aria-label="Remove">✕</button>
            </div>))}
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Active (can be booked)</label>
        <Alert>{error}</Alert><div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Close</Button><Button type="submit">Save</Button></div>
      </form>
    </Modal>
  )
}

export default function DirectoryAdmin() {
  const { isAdmin } = useAuth()
  const [depts, setDepts] = useState(null)
  const [staff, setStaff] = useState([])
  const [error, setError] = useState('')
  const [modal, setModal] = useState(null)
  const load = useCallback(() => {
    Promise.all([api.get('/api/admin/departments'), api.get('/api/admin/staff')]).then(([d, s]) => { setDepts(d.data); setStaff(s.data) }).catch((e) => setError(errorMessage(e)))
  }, [])
  useEffect(() => {
    load()
  }, [load])
  const saved = () => { setModal(null); load() }
  if (!depts) return error ? <Alert>{error}</Alert> : <Spinner />
  const deptName = (id) => depts.find((d) => d.id === id)?.name
  return (
    <div className="space-y-8">
      <Alert>{error}</Alert>
      <section>
        <div className="mb-3 flex items-center justify-between"><h1 className="text-2xl font-bold">Departments</h1>{isAdmin && <Button onClick={() => setModal({ type: 'dept' })}>+ Department</Button>}</div>
        <div className="grid gap-3 md:grid-cols-2">{depts.map((d) => (
          <Card key={d.id}><div className="flex items-start justify-between"><div><h2 className="font-semibold">{d.name}</h2><p className="text-sm text-slate-500">{[d.location, d.working_hours, d.phone].filter(Boolean).join(' · ')}</p></div>{!d.is_active && <Badge value="cancelled" />}</div>
            {isAdmin && <div className="mt-3 flex gap-2"><Button size="sm" variant="secondary" onClick={() => setModal({ type: 'dept', dept: d })}>Edit</Button></div>}</Card>))}</div>
      </section>
      <section>
        <div className="mb-3 flex items-center justify-between"><h2 className="text-2xl font-bold">Staff</h2>{isAdmin && depts.length > 0 && <Button onClick={() => setModal({ type: 'staff' })}>+ Staff member</Button>}</div>
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white"><table className="w-full min-w-[600px] text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Name</th><th className="p-3">Department</th><th className="p-3">Availability windows</th><th className="p-3">Active</th><th className="p-3" /></tr></thead>
          <tbody className="divide-y divide-slate-100">{staff.map((s) => (
            <tr key={s.id}><td className="p-3">{s.full_name}<div className="text-xs text-slate-500">{s.designation}</div></td><td className="p-3">{deptName(s.department_id)}</td><td className="p-3">{s.availability.length}</td><td className="p-3">{s.is_active ? 'Yes' : 'No'}</td>
              <td className="p-3">{isAdmin && <Button size="sm" variant="secondary" onClick={() => setModal({ type: 'staff', member: s })}>Edit</Button>}</td></tr>))}</tbody></table></div>
      </section>
      {modal?.type === 'dept' && <DeptForm dept={modal.dept} onClose={() => setModal(null)} onSaved={saved} />}
      {modal?.type === 'staff' && <StaffForm member={modal.member} depts={depts} onClose={() => setModal(null)} onSaved={saved} />}
    </div>
  )
}
