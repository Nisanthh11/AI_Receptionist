import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { Alert, Badge, Button, Card, Field, Input, Select, Spinner } from '../../components/ui'

export default function Users() {
  const [users, setUsers] = useState(null)
  const [f, setF] = useState({ email: '', full_name: '', password: '', role: 'receptionist' })
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const load = useCallback(() => { api.get('/api/admin/users').then((r) => setUsers(r.data)).catch((e) => setError(errorMessage(e))) }, [])
  useEffect(() => {
    load()
  }, [load])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function create(e) {
    e.preventDefault(); setError(''); setNotice('')
    try { await api.post('/api/admin/users', f); setF({ email: '', full_name: '', password: '', role: 'receptionist' }); setNotice('User created.'); load() } catch (err) { setError(errorMessage(err)) }
  }
  async function toggle(u) {
    setError(''); setNotice('')
    try { await api.patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active }); load() } catch (err) { setError(errorMessage(err)) }
  }
  if (!users) return error ? <Alert>{error}</Alert> : <Spinner />
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">User accounts</h1>
      <Alert>{error}</Alert><Alert kind="success">{notice}</Alert>
      <Card>
        <h2 className="mb-3 font-semibold">Add a staff account</h2>
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={create}>
          <Field label="Full name"><Input required value={f.full_name} onChange={set('full_name')} /></Field>
          <Field label="E-mail"><Input required type="email" value={f.email} onChange={set('email')} /></Field>
          <Field label="Temporary password" hint="At least 8 characters"><Input required type="password" minLength={8} autoComplete="new-password" value={f.password} onChange={set('password')} /></Field>
          <Field label="Role"><Select value={f.role} onChange={set('role')}><option value="receptionist">Receptionist</option><option value="admin">Administrator</option></Select></Field>
          <div className="sm:col-span-2"><Button type="submit">Create account</Button></div>
        </form>
      </Card>
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white"><table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Name</th><th className="p-3">E-mail</th><th className="p-3">Role</th><th className="p-3">Status</th><th className="p-3" /></tr></thead>
        <tbody className="divide-y divide-slate-100">{users.map((u) => (
          <tr key={u.id}><td className="p-3">{u.full_name}</td><td className="p-3">{u.email}</td><td className="p-3 capitalize">{u.role}</td><td className="p-3"><Badge value={u.is_active ? 'confirmed' : 'cancelled'} /></td>
            <td className="p-3"><Button size="sm" variant="secondary" onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</Button></td></tr>))}</tbody></table></div>
    </div>
  )
}
