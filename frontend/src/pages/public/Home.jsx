import { Link, useOutletContext } from 'react-router-dom'
import { Card } from '../../components/ui'

const tiles = [
  { to: '/chat', icon: '💬', title: 'Ask the receptionist', text: 'Get answers about departments, working hours and common questions.' },
  { to: '/call', icon: '📞', title: 'Call AI Receptionist', text: 'Have a spoken two-way voice conversation to book appointments or ask questions.' },
  { to: '/book', icon: '📅', title: 'Book an appointment', text: 'Pick a department, a person and a free time slot.' },
  { to: '/register', icon: '📝', title: 'Visitor registration', text: 'Arriving without an appointment? Register here, then tell reception.' },
  { to: '/status', icon: '🔎', title: 'Check appointment status', text: 'Use your reference code and phone number.' },
  { to: '/directory', icon: '🏢', title: 'Departments & FAQ', text: 'Find locations, staff and frequently asked questions.' },
]

export default function Home() {
  const { org } = useOutletContext()
  return (
    <div className="space-y-8">
      <section className="rounded-2xl bg-gradient-to-br from-indigo-600 to-indigo-800 p-8 text-white md:p-12">
        <h1 className="text-3xl font-bold md:text-4xl">{org.welcome_message || `Welcome${org.organization_name ? ' to ' + org.organization_name : ''}`}</h1>
        <p className="mt-3 max-w-2xl text-indigo-100">How can we help you today? Choose an option below, or speak with our virtual voice receptionist.</p>
        {org.working_hours && <p className="mt-4 inline-block rounded-lg bg-white/15 px-3 py-1.5 text-sm">Working hours: {org.working_hours}</p>}
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/call" className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-5 py-2.5 font-semibold text-white shadow-md hover:bg-emerald-600 transition">
            <span>📞</span> Call Receptionist
          </Link>
          <Link to="/chat" className="inline-block rounded-lg bg-white px-5 py-2.5 font-semibold text-indigo-700 hover:bg-indigo-50 transition">
            Start text chat
          </Link>
        </div>
      </section>
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map((t) => (
          <Link key={t.to} to={t.to}><Card className="h-full transition hover:border-indigo-300 hover:shadow-md">
            <div className="text-3xl" aria-hidden>{t.icon}</div><h2 className="mt-3 font-semibold">{t.title}</h2><p className="mt-1 text-sm text-slate-600">{t.text}</p>
          </Card></Link>
        ))}
      </section>
    </div>
  )
}
