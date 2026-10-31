import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { errorMessage } from '../../api/client'
import { Alert, Button, Card, Field, Input } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

export default function Login() {
  const { user, login } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to="/admin" replace />
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('')
    try { await login(email, password); nav('/admin') } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <h1 className="text-xl font-bold">Staff sign in</h1>
        <form className="mt-4 space-y-4" onSubmit={submit}>
          <Field label="E-mail"><Input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password"><Input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <Alert>{error}</Alert>
          <Button type="submit" disabled={busy} className="w-full">{busy ? 'Signing in…' : 'Sign in'}</Button>
        </form>
        <Link to="/" className="mt-4 block text-center text-sm text-slate-500 hover:underline">← Back to reception</Link>
      </Card>
    </div>
  )
}
