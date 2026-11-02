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
  const [manualInput, setManualInput] = useState('')
  const [agentSpeakingText, setAgentSpeakingText] = useState('')
  const [bookingFlow, setBookingFlow] = useState(null)
  const [suggestions, setSuggestions] = useState([])
  const [isMuted, setIsMuted] = useState(false)
  const [errorMessageText, setErrorMessageText] = useState('')
  const [permissionDenied, setPermissionDenied] = useState(false)
  const [transferredToHuman, setTransferredToHuman] = useState(false)
  const [availableVoices, setAvailableVoices] = useState([])
  const [callDuration, setCallDuration] = useState(0)
  const [micVolume, setMicVolume] = useState(0)

  // Language selection (defaulting to en-IN with fallback)
  const [selectedLang, setSelectedLang] = useState(() => {
    if (typeof navigator !== 'undefined' && navigator.language) {
      if (navigator.language.startsWith('en-IN')) return 'en-IN'
      if (navigator.language.startsWith('en')) return navigator.language
    }
    return 'en-IN'
  })

  // Mutable refs to prevent stale closure bugs in async callbacks & SpeechRecognition handlers
  const callStateRef = useRef('idle')
  const tokenRef = useRef(token)
  const isMutedRef = useRef(false)
  const isSpeakingRef = useRef(false)
  const isListeningRef = useRef(false)
  const turnInFlightRef = useRef(false)
  const selectedLangRef = useRef('en-IN')

  const recognitionRef = useRef(null)
  const silenceTimerRef = useRef(null)
  const callTimerRef = useRef(null)
  const transcriptEndRef = useRef(null)
  const streamRef = useRef(null)
  const audioContextRef = useRef(null)
  const analyserRef = useRef(null)
  const animFrameRef = useRef(null)
  const isMountedRef = useRef(true)

  // Keep refs in sync with React state
  useEffect(() => {
    callStateRef.current = callState
  }, [callState])

  useEffect(() => {
    tokenRef.current = token
  }, [token])

  useEffect(() => {
    isMutedRef.current = isMuted
  }, [isMuted])

  useEffect(() => {
    selectedLangRef.current = selectedLang
  }, [selectedLang])

  // Scroll transcript to bottom on new message
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcriptHistory, currentSpeech, agentSpeakingText])

  // Call duration timer
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

  // Setup Web Audio API analyser to measure live mic volume
  function setupAudioMeter(stream) {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext
      if (!AudioCtx) return

      if (audioContextRef.current) {
        try {
          audioContextRef.current.close()
        } catch {}
      }

      const ctx = new AudioCtx()
      if (ctx.state === 'suspended') {
        ctx.resume()
      }

      const analyser = ctx.createAnalyser()
      analyser.fftSize = 128
      analyser.smoothingTimeConstant = 0.3

      const source = ctx.createMediaStreamSource(stream)
      source.connect(analyser)

      audioContextRef.current = ctx
      analyserRef.current = analyser

      const dataArray = new Uint8Array(analyser.frequencyBinCount)
      const updateVolume = () => {
        if (!isMountedRef.current || callStateRef.current === 'ended' || callStateRef.current === 'idle') {
          setMicVolume(0)
          return
        }
        analyser.getByteFrequencyData(dataArray)
        let sum = 0
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i]
        }
        const avg = sum / dataArray.length
        // Map average magnitude (0-128) to percentage (0-100)
        const vol = Math.min(100, Math.round((avg / 60) * 100))
        setMicVolume(vol)
        animFrameRef.current = requestAnimationFrame(updateVolume)
      }
      updateVolume()
    } catch (err) {
      console.warn('AudioContext volume meter setup error:', err)
    }
  }

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
          recognitionRef.current.onend = null
          recognitionRef.current.onerror = null
          recognitionRef.current.stop()
        } catch {}
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop())
      }
      if (audioContextRef.current) {
        try {
          audioContextRef.current.close()
        } catch {}
      }
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current)
      }
    }
  }, [])

  function formatDuration(sec) {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  // Speak text using Web SpeechSynthesis API with watchdog safety
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
          (v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Samantha') || v.name.includes('Jenny') || v.name.includes('Ravi') || v.name.includes('India'))) ||
          v.lang.startsWith('en')
      )
      if (preferred) utterance.voice = preferred
    }

    setCallState('speaking')
    callStateRef.current = 'speaking'
    isSpeakingRef.current = true
    setAgentSpeakingText(text)

    let completed = false
    const finish = () => {
      if (completed) return
      completed = true
      clearTimeout(watchdogTimer)
      isSpeakingRef.current = false
      setAgentSpeakingText('')
      if (isMountedRef.current && onComplete) onComplete()
    }

    // Safety watchdog: Chrome speech synthesis can occasionally stall on long utterances
    const wordCount = (text || '').split(' ').length
    const estimatedDurationMs = Math.max(3000, Math.ceil((wordCount / 2.5) * 1000) + 2000)
    const watchdogTimer = setTimeout(finish, estimatedDurationMs)

    utterance.onend = finish
    utterance.onerror = finish

    try {
      window.speechSynthesis.speak(utterance)
    } catch {
      finish()
    }
  }

  // Initialize and start Speech Recognition with continuous auto-restart
  function startListening(activeToken) {
    const currentToken = activeToken || tokenRef.current
    if (!SpeechRecognition) return
    if (isSpeakingRef.current || isMutedRef.current) return

    if (recognitionRef.current) {
      try {
        recognitionRef.current.onend = null
        recognitionRef.current.onerror = null
        recognitionRef.current.onresult = null
        recognitionRef.current.stop()
      } catch {}
      recognitionRef.current = null
    }

    turnInFlightRef.current = false
    let finalTranscript = ''

    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = selectedLangRef.current || 'en-IN'

    recognition.onstart = () => {
      isListeningRef.current = true
      setCallState('listening')
      callStateRef.current = 'listening'
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

      // Debounce: send turn when speaker pauses for 1.6 seconds after speaking
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      if (spokenSoFar.length > 1) {
        silenceTimerRef.current = setTimeout(() => {
          if (spokenSoFar.trim().length > 0 && !turnInFlightRef.current) {
            turnInFlightRef.current = true
            try {
              recognition.stop()
            } catch {}
            sendVoiceTurn(spokenSoFar.trim(), currentToken)
          }
        }, 1600)
      }
    }

    recognition.onerror = (e) => {
      if (e.error === 'not-allowed') {
        setPermissionDenied(true)
        setCallState('ended')
        callStateRef.current = 'ended'
        setErrorMessageText('Microphone access was blocked. Please enable microphone permissions in your browser address bar.')
      } else if (e.error === 'audio-capture') {
        setErrorMessageText('No microphone detected. Please verify your microphone is plugged in, permitted, and active.')
      } else if (e.error === 'network') {
        setErrorMessageText('Browser speech recognition encountered a network issue contacting the speech service. You can speak again, tap a suggestion, or type below.')
      } else if (e.error !== 'no-speech') {
        console.warn('Speech recognition warning:', e.error)
      }
    }

    recognition.onend = () => {
      isListeningRef.current = false
      // If caller ended turn or recognition stopped without error, process final speech
      if (finalTranscript.trim().length > 0 && !turnInFlightRef.current && !isSpeakingRef.current) {
        turnInFlightRef.current = true
        sendVoiceTurn(finalTranscript.trim(), currentToken)
      } else if (callStateRef.current === 'listening' && !isSpeakingRef.current && !isMutedRef.current) {
        // Auto-restart recognition continuously so the mic never goes dead during pauses
        try {
          recognition.start()
        } catch {
          setTimeout(() => {
            if (callStateRef.current === 'listening' && !isSpeakingRef.current && !isMutedRef.current) {
              try {
                recognition.start()
              } catch {}
            }
          }, 200)
        }
      }
    }

    recognitionRef.current = recognition
    try {
      recognition.start()
    } catch (err) {
      console.warn('SpeechRecognition start failed:', err)
    }
  }

  // Start Call action
  async function handleStartCall() {
    setErrorMessageText('')
    setPermissionDenied(false)
    setTransferredToHuman(false)
    setCallDuration(0)
    setCallState('requesting_permission')
    callStateRef.current = 'requesting_permission'

    // 1. Request microphone permission & start volume meter
    try {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        streamRef.current = stream
        setupAudioMeter(stream)
      }
    } catch (err) {
      setPermissionDenied(true)
      setCallState('idle')
      callStateRef.current = 'idle'
      setErrorMessageText('Microphone permission is required to speak with the AI Receptionist. Please allow microphone access or switch to text chat.')
      return
    }

    // 2. Initialize voice session on backend
    try {
      const { data } = await api.post('/api/voice/session', {
        session_token: tokenRef.current,
        channel: 'browser_voice',
      })
      setToken(data.session_token)
      tokenRef.current = data.session_token
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
      callStateRef.current = 'idle'
      setErrorMessageText(errorMessage(err))
    }
  }

  // Send turn transcript to backend
  async function sendVoiceTurn(userText, activeToken) {
    const currentToken = activeToken || tokenRef.current
    if (!userText || !currentToken) return
    setCurrentSpeech('')
    turnInFlightRef.current = true

    // Stop recognition while processing to avoid hearing itself
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {}
    }

    // Append caller turn to transcript
    const userTurn = {
      sender: 'user',
      text: userText,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }
    setTranscriptHistory((prev) => [...prev, userTurn])
    setCallState('processing')
    callStateRef.current = 'processing'

    try {
      const { data } = await api.post('/api/voice/turn', {
        session_token: currentToken,
        transcript: userText,
        channel: 'browser_voice',
      })

      setToken(data.session_token)
      tokenRef.current = data.session_token
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
          callStateRef.current = 'ended'
        } else {
          startListening(data.session_token)
        }
      })
    } catch (err) {
      setCallState('listening')
      callStateRef.current = 'listening'
      setErrorMessageText(errorMessage(err))
      speak("I didn't quite catch that. Could you please repeat that?", () => {
        if (isMountedRef.current) startListening(currentToken)
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
        recognitionRef.current.onend = null
        recognitionRef.current.onerror = null
        recognitionRef.current.onresult = null
        recognitionRef.current.stop()
      } catch {}
      recognitionRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current)
      animFrameRef.current = null
    }
    if (audioContextRef.current) {
      try {
        audioContextRef.current.close()
      } catch {}
      audioContextRef.current = null
    }
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
    clearInterval(callTimerRef.current)

    setCallState('ended')
    callStateRef.current = 'ended'
    setAgentSpeakingText('')
    setCurrentSpeech('')
    setMicVolume(0)

    const curToken = tokenRef.current
    if (curToken) {
      api.post('/api/voice/end', { session_token: curToken }).catch(() => {})
    }
  }

  // Toggle Mute
  function handleToggleMute() {
    if (isMuted) {
      setIsMuted(false)
      isMutedRef.current = false
      if (callStateRef.current === 'listening' || callStateRef.current === 'in_call') {
        startListening(tokenRef.current)
      }
    } else {
      setIsMuted(true)
      isMutedRef.current = true
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop()
        } catch {}
      }
    }
  }

  // Manual restart speech listening
  function handleManualRestartListening() {
    if (callStateRef.current === 'listening' || callStateRef.current === 'speaking') {
      if ('speechSynthesis' in window) window.speechSynthesis.cancel()
      isSpeakingRef.current = false
      setAgentSpeakingText('')
      startListening(tokenRef.current)
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

        <div className="flex flex-wrap items-center gap-2">
          {/* Language / Accent Selector */}
          <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1">
            <span className="text-[11px] font-semibold text-slate-500 uppercase">Lang:</span>
            <select
              value={selectedLang}
              onChange={(e) => {
                const newLang = e.target.value
                setSelectedLang(newLang)
                selectedLangRef.current = newLang
                if (callStateRef.current === 'listening') {
                  startListening(tokenRef.current)
                }
              }}
              className="bg-transparent text-xs text-slate-700 font-medium focus:outline-none cursor-pointer"
            >
              <option value="en-IN">English (India - en-IN)</option>
              <option value="en-US">English (US - en-US)</option>
              <option value="en-GB">English (UK - en-GB)</option>
            </select>
          </div>

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
              <button
                type="button"
                onClick={callState === 'listening' ? handleManualRestartListening : undefined}
                title={callState === 'listening' ? 'Click to re-activate microphone' : undefined}
                className={`relative flex h-24 w-24 items-center justify-center rounded-full text-4xl shadow-md transition-all duration-300 ${
                  callState === 'speaking'
                    ? 'bg-gradient-to-tr from-indigo-600 to-indigo-700 text-white shadow-indigo-200'
                    : callState === 'listening'
                    ? 'bg-gradient-to-tr from-emerald-500 to-emerald-600 text-white shadow-emerald-200 scale-105 cursor-pointer'
                    : callState === 'processing'
                    ? 'bg-amber-500 text-white'
                    : callState === 'ended'
                    ? 'bg-slate-200 text-slate-500'
                    : 'bg-indigo-50 text-indigo-700 border-2 border-indigo-200'
                }`}
              >
                {callState === 'speaking' ? '🗣️' : callState === 'listening' ? '🎙️' : callState === 'processing' ? '⏳' : '🛎️'}
              </button>
            </div>

            {/* Call State Title */}
            <div className="mt-2 w-full">
              <h3 className="font-bold text-slate-900 text-lg">
                {callState === 'idle' && 'Ready to Connect'}
                {callState === 'requesting_permission' && 'Accessing Microphone…'}
                {callState === 'speaking' && 'Receptionist is Speaking…'}
                {callState === 'listening' && 'Listening to you…'}
                {callState === 'processing' && 'Thinking & checking slots…'}
                {callState === 'ended' && 'Call Disconnected'}
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                {callState === 'idle' && 'Click Start Voice Call to begin'}
                {callState === 'speaking' && 'Listen or speak to respond'}
                {callState === 'listening' && (isMuted ? 'Microphone is muted' : 'Speak into your microphone')}
                {callState === 'processing' && 'Validating your details'}
                {callState === 'ended' && 'Thank you for calling'}
              </p>
            </div>

            {/* Real-Time Microphone Volume Level Meter */}
            {(callState === 'listening' || callState === 'speaking' || callState === 'processing') && (
              <div className="w-full mt-3 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-left">
                <div className="flex items-center justify-between text-xs font-medium text-slate-600 mb-1">
                  <span className="flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${micVolume > 6 ? 'bg-emerald-500 animate-ping' : 'bg-slate-400'}`} />
                    <span>Mic Level: {micVolume}%</span>
                  </span>
                  <span className="text-[11px] text-slate-400">
                    {micVolume > 6 ? '🎙️ Sound detected' : isMuted ? 'Muted' : 'Quiet / Silence'}
                  </span>
                </div>
                <div className="w-full bg-slate-200 rounded-full h-2 overflow-hidden">
                  <div
                    className={`h-2 transition-all duration-75 rounded-full ${
                      micVolume > 6 ? 'bg-gradient-to-r from-emerald-500 to-indigo-600' : 'bg-slate-300'
                    }`}
                    style={{ width: `${Math.max(micVolume, 4)}%` }}
                  />
                </div>
                {micVolume === 0 && callState === 'listening' && !isMuted && (
                  <p className="text-[10px] text-amber-600 mt-1">
                    Tip: If meter stays 0% while speaking, check system/browser microphone input.
                  </p>
                )}
              </div>
            )}

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
                <div className="flex flex-col gap-2 w-full">
                  <div className="flex items-center gap-2 w-full">
                    <Button
                      variant={isMuted ? 'danger' : 'secondary'}
                      className="flex-1 py-2 text-xs md:text-sm font-semibold flex items-center justify-center gap-1.5"
                      onClick={handleToggleMute}
                    >
                      {isMuted ? '🔇 Unmute' : '🎙️ Mute'}
                    </Button>
                    <Button
                      variant="danger"
                      className="flex-1 py-2 text-xs md:text-sm font-semibold flex items-center justify-center gap-1.5 shadow-sm"
                      onClick={handleEndCall}
                    >
                      🔴 End Call
                    </Button>
                  </div>

                  {callState === 'listening' && (
                    <button
                      type="button"
                      onClick={handleManualRestartListening}
                      className="text-[11px] text-indigo-600 hover:text-indigo-800 underline font-medium text-center"
                    >
                      🔄 Tap to restart microphone if paused
                    </button>
                  )}
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
                <div className="flex flex-col gap-1 items-end animate-pulse">
                  <div className="flex gap-3 justify-end text-sm">
                    <div className="max-w-[80%] rounded-2xl px-4 py-2 bg-indigo-100 border border-indigo-200 text-indigo-900 italic text-xs">
                      "{currentSpeech}…"
                    </div>
                    <div className="h-8 w-8 rounded-full bg-indigo-400 text-white flex items-center justify-center shrink-0 text-xs font-bold">
                      You
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="primary"
                    className="mr-11 text-xs py-1 px-2.5 shadow-2xs"
                    onClick={() => {
                      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
                      turnInFlightRef.current = true
                      if (recognitionRef.current) {
                        try {
                          recognitionRef.current.stop()
                        } catch {}
                      }
                      sendVoiceTurn(currentSpeech, tokenRef.current)
                    }}
                  >
                    Send Now ➔
                  </Button>
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
                        const curToken = tokenRef.current
                        if (curToken) sendVoiceTurn(s, curToken)
                      }}
                    >
                      "{s}"
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Inline Fallback Input for Noisy Environments or Low Mic Input */}
            {callState !== 'idle' && callState !== 'ended' && (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!manualInput.trim()) return
                  const text = manualInput.trim()
                  setManualInput('')
                  sendVoiceTurn(text, tokenRef.current)
                }}
                className="border-t border-slate-200 bg-white p-2.5 flex items-center gap-2"
              >
                <input
                  type="text"
                  value={manualInput}
                  onChange={(e) => setManualInput(e.target.value)}
                  placeholder="Or type here if mic is quiet (e.g., 'Book with Admissions tomorrow')..."
                  className="flex-1 text-xs rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
                <Button type="submit" size="sm" variant="secondary" disabled={!manualInput.trim()}>
                  Send
                </Button>
              </form>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
