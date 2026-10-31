import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { errorMessage } from '../../api/client'
import { Alert, Button, Card, Field, Input } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

export default function Login() {
  const { user, login, register } = useAuth()
  const nav = useNavigate()
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) {
    return <Navigate to={user.role === 'user' ? '/my-appointments' : '/admin'} replace />
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (mode === 'register') {
        const data = await register(email, password, fullName)
        nav(data.role === 'user' ? '/my-appointments' : '/admin')
      } else {
        const data = await login(email, password)
        nav(data.role === 'user' ? '/my-appointments' : '/admin')
      }
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <div className="flex border-b border-slate-200 mb-4">
          <button
            type="button"
            className={`flex-1 pb-2 text-center text-sm font-semibold transition ${
              mode === 'login'
                ? 'border-b-2 border-indigo-600 text-indigo-700'
                : 'text-slate-500 hover:text-slate-800'
            }`}
            onClick={() => { setMode('login'); setError('') }}
          >
            Sign in
          </button>
          <button
            type="button"
            className={`flex-1 pb-2 text-center text-sm font-semibold transition ${
              mode === 'register'
                ? 'border-b-2 border-indigo-600 text-indigo-700'
                : 'text-slate-500 hover:text-slate-800'
            }`}
            onClick={() => { setMode('register'); setError('') }}
          >
            Create account
          </button>
        </div>

        <h1 className="text-xl font-bold">
          {mode === 'login' ? 'Sign in to your account' : 'Create a visitor / patient account'}
        </h1>
        <p className="mt-1 text-xs text-slate-500">
          {mode === 'login'
            ? 'Sign in to access your appointments or staff desk.'
            : 'Track appointments, view history, and manage bookings.'}
        </p>

        <form className="mt-4 space-y-4" onSubmit={submit}>
          {mode === 'register' && (
            <Field label="Full name">
              <Input
                required
                minLength={2}
                maxLength={100}
                placeholder="Jane Doe"
                autoComplete="name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </Field>
          )}
          <Field label="E-mail">
            <Input
              type="email"
              required
              autoComplete="username"
              placeholder="user@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Password" hint={mode === 'register' ? 'At least 8 characters' : undefined}>
            <Input
              type="password"
              required
              minLength={mode === 'register' ? 8 : undefined}
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Alert>{error}</Alert>
          <Button type="submit" disabled={busy} className="w-full">
            {busy
              ? mode === 'register' ? 'Creating account…' : 'Signing in…'
              : mode === 'register' ? 'Create account' : 'Sign in'}
          </Button>
        </form>
        <Link to="/" className="mt-4 block text-center text-sm text-slate-500 hover:underline">
          ← Back to reception
        </Link>
      </Card>
    </div>
  )
}
