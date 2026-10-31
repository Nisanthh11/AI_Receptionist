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
    const u = { role: data.role, name: data.full_name, user_id: data.user_id, email }
    sessionStorage.setItem('user', JSON.stringify(u))
    setUser(u)
    return data
  }

  async function register(email, password, full_name) {
    const { data } = await api.post('/api/auth/register', { email, password, full_name })
    sessionStorage.setItem('token', data.access_token)
    const u = { role: data.role, name: data.full_name, user_id: data.user_id, email }
    sessionStorage.setItem('user', JSON.stringify(u))
    setUser(u)
    return data
  }

  function updateUser(patch) {
    setUser((prev) => {
      if (!prev) return null
      const updated = { ...prev, ...patch }
      sessionStorage.setItem('user', JSON.stringify(updated))
      return updated
    })
  }

  function logout() {
    sessionStorage.clear()
    setUser(null)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        login,
        register,
        updateUser,
        logout,
        isAdmin: user?.role === 'admin',
        isStaff: user?.role === 'admin' || user?.role === 'receptionist',
        isUser: user?.role === 'user',
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
