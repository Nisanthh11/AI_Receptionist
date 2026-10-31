import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { Alert, Badge, Button, Card } from '../../components/ui'

// SpeechRecognition cross-browser support
const SpeechRecognition =
  typeof window !== 'undefined'
    ? window.SpeechRecognition || window.webkitSpeechRecognition || null
    : null

export default function VoiceCall() {
  const nav = useNavigate()
  // Call status: 'idle' | 'requesting_permission' | 'in_call' | 'listening' | 'speaking' | 'processing' | 'ended'
  const [callState, setCallState] = useState('idle')
  const [token, setToken] = useState(() => sessionStorage.getItem('receptionist_voice_token') || null)
  const [transcriptHistory, setTranscriptHistory] = useState([])
  const [currentSpeech, setCurrentSpeech] = useState('')
  const [agentSpeakingText, setAgentSpeakingText] = useState('')
  const [bookingFlow, setBookingFlow] = useState(null)
  const [suggestions, setSuggestions] = useState([])
  const [isMuted, setIsMuted] = useState(false)
  const [errorMessageText, setErrorMessageText] = useState('')
  const [permissionDenied, setPermissionDenied] = useState(false)
  const [transferredToHuman, setTransferredToHuman] = useState(false)
  const [availableVoices, setAvailableVoices] = useState([])
  const [callDuration, setCallDuration] = useState(0)

  const recognitionRef = useRef(null)
  const isListeningRef = useRef(false)
  const isSpeakingRef = useRef(false)
  const silenceTimerRef = useRef(null)
  const callTimerRef = useRef(null)
  const transcriptEndRef = useRef(null)
  const streamRef = useRef(null)
  const isMountedRef = useRef(true)

  // Scroll transcript to bottom on new message
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcriptHistory, currentSpeech, agentSpeakingText])

  // Call timer
  useEffect(() => {
    if (callState !== 'idle' && callState !== 'ended') {
      callTimerRef.current = setInterval(() => {
        setCallDuration((d) => d + 1)
      }, 1000)
    } else {
      clearInterval(callTimerRef.current)
    }
    return () => clearInterval(callTimerRef.current)
  }, [callState])

  // Load available speech synthesis voices
  useEffect(() => {
    isMountedRef.current = true
    if ('speechSynthesis' in window) {
      const loadVoices = () => {
        const voices = window.speechSynthesis.getVoices()
        if (voices.length > 0) setAvailableVoices(voices)
      }
      loadVoices()
      window.speechSynthesis.onvoiceschanged = loadVoices
    }
    return () => {
      isMountedRef.current = false
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel()
      }
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop()
        } catch {}
      }
    }
  }, [])

  function formatDuration(sec) {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  // Speak text using Web SpeechSynthesis API
  function speak(text, onComplete) {
    if (!('speechSynthesis' in window)) {
      if (onComplete) onComplete()
      return
    }

    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.rate = 1.0
    utterance.pitch = 1.0

    // Select natural, preferred English voice
    if (availableVoices.length > 0) {
      const preferred = availableVoices.find(
        (v) =>
          (v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Samantha') || v.name.includes('Jenny'))) ||
          v.lang.startsWith('en')
      )
      if (preferred) utterance.voice = preferred
    }

    setCallState('speaking')
    isSpeakingRef.current = true
    setAgentSpeakingText(text)

    utterance.onend = () => {
      isSpeakingRef.current = false
      setAgentSpeakingText('')
      if (isMountedRef.current) {
        if (onComplete) onComplete()
      }
    }

    utterance.onerror = () => {
      isSpeakingRef.current = false
      setAgentSpeakingText('')
      if (isMountedRef.current && onComplete) onComplete()
    }

    window.speechSynthesis.speak(utterance)
  }

  // Initialize and start Speech Recognition
  function startListening(activeToken) {
    if (!SpeechRecognition) return
    if (isSpeakingRef.current || isMuted) return

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {}
    }

    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'

    let finalTranscript = ''

    recognition.onstart = () => {
      isListeningRef.current = true
      setCallState('listening')
      setErrorMessageText('')
    }

    recognition.onresult = (event) => {
      let interim = ''
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript + ' '
        } else {
          interim += event.results[i][0].transcript
        }
      }

      const spokenSoFar = (finalTranscript + interim).trim()
      setCurrentSpeech(spokenSoFar)

      // Reset silence debounce timer: send turn when caller pauses for 1.8 seconds
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      if (spokenSoFar.length > 1) {
        silenceTimerRef.current = setTimeout(() => {
          if (spokenSoFar.trim().length > 0) {
            try {
              recognition.stop()
            } catch {}
            sendVoiceTurn(spokenSoFar.trim(), activeToken)
          }
        }, 1800)
      }
    }

    recognition.onerror = (e) => {
      if (e.error === 'not-allowed') {
        setPermissionDenied(true)
        setCallState('ended')
        setErrorMessageText('Microphone access was blocked. Please enable microphone permissions in your browser address bar.')
      } else if (e.error !== 'no-speech') {
        logger_warn('Speech recognition warning:', e.error)
      }
    }

    recognition.onend = () => {
      isListeningRef.current = false
      // If caller ended turn or recognition stopped without error, process final speech
      if (finalTranscript.trim().length > 0 && !isSpeakingRef.current) {
        sendVoiceTurn(finalTranscript.trim(), activeToken)
      } else if (callState === 'listening' && !isSpeakingRef.current && !isMuted) {
        // Auto-restart recognition if still in listening state
        try {
          recognition.start()
        } catch {}
      }
    }

    recognitionRef.current = recognition
    try {
      recognition.start()
    } catch {}
  }

  function logger_warn(msg, detail) {
    console.warn(msg, detail)
  }

  // Start Call action
  async function handleStartCall() {
    setErrorMessageText('')
    setPermissionDenied(false)
    setTransferredToHuman(false)
    setCallDuration(0)
    setCallState('requesting_permission')

    // 1. Request microphone permission
    try {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        streamRef.current = stream
      }
    } catch (err) {
      setPermissionDenied(true)
      setCallState('idle')
      setErrorMessageText('Microphone permission is required to speak with the AI Receptionist. Please allow microphone access or switch to text chat.')
      return
    }

    // 2. Initialize voice session on backend
    try {
      const { data } = await api.post('/api/voice/session', {
        session_token: token,
        channel: 'browser_voice',
      })
      setToken(data.session_token)
      sessionStorage.setItem('receptionist_voice_token', data.session_token)
      setSuggestions(data.suggestions || [])

      // Record receptionist greeting turn
      const greetingTurn = {
        sender: 'agent',
        text: data.display_text,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setTranscriptHistory([greetingTurn])

      // Speak greeting, then listen
      speak(data.speech_text, () => {
        if (isMountedRef.current) {
          startListening(data.session_token)
        }
      })
    } catch (err) {
      setCallState('idle')
      setErrorMessageText(errorMessage(err))
    }
  }

  // Send turn transcript to backend
  async function sendVoiceTurn(userText, activeToken) {
    if (!userText || !activeToken) return
    setCurrentSpeech('')

    // Append caller turn to transcript
    const userTurn = {
      sender: 'user',
      text: userText,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }
    setTranscriptHistory((prev) => [...prev, userTurn])
    setCallState('processing')

    try {
      const { data } = await api.post('/api/voice/turn', {
        session_token: activeToken,
        transcript: userText,
        channel: 'browser_voice',
      })

      setToken(data.session_token)
      sessionStorage.setItem('receptionist_voice_token', data.session_token)
      setBookingFlow(data.booking_flow || null)
      setSuggestions(data.suggestions || [])

      if (data.transfer_to_human) {
        setTransferredToHuman(true)
      }

      // Append agent reply turn to transcript
      const agentTurn = {
        sender: 'agent',
        text: data.reply_text,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        booking_flow: data.booking_flow,
      }
      setTranscriptHistory((prev) => [...prev, agentTurn])

      // Speak the response
      speak(data.speech_text, () => {
        if (!isMountedRef.current) return
        if (data.is_final || data.transfer_to_human) {
          setCallState('ended')
        } else {
          startListening(data.session_token)
        }
      })
    } catch (err) {
      setCallState('listening')
      setErrorMessageText(errorMessage(err))
      speak("I didn't quite catch that. Could you please repeat that?", () => {
        if (isMountedRef.current) startListening(activeToken)
      })
    }
  }

  // End Call action
  function handleEndCall() {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {}
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
    }
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
    clearInterval(callTimerRef.current)

    setCallState('ended')
    setAgentSpeakingText('')
    setCurrentSpeech('')

    if (token) {
      api.post('/api/voice/end', { session_token: token }).catch(() => {})
    }
  }

  // Toggle Mute
  function handleToggleMute() {
    if (isMuted) {
      setIsMuted(false)
      if (callState === 'listening' || callState === 'in_call') {
        startListening(token)
      }
    } else {
      setIsMuted(true)
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop()
        } catch {}
      }
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Top Banner / Call Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-slate-900">Call AI Receptionist</h1>
            <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 border border-indigo-200">
              Live Voice
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            Talk naturally with our virtual receptionist to book appointments, ask about departments, and get answers.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link to="/chat">
            <Button variant="secondary" size="sm">
              💬 Switch to Text Chat
            </Button>
          </Link>
          <Link to="/book">
            <Button variant="secondary" size="sm">
              📅 Direct Booking
            </Button>
          </Link>
        </div>
      </div>

      {/* Browser Speech Compatibility Notice */}
      {!SpeechRecognition && (
        <Alert kind="info">
          <b>Voice Input Notice:</b> Your browser does not natively support continuous speech recognition. For full spoken two-way voice conversations, we recommend <b>Google Chrome</b>, <b>Microsoft Edge</b>, or <b>Safari</b>. You can also use our{' '}
          <Link to="/chat" className="underline font-semibold text-indigo-700">
            interactive text receptionist
          </Link>.
        </Alert>
      )}

      {/* Permission Denied Alert */}
      {permissionDenied && (
        <Alert kind="error">
          <b>Microphone Permission Denied:</b> We need microphone access so the virtual receptionist can hear you. Please click the camera/mic icon in your browser address bar, grant access, and try again.
        </Alert>
      )}

      {/* Generic Error */}
      <Alert kind="error">{errorMessageText}</Alert>

      {/* Main Call Center Card */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left Column: Visual Call Status & Controls */}
        <div className="lg:col-span-1 space-y-4">
          <Card className="flex flex-col items-center justify-center p-6 text-center">
            {/* Visual Call State Ring / Avatar */}
            <div className="relative my-4 flex h-32 w-32 items-center justify-center">
              {/* Outer pulsing ring when speaking or listening */}
              {callState === 'speaking' && (
                <div className="absolute inset-0 rounded-full bg-indigo-400 opacity-40 animate-ping" />
              )}
              {callState === 'listening' && (
                <div className="absolute inset-0 rounded-full bg-emerald-400 opacity-40 animate-pulse" />
              )}
              {callState === 'processing' && (
                <div className="absolute inset-0 rounded-full bg-amber-400 opacity-40 animate-spin" />
              )}

              {/* Main Avatar Circle */}
              <div
                className={`relative flex h-24 w-24 items-center justify-center rounded-full text-4xl shadow-md transition-all duration-300 ${
                  callState === 'speaking'
                    ? 'bg-gradient-to-tr from-indigo-600 to-indigo-700 text-white shadow-indigo-200'
                    : callState === 'listening'
                    ? 'bg-gradient-to-tr from-emerald-500 to-emerald-600 text-white shadow-emerald-200 scale-105'
                    : callState === 'processing'
                    ? 'bg-amber-500 text-white'
                    : callState === 'ended'
                    ? 'bg-slate-200 text-slate-500'
                    : 'bg-indigo-50 text-indigo-700 border-2 border-indigo-200'
                }`}
              >
                {callState === 'speaking' ? '🗣️' : callState === 'listening' ? '🎙️' : callState === 'processing' ? '⏳' : '🛎️'}
              </div>
            </div>

            {/* Call State Title */}
            <div className="mt-2">
              <h3 className="font-bold text-slate-900 text-lg">
                {callState === 'idle' && 'Ready to Connect'}
                {callState === 'requesting_permission' && 'Accessing Microphone…'}
                {callState === 'speaking' && 'Receptionist is Speaking…'}
                {callState === 'listening' && 'Listening to you…'}
                {callState === 'processing' && 'Thinking & checking slots…'}
                {callState === 'ended' && 'Call Disconnected'}
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                {callState === 'idle' && 'Click Start Call to begin speaking'}
                {callState === 'speaking' && 'Listen or speak to respond'}
                {callState === 'listening' && (isMuted ? 'Microphone is muted' : 'Speak into your microphone')}
                {callState === 'processing' && 'Validating your details'}
                {callState === 'ended' && 'Thank you for calling'}
              </p>
            </div>

            {/* Call Duration Badge */}
            {callState !== 'idle' && (
              <div className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 font-mono text-xs font-semibold text-slate-700">
                <span className={`h-2 w-2 rounded-full ${callState === 'ended' ? 'bg-slate-400' : 'bg-rose-500 animate-pulse'}`} />
                <span>{formatDuration(callDuration)}</span>
              </div>
            )}

            {/* Main Action Buttons */}
            <div className="mt-6 flex flex-col w-full gap-2.5">
              {callState === 'idle' || callState === 'ended' ? (
                <Button
                  variant="primary"
                  className="w-full py-3 text-base font-semibold shadow-md flex items-center justify-center gap-2"
                  onClick={handleStartCall}
                  disabled={!SpeechRecognition}
                >
                  <span>📞</span> Start Voice Call
                </Button>
              ) : (
                <div className="flex items-center gap-2 w-full">
                  <Button
                    variant={isMuted ? 'danger' : 'secondary'}
                    className="flex-1 py-2.5 text-sm font-semibold flex items-center justify-center gap-1.5"
                    onClick={handleToggleMute}
                  >
                    {isMuted ? '🔇 Unmute' : '🎙️ Mute'}
                  </Button>
                  <Button
                    variant="danger"
                    className="flex-1 py-2.5 text-sm font-semibold flex items-center justify-center gap-1.5 shadow-sm"
                    onClick={handleEndCall}
                  >
                    🔴 End Call
                  </Button>
                </div>
              )}
            </div>

            {/* Live Audio Level indicator note */}
            <div className="mt-4 pt-4 border-t border-slate-100 w-full text-left text-xs text-slate-400 space-y-1">
              <p>🔒 <b>Private & Local:</b> Audio is processed directly in your browser without recordings.</p>
              <p>🗣️ <b>Natural Turn-Taking:</b> Speak your department, date, and time preferences naturally.</p>
            </div>
          </Card>

          {/* Active Booking Flow Progress Widget */}
          {bookingFlow && bookingFlow.step !== 'idle' && (
            <Card className="p-4 border-indigo-100 bg-indigo-50/40">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-900">
                  Appointment Details
                </h4>
                <Badge value={bookingFlow.step === 'completed' ? 'confirmed' : 'pending'} />
              </div>

              <div className="space-y-1.5 text-xs text-slate-700">
                {bookingFlow.department_name && (
                  <p>
                    <span className="font-semibold text-slate-500">Department:</span> {bookingFlow.department_name}
                  </p>
                )}
                {bookingFlow.staff_name && (
                  <p>
                    <span className="font-semibold text-slate-500">Staff:</span> {bookingFlow.staff_name}
                  </p>
                )}
                {bookingFlow.date_str && (
                  <p>
                    <span className="font-semibold text-slate-500">Date:</span> {bookingFlow.date_str}
                  </p>
                )}
                {bookingFlow.slot_start && (
                  <p>
                    <span className="font-semibold text-slate-500">Time:</span>{' '}
                    {new Date(bookingFlow.slot_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </p>
                )}
                {bookingFlow.full_name && (
                  <p>
                    <span className="font-semibold text-slate-500">Visitor:</span> {bookingFlow.full_name}
                  </p>
                )}
                {bookingFlow.reference_code && (
                  <div className="mt-2 rounded bg-white p-2 border border-indigo-200">
                    <span className="block text-[10px] text-slate-400 uppercase font-bold">Reference Code</span>
                    <span className="font-mono text-sm font-bold text-indigo-700">{bookingFlow.reference_code}</span>
                  </div>
                )}
              </div>
            </Card>
          )}

          {/* Human Escalation Notice */}
          {transferredToHuman && (
            <Alert kind="info">
              <b>Transferred to Front Desk Staff:</b> An on-site receptionist has been notified. You can also reach our desk directly at <b>+910000000000</b>.
            </Alert>
          )}
        </div>

        {/* Right Column: Live Conversation Transcript */}
        <div className="lg:col-span-2 flex flex-col h-[600px]">
          <Card className="flex flex-col flex-1 p-0 overflow-hidden shadow-sm">
            {/* Transcript Header */}
            <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="text-base" aria-hidden>📜</span>
                <span className="font-semibold text-sm text-slate-800">Live Call Transcript</span>
              </div>
              <span className="text-xs text-slate-500 font-medium">
                {transcriptHistory.length} turns recorded
              </span>
            </div>

            {/* Transcript Messages Scroll Area */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3.5 bg-white">
              {transcriptHistory.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 py-12">
                  <span className="text-4xl mb-2">🎙️</span>
                  <p className="font-medium">No conversation yet</p>
                  <p className="text-xs max-w-xs mt-1">
                    Click "Start Voice Call" on the left to begin your spoken session with our virtual receptionist.
                  </p>
                </div>
              ) : (
                transcriptHistory.map((turn, i) => (
                  <div
                    key={i}
                    className={`flex gap-3 text-sm ${turn.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    {turn.sender === 'agent' && (
                      <div className="h-8 w-8 rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center shrink-0 text-sm">
                        🛎️
                      </div>
                    )}

                    <div
                      className={`max-w-[80%] rounded-2xl px-4 py-2.5 leading-relaxed shadow-xs ${
                        turn.sender === 'user'
                          ? 'bg-indigo-600 text-white rounded-br-xs'
                          : 'bg-slate-100 text-slate-800 rounded-bl-xs border border-slate-200'
                      }`}
                    >
                      <div className="whitespace-pre-line text-xs md:text-sm font-normal">
                        {turn.text}
                      </div>
                      <div
                        className={`text-[10px] mt-1 text-right ${
                          turn.sender === 'user' ? 'text-indigo-200' : 'text-slate-400'
                        }`}
                      >
                        {turn.time}
                      </div>
                    </div>

                    {turn.sender === 'user' && (
                      <div className="h-8 w-8 rounded-full bg-indigo-600 text-white flex items-center justify-center shrink-0 text-xs font-bold">
                        You
                      </div>
                    )}
                  </div>
                ))
              )}

              {/* Interim Live Speech from User */}
              {currentSpeech && (
                <div className="flex gap-3 justify-end text-sm animate-pulse">
                  <div className="max-w-[80%] rounded-2xl px-4 py-2 bg-indigo-100 border border-indigo-200 text-indigo-900 italic text-xs">
                    "{currentSpeech}…"
                  </div>
                  <div className="h-8 w-8 rounded-full bg-indigo-400 text-white flex items-center justify-center shrink-0 text-xs font-bold">
                    You
                  </div>
                </div>
              )}

              {/* Live Receptionist Speaking Indicator */}
              {agentSpeakingText && callState === 'speaking' && (
                <div className="flex gap-3 justify-start text-sm">
                  <div className="h-8 w-8 rounded-full bg-indigo-100 border border-indigo-200 flex items-center justify-center shrink-0 text-sm animate-bounce">
                    🗣️
                  </div>
                  <div className="max-w-[80%] rounded-2xl px-4 py-2 bg-slate-50 border border-slate-200 text-slate-600 text-xs italic flex items-center gap-2">
                    <span className="inline-block h-2 w-2 rounded-full bg-indigo-600 animate-ping" />
                    <span>Speaking response…</span>
                  </div>
                </div>
              )}

              <div ref={transcriptEndRef} />
            </div>

            {/* Quick Suggestions Chips Footer */}
            {suggestions.length > 0 && callState !== 'ended' && (
              <div className="border-t border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
                  <span className="text-[11px] font-semibold text-slate-500 uppercase shrink-0">
                    Spoken Suggestions:
                  </span>
                  {suggestions.map((s, idx) => (
                    <button
                      key={idx}
                      type="button"
                      className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-700 border border-slate-200 hover:border-indigo-400 hover:text-indigo-600 transition shrink-0 shadow-2xs"
                      onClick={() => {
                        if (token) sendVoiceTurn(s, token)
                      }}
                    >
                      "{s}"
                    </button>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
