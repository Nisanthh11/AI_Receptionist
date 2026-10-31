import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { fmtDateTime } from '../../api/format'
import { Alert, Badge, Button, Field, Input, Modal, Pagination, Select, Spinner } from '../../components/ui'

const PAGE_SIZE = 15

function NewVisit({ staff, onDone, onClose }) {
  const [f, setF] = useState({ full_name: '', phone: '', email: '', purpose: '', staff_id: '', check_in_now: true })
  const [error, setError] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  async function submit(e) {
    e.preventDefault(); setError('')
    try {
      await api.post('/api/admin/visits', { full_name: f.full_name, phone: f.phone, purpose: f.purpose, check_in_now: f.check_in_now, ...(f.email && { email: f.email }), ...(f.staff_id && { staff_id: Number(f.staff_id) }) })
      onDone()
    } catch (err) { setError(errorMessage(err)) }
  }
  return (
    <Modal title="Register a walk-in visitor" onClose={onClose}>
      <form className="space-y-3" onSubmit={submit}>
        <Field label="Full name"><Input required value={f.full_name} onChange={set('full_name')} /></Field>
        <div className="grid grid-cols-2 gap-3"><Field label="Phone"><Input required type="tel" value={f.phone} onChange={set('phone')} /></Field><Field label="E-mail (optional)"><Input type="email" value={f.email} onChange={set('email')} /></Field></div>
        <Field label="Purpose"><Input required value={f.purpose} onChange={set('purpose')} /></Field>
        <Field label="Host"><Select value={f.staff_id} onChange={set('staff_id')}><option value="">—</option>{staff.map((s) => <option key={s.id} value={s.id}>{s.full_name}</option>)}</Select></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.check_in_now} onChange={set('check_in_now')} /> Check in immediately</label>
        <Alert>{error}</Alert>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Close</Button><Button type="submit">Save</Button></div>
      </form>
    </Modal>
  )
}

function History({ id, onClose }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    api.get(`/api/admin/visitors/${id}`)
      .then((r) => { if (!cancelled) setD(r.data) })
      .catch((e) => { if (!cancelled) setError(errorMessage(e)) })
    return () => { cancelled = true }
  }, [id])
  return (
    <Modal title="Visitor history" onClose={onClose}>
      <Alert>{error}</Alert>{!d && !error && <Spinner />}
      {d && <div className="space-y-4 text-sm">
        <p><b>{d.visitor.full_name}</b> · {d.visitor.phone}{d.visitor.email && ` · ${d.visitor.email}`}</p>
        <div><h4 className="mb-1 font-semibold">Visits ({d.visits.length})</h4>
          <ul className="space-y-1">{d.visits.map((v) => <li key={v.id} className="flex justify-between"><span>{fmtDateTime(v.check_in_at || v.registered_at)} — {v.purpose}</span><Badge value={v.status} /></li>)}</ul></div>
        <div><h4 className="mb-1 font-semibold">Appointments ({d.appointments.length})</h4>
          <ul className="space-y-1">{d.appointments.map((a) => <li key={a.id} className="flex justify-between"><span>{fmtDateTime(a.start_at)} with {a.staff.full_name}</span><Badge value={a.status} /></li>)}</ul></div>
      </div>}
    </Modal>
  )
}

