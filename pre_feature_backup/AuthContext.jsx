import { createContext, useContext, useState } from 'react'
import api from '../api/client'

const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const raw = sessionStorage.getItem('user')
    return raw && sessionStorage.getItem('token') ? JSON.parse(raw) : null
  })

  async function login(email, password) {
    const { data } = await api.post('/api/auth/login', { email, password })
    sessionStorage.setItem('token', data.access_token)
    const u = { role: data.role, name: data.full_name }
    sessionStorage.setItem('user', JSON.stringify(u))
    setUser(u)
  }

  function logout() {
    sessionStorage.clear()
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, login, logout, isAdmin: user?.role === 'admin' }}>{children}</AuthContext.Provider>
}
