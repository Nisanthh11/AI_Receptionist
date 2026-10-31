import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { Alert, Button, Input } from '../../components/ui'

export default function Chat() {
  const [messages, setMessages] = useState([{ from: 'bot', text: "Hello! I'm the virtual receptionist. Ask me about departments, working hours or appointments." }])
  const [suggestions, setSuggestions] = useState(['What are your working hours?', 'Which departments do you have?', 'I want to book an appointment'])
  const [action, setAction] = useState(null)
  const [token, setToken] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const end = useRef(null)
  const isMounted = useRef(true)

  useEffect(() => {
    isMounted.current = true
    return () => { isMounted.current = false }
  }, [])

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send(msg) {
    const m = msg.trim()
    if (!m || busy) return
    setMessages((x) => [...x, { from: 'me', text: m }]); setText(''); setBusy(true); setError(''); setAction(null)
    try {
      const { data } = await api.post('/api/public/chat', { message: m, session_token: token })
      if (!isMounted.current) return
      setToken(data.session_token)
      setMessages((x) => [...x, { from: 'bot', text: data.reply, unanswered: !data.answered_from_records }])
      setSuggestions(data.suggestions || []); setAction(data.action)
    } catch (e) {
      if (isMounted.current) setError(errorMessage(e))
    } finally {
      if (isMounted.current) setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-2xl font-bold">Ask the receptionist</h1>
      <p className="mb-4 text-sm text-slate-500">Answers come from our stored FAQs and directory. This is a rule-based assistant, not an AI language model.</p>
      <div className="h-[55vh] space-y-3 overflow-y-auto rounded-xl border border-slate-200 bg-white p-4" aria-live="polite">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.from === 'me' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${m.from === 'me' ? 'bg-indigo-600 text-white' : m.unanswered ? 'bg-amber-50 text-amber-900' : 'bg-slate-100'}`}>{m.text}</div>
          </div>
        ))}
        {busy && <p className="text-xs text-slate-400">Receptionist is typing…</p>}
        <div ref={end} />
      </div>
      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
      <div className="mt-3 flex flex-wrap gap-2">
        {action === 'book_appointment' && <Link to="/book" className="rounded-full bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white">Go to booking form</Link>}
        {suggestions.map((s) => <button key={s} onClick={() => send(s)} className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm hover:border-indigo-400">{s}</button>)}
      </div>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={500} placeholder="Type your question…" aria-label="Your message" />
        <Button type="submit" disabled={busy || !text.trim()}>Send</Button>
      </form>
    </div>
  )
}
