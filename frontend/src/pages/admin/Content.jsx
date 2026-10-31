import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { Alert, Button, Card, Field, Input, Modal, Spinner, Textarea } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

const ORG_FIELDS = [['organization_name', 'Organisation name'], ['welcome_message', 'Welcome message'], ['working_hours', 'Working hours'], ['address', 'Address'], ['contact_phone', 'Contact phone'], ['contact_email', 'Contact e-mail']]

function FaqForm({ faq, onClose, onSaved }) {
  const [f, setF] = useState({ question: '', answer: '', keywords: '', category: '', is_active: true, ...faq })
  const [error, setError] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function submit(e) {
    e.preventDefault()
    const body = { question: f.question, answer: f.answer, is_active: f.is_active, keywords: f.keywords || null, category: f.category || null }
    try { faq?.id ? await api.put(`/api/admin/faqs/${faq.id}`, body) : await api.post('/api/admin/faqs', body); onSaved() } catch (err) { setError(errorMessage(err)) }
  }
  return (
    <Modal title={faq?.id ? 'Edit FAQ' : 'New FAQ'} onClose={onClose}>
      <form className="space-y-3" onSubmit={submit}>
        <Field label="Question"><Input required value={f.question} onChange={set('question')} /></Field>
        <Field label="Answer"><Textarea required value={f.answer} onChange={set('answer')} /></Field>
        <Field label="Keywords" hint="Extra words visitors might use, used for chat matching"><Input value={f.keywords || ''} onChange={set('keywords')} /></Field>
        <Field label="Category"><Input value={f.category || ''} onChange={set('category')} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Active</label>
        <Alert>{error}</Alert><div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Close</Button><Button type="submit">Save</Button></div>
      </form>
    </Modal>
  )
}

export default function Content() {
  const { isAdmin } = useAuth()
  const [faqs, setFaqs] = useState(null)
  const [org, setOrg] = useState({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(null)
  const load = useCallback(() => {
    Promise.all([api.get('/api/admin/faqs'), api.get('/api/admin/organization')]).then(([f, o]) => { setFaqs(f.data); setOrg(o.data) }).catch((e) => setError(errorMessage(e)))
  }, [])
  useEffect(() => {
    load()
  }, [load])

  async function saveOrg(e) {
    e.preventDefault(); setError(''); setNotice('')
    try { await api.put('/api/admin/organization', { values: Object.fromEntries(ORG_FIELDS.map(([k]) => [k, org[k]]).filter(([, v]) => v && v.trim())) }); setNotice('Organisation information saved.') } catch (err) { setError(errorMessage(err)) }
  }
  async function remove(f) {
    if (!window.confirm(`Delete this FAQ?\n\n${f.question}`)) return
    try { await api.delete(`/api/admin/faqs/${f.id}`); load() } catch (err) { setError(errorMessage(err)) }
  }
  if (!faqs) return error ? <Alert>{error}</Alert> : <Spinner />
  return (
    <div className="space-y-8">
      <Alert>{error}</Alert><Alert kind="success">{notice}</Alert>
      <Card>
        <h1 className="mb-1 text-2xl font-bold">Organisation information</h1>
        <p className="mb-4 text-sm text-slate-500">Shown on the public site and used by the chat for working-hours answers. Leave blank if unknown - the chat will say it has no information rather than guess.</p>
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={saveOrg}>
          {ORG_FIELDS.map(([k, label]) => <Field key={k} label={label}><Input disabled={!isAdmin} value={org[k] || ''} onChange={(e) => setOrg({ ...org, [k]: e.target.value })} /></Field>)}
          {isAdmin && <div className="sm:col-span-2"><Button type="submit">Save information</Button></div>}
        </form>
      </Card>
      <section>
        <div className="mb-3 flex items-center justify-between"><h2 className="text-2xl font-bold">FAQs</h2>{isAdmin && <Button onClick={() => setModal({})}>+ FAQ</Button>}</div>
        <div className="space-y-2">{faqs.length === 0 && <p className="text-sm text-slate-500">No FAQs yet.</p>}
          {faqs.map((f) => (
            <Card key={f.id} className="!p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-medium">{f.question} {!f.is_active && <span className="ml-1 rounded bg-slate-200 px-1.5 text-xs">inactive</span>}</p><p className="mt-1 text-sm text-slate-600">{f.answer}</p>{f.category && <p className="mt-1 text-xs text-slate-400">{f.category}</p>}</div>
              {isAdmin && <div className="flex shrink-0 gap-1"><Button size="sm" variant="secondary" onClick={() => setModal({ faq: f })}>Edit</Button><Button size="sm" variant="danger" onClick={() => remove(f)}>Delete</Button></div>}</div></Card>))}</div>
      </section>
      {modal && <FaqForm faq={modal.faq} onClose={() => setModal(null)} onSaved={() => { setModal(null); load() }} />}
    </div>
  )
}
