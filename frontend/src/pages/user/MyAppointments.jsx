import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'
import { fmtDateTime } from '../../api/format'
import { Alert, Badge, Button, Card, Modal, Spinner } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

export default function MyAppointments() {
  const { user } = useAuth()
  const [data, setData] = useState({ upcoming: [], previous: [], total: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('upcoming') // 'upcoming' | 'previous'
  const [selectedAppt, setSelectedAppt] = useState(null)
  const [copiedRef, setCopiedRef] = useState('')

  async function fetchAppointments() {
    setLoading(true)
    setError('')
    try {
      const res = await api.get('/api/user/appointments')
      setData(res.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAppointments()
  }, [])

  function copyCode(code) {
    navigator.clipboard.writeText(code).then(() => {
      setCopiedRef(code)
      setTimeout(() => setCopiedRef(''), 2000)
    }).catch(() => {})
  }

  const items = tab === 'upcoming' ? data.upcoming : data.previous

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">My Appointments</h1>
          <p className="text-sm text-slate-500">
            Welcome back, {user?.name}. View your scheduled and previous appointments.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={fetchAppointments} disabled={loading}>
            ↻ Refresh
          </Button>
          <Link to="/book">
            <Button variant="primary" size="sm">
              + Book New Appointment
            </Button>
          </Link>
        </div>
      </div>

      {/* Error state */}
      <Alert>{error}</Alert>

      {/* Tabs */}
      <div className="flex border-b border-slate-200">
        <button
          type="button"
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold transition border-b-2 ${
            tab === 'upcoming'
              ? 'border-indigo-600 text-indigo-700'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
          onClick={() => setTab('upcoming')}
        >
          <span>Upcoming Appointments</span>
          <span className={`rounded-full px-2 py-0.5 text-xs ${
            tab === 'upcoming' ? 'bg-indigo-100 text-indigo-800' : 'bg-slate-100 text-slate-600'
          }`}>
            {data.upcoming.length}
          </span>
        </button>
        <button
          type="button"
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold transition border-b-2 ${
            tab === 'previous'
              ? 'border-indigo-600 text-indigo-700'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
          onClick={() => setTab('previous')}
        >
          <span>Past Appointments</span>
          <span className={`rounded-full px-2 py-0.5 text-xs ${
            tab === 'previous' ? 'bg-indigo-100 text-indigo-800' : 'bg-slate-100 text-slate-600'
          }`}>
            {data.previous.length}
          </span>
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <Spinner text="Loading your appointments…" />
      ) : items.length === 0 ? (
        <Card className="text-center py-12">
          <div className="text-4xl mb-2">📋</div>
          <h3 className="text-base font-semibold text-slate-800">
            {tab === 'upcoming' ? 'No upcoming appointments' : 'No past appointments found'}
          </h3>
          <p className="mt-1 text-sm text-slate-500 max-w-sm mx-auto">
            {tab === 'upcoming'
              ? "You don't have any appointments scheduled. Need assistance or want to meet our staff?"
              : 'Completed or cancelled appointments will appear here for your records.'}
          </p>
          {tab === 'upcoming' && (
            <div className="mt-4">
              <Link to="/book">
                <Button variant="primary">Schedule an Appointment</Button>
              </Link>
            </div>
          )}
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {items.map((appt) => (
            <Card key={appt.id} className="flex flex-col justify-between hover:border-slate-300 transition">
              <div>
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-bold text-indigo-700">
                      {appt.reference_code}
                    </span>
                    <button
                      type="button"
                      onClick={() => copyCode(appt.reference_code)}
                      className="text-slate-400 hover:text-indigo-600 text-xs"
                      title="Copy reference code"
                    >
                      {copiedRef === appt.reference_code ? '✓' : '📋'}
                    </button>
                  </div>
                  <Badge value={appt.status} />
                </div>

                <div className="space-y-1.5 text-sm text-slate-700">
                  <div className="flex items-center gap-2 font-medium text-slate-900">
                    <span>🗓️</span>
                    <span>{fmtDateTime(appt.start_at)}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-600">
                    <span>👤</span>
                    <span>{appt.staff_name}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-600">
                    <span>🏢</span>
                    <span>{appt.department_name}</span>
                  </div>
                  <div className="mt-2 text-xs text-slate-500 bg-slate-50 rounded p-2">
                    <span className="font-medium text-slate-700">Purpose: </span>
                    {appt.purpose}
                  </div>
                </div>

                {/* Status-specific notices */}
                {appt.status === 'pending' && (
                  <p className="mt-2 text-xs text-amber-700 font-medium">
                    ⏳ Waiting for reception confirmation
                  </p>
                )}
                {appt.cancelled_reason && (
                  <p className="mt-2 text-xs text-red-600">
                    Reason: {appt.cancelled_reason}
                  </p>
                )}
              </div>

              <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between">
                <div className="flex gap-1 text-[11px] text-slate-400">
                  {appt.sms_status && appt.sms_status !== 'not_configured' && (
                    <span className="bg-slate-100 px-1.5 py-0.5 rounded">SMS: {appt.sms_status}</span>
                  )}
                  {appt.email_status && appt.email_status !== 'not_configured' && (
                    <span className="bg-slate-100 px-1.5 py-0.5 rounded">Email: {appt.email_status}</span>
                  )}
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setSelectedAppt(appt)}
                >
                  View Details
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Detail Modal */}
      {selectedAppt && (
        <Modal title={`Appointment Details — ${selectedAppt.reference_code}`} onClose={() => setSelectedAppt(null)}>
          <div className="space-y-4 text-sm">
            <div className="flex items-center justify-between border-b pb-3">
              <div>
                <p className="text-xs text-slate-500">Status</p>
                <div className="mt-1"><Badge value={selectedAppt.status} /></div>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-500">Reference Code</p>
                <div className="flex items-center gap-1 font-mono font-bold text-indigo-700">
                  <span>{selectedAppt.reference_code}</span>
                  <button
                    type="button"
                    onClick={() => copyCode(selectedAppt.reference_code)}
                    className="text-xs text-slate-400 hover:text-indigo-600"
                  >
                    {copiedRef === selectedAppt.reference_code ? '✓ Copied' : '📋'}
                  </button>
                </div>
              </div>
            </div>

            <dl className="grid grid-cols-2 gap-3">
              <div>
                <dt className="text-xs text-slate-500">Scheduled Time</dt>
                <dd className="font-medium text-slate-800">{fmtDateTime(selectedAppt.start_at)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Staff Member</dt>
                <dd className="font-medium text-slate-800">{selectedAppt.staff_name}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Department</dt>
                <dd className="font-medium text-slate-800">{selectedAppt.department_name}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Booked On</dt>
                <dd className="font-medium text-slate-800">{fmtDateTime(selectedAppt.created_at)}</dd>
              </div>
            </dl>

            <div>
              <p className="text-xs text-slate-500">Purpose</p>
              <p className="mt-1 rounded bg-slate-50 p-2 text-slate-800">{selectedAppt.purpose}</p>
            </div>

            {selectedAppt.notes && (
              <div>
                <p className="text-xs text-slate-500">Staff Notes</p>
                <p className="mt-1 rounded bg-amber-50 p-2 text-amber-900 text-xs">{selectedAppt.notes}</p>
              </div>
            )}

            {selectedAppt.cancelled_reason && (
              <div>
                <p className="text-xs text-slate-500">Cancellation Reason</p>
                <p className="mt-1 rounded bg-red-50 p-2 text-red-800 text-xs">{selectedAppt.cancelled_reason}</p>
              </div>
            )}

            <div className="border-t pt-3 flex justify-between items-center text-xs text-slate-500">
              <span>Delivery Status: SMS ({selectedAppt.sms_status || 'none'}), Email ({selectedAppt.email_status || 'none'})</span>
              <Button variant="secondary" size="sm" onClick={() => setSelectedAppt(null)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
