import { Navigate, Route, Routes } from 'react-router-dom'
import { AdminLayout, ProtectedRoute, PublicLayout } from './components/Layouts.jsx'
import Home from './pages/public/Home.jsx'
import Chat from './pages/public/Chat.jsx'
import Register from './pages/public/Register.jsx'
import Book from './pages/public/Book.jsx'
import Status from './pages/public/Status.jsx'
import Directory from './pages/public/Directory.jsx'
import Login from './pages/admin/Login.jsx'
import Dashboard from './pages/admin/Dashboard.jsx'
import Appointments from './pages/admin/Appointments.jsx'
import Visitors from './pages/admin/Visitors.jsx'
import DirectoryAdmin from './pages/admin/DirectoryAdmin.jsx'
import Content from './pages/admin/Content.jsx'
import Analytics from './pages/admin/Analytics.jsx'
import Users from './pages/admin/Users.jsx'
import MyAppointments from './pages/user/MyAppointments.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/register" element={<Register />} />
        <Route path="/book" element={<Book />} />
        <Route path="/status" element={<Status />} />
        <Route path="/directory" element={<Directory />} />
        <Route path="/my-appointments" element={<ProtectedRoute><MyAppointments /></ProtectedRoute>} />
      </Route>
      <Route path="/login" element={<Login />} />
      <Route path="/admin/login" element={<Login />} />
      <Route path="/admin" element={<ProtectedRoute staffOnly><AdminLayout /></ProtectedRoute>}>
        <Route index element={<Dashboard />} />
        <Route path="appointments" element={<Appointments />} />
        <Route path="visitors" element={<Visitors />} />
        <Route path="directory" element={<DirectoryAdmin />} />
        <Route path="content" element={<Content />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="users" element={<ProtectedRoute adminOnly><Users /></ProtectedRoute>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
