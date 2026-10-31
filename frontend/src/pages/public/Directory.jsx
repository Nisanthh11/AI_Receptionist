import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { Alert, Card, Input, Spinner } from '../../components/ui'

export default function Directory() {
  const [depts, setDepts] = useState(null)
  const [faqs, setFaqs] = useState(null)
  const [q, setQ] = useState('')
  const [error, setError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setError('')
    setDepts(null)
    setFaqs(null)
    Promise.all([api.get('/api/public/departments'), api.get('/api/public/faqs')])
      .then(([d, f]) => {
        if (!cancelled) {
          setDepts(d.data || [])
          setFaqs(f.data || [])
        }
      })
      .catch((e) => {
        if (!cancelled) setError(errorMessage(e))
      })
    return () => { cancelled = true }
  }, [reloadKey])

  if (error) return (
    <div className="mx-auto max-w-md space-y-4 py-8 text-center">
      <Alert>{error}</Alert>
      <button
        onClick={() => setReloadKey((k) => k + 1)}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
      >
        Retry
      </button>
    </div>
  )
  if (!depts || !faqs) return <Spinner />
  const match = (s) => !q || s.toLowerCase().includes(q.toLowerCase())
  return (
    <div className="space-y-8">
      <div className="max-w-md"><Input placeholder="Search departments and FAQs…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" /></div>
      <section>
        <h1 className="mb-3 text-2xl font-bold">Departments</h1>
        {depts.length === 0 && <p className="text-sm text-slate-500">No departments have been added yet.</p>}
        <div className="grid gap-4 md:grid-cols-2">
          {depts.filter((d) => match(`${d.name} ${d.description || ''} ${(d.staff || []).map((s) => s.full_name).join(' ')}`)).map((d) => (
            <Card key={d.id}>
              <h2 className="font-semibold">{d.name}</h2>
              {d.description && <p className="mt-1 text-sm text-slate-600">{d.description}</p>}
              <ul className="mt-2 space-y-0.5 text-sm text-slate-600">
                {d.location && <li>📍 {d.location}</li>}{d.working_hours && <li>🕒 {d.working_hours}</li>}{d.phone && <li>📞 {d.phone}</li>}
              </ul>
              {(d.staff || []).length > 0 && <p className="mt-3 text-sm"><span className="font-medium">Staff:</span> {(d.staff || []).map((s) => s.full_name).join(', ')}</p>}
              <Link to="/book" className="mt-3 inline-block text-sm font-medium text-indigo-600 hover:underline">Book an appointment →</Link>
            </Card>
          ))}
        </div>
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">Frequently asked questions</h2>
        {faqs.length === 0 && <p className="text-sm text-slate-500">No FAQs have been added yet.</p>}
        <div className="space-y-2">
          {faqs.filter((f) => match(`${f.question} ${f.answer}`)).map((f) => (
            <details key={f.id} className="rounded-xl border border-slate-200 bg-white p-4"><summary className="cursor-pointer font-medium">{f.question}</summary><p className="mt-2 text-sm text-slate-600">{f.answer}</p></details>
          ))}
        </div>
      </section>
    </div>
  )
}
