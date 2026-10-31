import axios from 'axios'

// Every call goes to the real FastAPI backend. The JWT lives in sessionStorage (cleared when the tab closes).
const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '', timeout: 20000 })

api.interceptors.request.use((cfg) => {
  const token = sessionStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && sessionStorage.getItem('token')) {
      sessionStorage.clear()
      if (!window.location.pathname.startsWith('/admin/login')) window.location.assign('/admin/login')
    }
    return Promise.reject(err)
  },
)

export function errorMessage(err) {
  if (!err.response) return 'Cannot reach the server. Check that the backend is running and try again.'
  const d = err.response.data
  if (d?.errors?.length) return d.errors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join('; ')
  return d?.detail || 'Something went wrong. Please try again.'
}

export default api
