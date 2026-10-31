import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { addDaysISO, todayISO } from '../../api/format'
import { Alert, Badge, Button, Input } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

export default function Chat() {
  const { user } = useAuth()
  const [messages, setMessages] = useState([
    {
      from: 'bot',
      text: "Hello! I'm the virtual receptionist. I can answer questions about our departments, working hours, FAQs, or guide you through booking an appointment. How can I help you today?",
    },
  ])
  const [suggestions, setSuggestions] = useState(['What are your working hours?', 'Which departments do you have?', 'I want to book an appointment'])
  const [action, setAction] = useState(null)
  const [bookingFlow, setBookingFlow] = useState(null)
  const [token, setToken] = useState(() => sessionStorage.getItem('receptionist_chat_token') || null)
  const [text, setText] = useState('')
  const [customDate, setCustomDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copiedCode, setCopiedCode] = useState(null)
  const end = useRef(null)
  const isMounted = useRef(true)

  useEffect(() => {
    isMounted.current = true
    return () => { isMounted.current = false }
  }, [])

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  // Resume or restore active session on page mount
  useEffect(() => {
    if (!token) return
    let cancelled = false
    api.get('/api/public/chat', { params: { session_token: token } })
      .then((r) => {
        if (cancelled || !isMounted.current) return
        if (r.data.booking_flow && r.data.booking_flow.step !== 'idle') {
          setBookingFlow(r.data.booking_flow)
          setSuggestions(r.data.suggestions || [])
          setAction(r.data.action)
          setMessages((prev) => [
            ...prev,
            { from: 'bot', text: r.data.reply, booking_flow: r.data.booking_flow },
          ])
        }
      })
      .catch(() => {
        // If expired or invalid, start fresh
        sessionStorage.removeItem('receptionist_chat_token')
        setToken(null)
      })
    return () => { cancelled = true }
  }, [])

  async function send(msg) {
    const m = typeof msg === 'string' ? msg.trim() : ''
    if (!m || busy) return
    setMessages((x) => [...x, { from: 'me', text: m }])
    setText('')
    setCustomDate('')
    setBusy(true)
    setError('')
    setAction(null)

    try {
      const { data } = await api.post('/api/public/chat', { message: m, session_token: token })
      if (!isMounted.current) return
      setToken(data.session_token)
      sessionStorage.setItem('receptionist_chat_token', data.session_token)

      setBookingFlow(data.booking_flow || null)
      setSuggestions(data.suggestions || [])
      setAction(data.action)

      setMessages((x) => [
        ...x,
        {
          from: 'bot',
          text: data.reply,
          unanswered: !data.answered_from_records,
          booking_flow: data.booking_flow,
          action: data.action,
        },
      ])
    } catch (e) {
      if (isMounted.current) setError(errorMessage(e))
    } finally {
      if (isMounted.current) setBusy(false)
    }
  }

  function handleCopy(refCode) {
    if (!refCode) return
    navigator.clipboard.writeText(refCode).then(() => {
      setCopiedCode(refCode)
      setTimeout(() => setCopiedCode(null), 2500)
    }).catch(() => {})
  }

  function formatBotText(content) {
    // Basic Markdown formatting helper for bolding and line breaks
    if (!content) return ''
    const parts = content.split('\n')
    return parts.map((line, idx) => {
      // Replace **text** with <strong>
      const boldRegex = /\*\*(.*?)\*\*/g
      const elements = []
      let lastIndex = 0
      let match

      while ((match = boldRegex.exec(line)) !== null) {
        if (match.index > lastIndex) {
          elements.push(line.substring(lastIndex, match.index))
        }
        elements.push(<strong key={match.index}>{match[1]}</strong>)
        lastIndex = boldRegex.lastIndex
      }
      if (lastIndex < line.length) {
        elements.push(line.substring(lastIndex))
      }

      return (
        <span key={idx} className="block min-h-[1.25rem]">
          {elements.length > 0 ? elements : line}
        </span>
      )
    })
  }

  const isBookingActive = bookingFlow && bookingFlow.step && bookingFlow.step !== 'idle' && bookingFlow.step !== 'completed'

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold">Ask the receptionist</h1>
          <p className="text-sm text-slate-500">
            Ask questions, check working hours, or book an appointment directly through conversation.
          </p>
        </div>
        {isBookingActive && (
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 border border-indigo-200">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex h-2 w-2 rounded-full bg-indigo-600"></span>
              </span>
              Booking In Progress
            </span>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => send('cancel')}
              className="text-xs text-red-600 hover:bg-red-50"
            >
              Cancel flow
            </Button>
          </div>
        )}
      </div>

      <div className="h-[58vh] space-y-3.5 overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 shadow-xs" aria-live="polite">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.from === 'me' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[88%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                m.from === 'me'
                  ? 'bg-indigo-600 text-white shadow-xs'
                  : m.unanswered
                  ? 'border border-amber-200 bg-amber-50 text-amber-950'
                  : 'border border-slate-200/80 bg-slate-50/80 text-slate-900 shadow-2xs'
              }`}
            >
              {m.from === 'me' ? m.text : formatBotText(m.text)}

              {/* Celebration Card for Completed Booking */}
              {m.booking_flow?.step === 'completed' && m.booking_flow.reference_code && (
                <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50/90 p-3.5 text-left text-xs text-emerald-950">
                  <div className="flex items-center justify-between border-b border-emerald-200 pb-2">
                    <div>
                      <span className="block text-[10px] uppercase font-semibold text-emerald-700 tracking-wider">Reference Code</span>
                      <span className="font-mono text-base font-bold text-emerald-900">{m.booking_flow.reference_code}</span>
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => handleCopy(m.booking_flow.reference_code)}
                      className="text-xs border-emerald-300 hover:bg-emerald-100"
                    >
                      {copiedCode === m.booking_flow.reference_code ? '✓ Copied' : '📋 Copy'}
                    </Button>
                  </div>
                  <div className="mt-2 space-y-1">
                    <div className="flex justify-between">
                      <span className="text-emerald-800">Status:</span>
                      <Badge value="pending" />
                    </div>
                    {m.booking_flow.department_name && (
                      <div className="flex justify-between">
                        <span className="text-emerald-800">Department:</span>
                        <span className="font-medium text-emerald-950">{m.booking_flow.department_name}</span>
                      </div>
                    )}
                    {m.booking_flow.staff_name && (
                      <div className="flex justify-between">
                        <span className="text-emerald-800">Person:</span>
                        <span className="font-medium text-emerald-950">{m.booking_flow.staff_name}</span>
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-emerald-200/60 pt-2">
                    {user ? (
                      <Link to="/my-appointments">
                        <Button size="sm" variant="primary">View My Appointments</Button>
                      </Link>
                    ) : (
                      <Link to="/status">
                        <Button size="sm" variant="primary">Check Status Page</Button>
                      </Link>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex justify-start">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400"></span>
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:0.2s]"></span>
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:0.4s]"></span>
              Receptionist is typing…
            </div>
          </div>
        )}
        <div ref={end} />
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      {/* Date Picker Helper if at Date Step */}
      {bookingFlow?.step === 'date' && (
        <div className="flex items-center gap-2 rounded-xl border border-indigo-100 bg-indigo-50/60 p-2.5 text-xs text-indigo-900">
          <span className="font-medium">Or select specific date:</span>
          <Input
            type="date"
            min={todayISO()}
            value={customDate}
            onChange={(e) => setCustomDate(e.target.value)}
            className="w-auto py-1 text-xs"
          />
          <Button
            type="button"
            size="sm"
            disabled={!customDate || busy}
            onClick={() => customDate && send(customDate)}
          >
            Select Date
          </Button>
        </div>
      )}

      {/* Quick Action & Suggestion Pills */}
      <div className="flex flex-wrap items-center gap-2">
        {action === 'book_appointment' && !isBookingActive && (
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={() => send('I want to book an appointment')}
            className="flex items-center gap-1.5"
          >
            📅 Book Appointment in Chat
          </Button>
        )}

        {suggestions.map((s) => {
          const isConfirm = s.toLowerCase() === 'confirm'
          const isCancel = s.toLowerCase() === 'cancel'
          return (
            <button
              key={s}
              type="button"
              disabled={busy}
              onClick={() => send(s)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium transition cursor-pointer disabled:cursor-not-allowed ${
                isConfirm
                  ? 'bg-emerald-600 text-white hover:bg-emerald-700 shadow-xs ring-2 ring-emerald-300'
                  : isCancel
                  ? 'border border-slate-200 bg-slate-100 text-slate-600 hover:bg-slate-200'
                  : 'border border-slate-300 bg-white text-slate-700 hover:border-indigo-400 hover:bg-indigo-50/50 hover:text-indigo-900 shadow-2xs'
              }`}
            >
              {s}
            </button>
          )
        })}
      </div>

      {/* Message input */}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          send(text)
        }}
      >
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={500}
          placeholder={isBookingActive ? 'Type your response or select an option above…' : 'Type your question or request…'}
          aria-label="Your message"
          disabled={busy}
        />
        <Button type="submit" disabled={busy || !text.trim()}>
          Send
        </Button>
      </form>
    </div>
  )
}