export default function Visitors() {
  const [tab, setTab] = useState('visits')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [staff, setStaff] = useState([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [history, setHistory] = useState(null)

  const load = useCallback(() => {
    const url = tab === 'visits' ? '/api/admin/visits' : '/api/admin/visitors'
    const params = { page, page_size: PAGE_SIZE, ...(q && { q }), ...(tab === 'visits' && status && { status }) }
    api.get(url, { params }).then((r) => { setData(r.data); setError('') }).catch((e) => setError(errorMessage(e)))
  }, [tab, status, q, page])
  useEffect(() => { setData(null); const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])
  useEffect(() => {
    let cancelled = false
    api.get('/api/admin/staff')
      .then((r) => { if (!cancelled) setStaff(r.data.filter((s) => s.is_active)) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  async function action(id, what) {
    setError(''); setNotice('')
    try { await api.post(`/api/admin/visits/${id}/${what}`); setNotice(what === 'check-in' ? 'Visitor checked in.' : 'Visitor checked out.'); load() } catch (e) { setError(errorMessage(e)) }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h1 className="text-2xl font-bold">Visitors</h1><Button onClick={() => setShowNew(true)}>+ Walk-in visitor</Button></div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex rounded-lg border border-slate-300 bg-white p-0.5 text-sm">
          {[['visits', 'Visits'], ['people', 'Visitor records']].map(([k, l]) => <button key={k} onClick={() => { setTab(k); setPage(1) }} className={`rounded-md px-3 py-1.5 ${tab === k ? 'bg-indigo-600 text-white' : ''}`}>{l}</button>)}
        </div>
        <div className="w-56"><Input placeholder="Search…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} aria-label="Search" /></div>
        {tab === 'visits' && <div className="w-48"><Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} aria-label="Status"><option value="">All visits</option><option value="registered">Waiting for check-in</option><option value="checked_in">On site</option><option value="checked_out">Checked out</option></Select></div>}
      </div>
      <Alert>{error}</Alert><Alert kind="success">{notice}</Alert>
      {!data ? <Spinner /> : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          {tab === 'visits' ? (
            <table className="w-full min-w-[720px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Visitor</th><th className="p-3">Purpose / host</th><th className="p-3">Check-in</th><th className="p-3">Check-out</th><th className="p-3">Status</th><th className="p-3">Actions</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{data.items.length === 0 && <tr><td colSpan="6" className="p-6 text-center text-slate-500">No visits found.</td></tr>}
                {data.items.map((v) => (
                  <tr key={v.id}><td className="p-3">{v.visitor.full_name}<div className="text-xs text-slate-500">{v.visitor.phone}</div></td>
                    <td className="p-3">{v.purpose}<div className="text-xs text-slate-500">{v.staff ? `Host: ${v.staff.full_name}` : 'No host'} · <span className="font-mono">{v.reference_code}</span></div></td>
                    <td className="p-3">{fmtDateTime(v.check_in_at)}</td><td className="p-3">{fmtDateTime(v.check_out_at)}</td><td className="p-3"><Badge value={v.status} /></td>
                    <td className="p-3"><div className="flex gap-1">
                      {v.status === 'registered' && <Button size="sm" variant="success" onClick={() => action(v.id, 'check-in')}>Check in</Button>}
                      {v.status === 'checked_in' && <Button size="sm" variant="secondary" onClick={() => action(v.id, 'check-out')}>Check out</Button>}
                      <Button size="sm" variant="secondary" onClick={() => setHistory(v.visitor.id)}>History</Button></div></td></tr>))}</tbody></table>
          ) : (
            <table className="w-full min-w-[560px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Name</th><th className="p-3">Phone</th><th className="p-3">E-mail</th><th className="p-3">First seen</th><th className="p-3" /></tr></thead>
              <tbody className="divide-y divide-slate-100">{data.items.length === 0 && <tr><td colSpan="5" className="p-6 text-center text-slate-500">No visitors found.</td></tr>}
                {data.items.map((v) => <tr key={v.id}><td className="p-3">{v.full_name}</td><td className="p-3">{v.phone}</td><td className="p-3">{v.email || '—'}</td><td className="p-3">{fmtDateTime(v.created_at)}</td>
                  <td className="p-3"><Button size="sm" variant="secondary" onClick={() => setHistory(v.id)}>History</Button></td></tr>)}</tbody></table>
          )}
        </div>)}
      {data && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />}
      {showNew && <NewVisit staff={staff} onClose={() => setShowNew(false)} onDone={() => { setShowNew(false); setNotice('Visitor saved.'); load() }} />}
      {history && <History id={history} onClose={() => setHistory(null)} />}
    </div>
  )
}
