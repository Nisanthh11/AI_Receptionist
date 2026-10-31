import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { fmtDateTime } from '../../api/format'
import { Alert, Badge, Button, Card, Field, Input, Spinner } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

export default function MyProfile() {
  const { updateUser } = useAuth()
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [form, setForm] = useState({ full_name: '', phone: '' })

  async function fetchProfile() {
    setLoading(true)
    setError('')
    try {
      const res = await api.get('/api/auth/me')
      setProfile(res.data)
      setForm({
        full_name: res.data.full_name || '',
        phone: res.data.phone || '',
      })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchProfile()
  }, [])

  function startEdit() {
    setError('')
    setSuccess('')
    setForm({
      full_name: profile?.full_name || '',
      phone: profile?.phone || '',
    })
    setIsEditing(true)
  }

  function cancelEdit() {
    setIsEditing(false)
    setError('')
    setForm({
      full_name: profile?.full_name || '',
      phone: profile?.phone || '',
    })
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    setSuccess('')

    // Basic frontend validation
    if (form.full_name.trim().length < 2) {
      setError('Full name must be at least 2 characters.')
      setSaving(false)
      return
    }

    if (form.phone && form.phone.trim()) {
      const cleanedPhone = form.phone.replace(/[\s\-().]/g, '')
      if (!/^\+?\d{7,15}$/.test(cleanedPhone)) {
        setError('Please enter a valid phone number (7 to 15 digits, optional +).')
        setSaving(false)
        return
      }
    }

    try {
      const payload = {
        full_name: form.full_name.trim(),
        phone: form.phone.trim() ? form.phone.trim() : null,
      }
      const res = await api.patch('/api/auth/me', payload)
      setProfile(res.data)
      // Update global auth user name and phone
      updateUser({
        name: res.data.full_name,
        phone: res.data.phone,
      })
      setSuccess('Profile updated successfully.')
      setIsEditing(false)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <Spinner text="Loading your profile…" />
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">My Profile</h1>
          <p className="text-sm text-slate-500">
            View and manage your personal account and contact information.
          </p>
        </div>
        <Link to="/my-appointments">
          <Button variant="secondary" size="sm" className="flex items-center gap-1.5">
            <span>📋</span>
            <span>My Appointments</span>
          </Button>
        </Link>
      </div>

      {/* Alerts */}
      {error && <Alert kind="error">{error}</Alert>}
      {success && <Alert kind="success">{success}</Alert>}

      {/* Main Profile Card */}
      <Card className="space-y-6">
        {/* Profile Avatar & Header */}
        <div className="flex items-center gap-4 border-b border-slate-100 pb-5">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-indigo-100 text-xl font-bold text-indigo-700">
            {profile?.full_name ? profile.full_name.charAt(0).toUpperCase() : '👤'}
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-900">{profile?.full_name}</h2>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-slate-500">{profile?.email}</span>
              <Badge value={profile?.role || 'user'} />
            </div>
          </div>
        </div>

        {/* View / Edit Mode */}
        {!isEditing ? (
          <div className="space-y-5">
            <dl className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-lg bg-slate-50 p-3.5">
                <dt className="text-xs font-medium text-slate-500 uppercase tracking-wider">Full Name</dt>
                <dd className="mt-1 font-semibold text-slate-900">{profile?.full_name}</dd>
              </div>

              <div className="rounded-lg bg-slate-50 p-3.5">
                <dt className="text-xs font-medium text-slate-500 uppercase tracking-wider">Email Address</dt>
                <dd className="mt-1 font-semibold text-slate-900">{profile?.email}</dd>
              </div>

              <div className="rounded-lg bg-slate-50 p-3.5">
                <dt className="text-xs font-medium text-slate-500 uppercase tracking-wider">Phone Number</dt>
                <dd className="mt-1 font-semibold text-slate-900">
                  {profile?.phone || <span className="text-slate-400 italic font-normal">Not provided</span>}
                </dd>
              </div>

              <div className="rounded-lg bg-slate-50 p-3.5">
                <dt className="text-xs font-medium text-slate-500 uppercase tracking-wider">Account Role</dt>
                <dd className="mt-1 font-semibold text-slate-900 capitalize">
                  {profile?.role === 'user' ? 'Registered Visitor' : profile?.role}
                </dd>
              </div>

              <div className="rounded-lg bg-slate-50 p-3.5 sm:col-span-2">
                <dt className="text-xs font-medium text-slate-500 uppercase tracking-wider">Member Since</dt>
                <dd className="mt-1 text-sm text-slate-800">
                  {profile?.created_at ? fmtDateTime(profile.created_at) : 'N/A'}
                </dd>
              </div>
            </dl>

            <div className="pt-2 flex items-center justify-between">
              <Button type="button" variant="primary" onClick={startEdit} className="flex items-center gap-2">
                <span>✏️</span>
                <span>Edit Profile</span>
              </Button>
              <Link to="/my-appointments" className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline">
                View appointment history →
              </Link>
            </div>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={handleSubmit}>
            <Field label="Full name">
              <Input
                required
                minLength={2}
                maxLength={100}
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                placeholder="Your full name"
              />
            </Field>

            <Field label="Phone number" hint="Used for appointment confirmations and notifications (e.g. +919876543210)">
              <Input
                type="tel"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="+91..."
              />
            </Field>

            <Field label="Email address" hint="Email address is tied to your account login and cannot be modified directly.">
              <Input
                type="email"
                disabled
                value={profile?.email || ''}
                className="bg-slate-100 text-slate-500 cursor-not-allowed"
              />
            </Field>

            <div className="pt-4 flex items-center gap-3">
              <Button type="submit" disabled={saving} variant="primary">
                {saving ? 'Saving…' : 'Save Changes'}
              </Button>
              <Button type="button" variant="secondary" onClick={cancelEdit} disabled={saving}>
                Cancel
              </Button>
            </div>
          </form>
        )}
      </Card>
    </div>
  )
}
