// Supabase Auth over plain fetch (email + password), so the frontend needs no extra package.
// When VITE_SUPABASE_URL is empty the app runs in dev mode: no login, the backend must have
// DEV_AUTH=true and no SUPABASE_URL, and every request carries `X-Dev-User`.

const SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL || '').replace(/\/$/, '')
const PUBLISHABLE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || ''
const STORAGE_KEY = 'orbit.session'

export const DEV_MODE = !SUPABASE_URL
export const DEV_USER = import.meta.env.VITE_DEV_USER || 'demo-user'

function load() {
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null')
  } catch {
    return null
  }
}

function save(session) {
  try {
    if (session) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // storage can be unavailable (private mode); the session then lasts for this tab only
  }
}

let current = load()

function toSession(data) {
  return {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_at: data.expires_at || Math.floor(Date.now() / 1000) + (data.expires_in || 3600),
    email: data.user?.email || current?.email || '',
  }
}

async function tokenRequest(grant, body) {
  let response
  try {
    response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=${grant}`, {
      method: 'POST',
      headers: { apikey: PUBLISHABLE_KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error(`連不到 Supabase（${SUPABASE_URL}），請檢查網路或 .env.local`)
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = data.error_description || data.msg || data.message || `登入失敗（${response.status}）`
    throw new Error(message === 'Invalid login credentials' ? '帳號或密碼錯誤' : message)
  }
  return data
}

export function currentUser() {
  if (DEV_MODE) return { email: `${DEV_USER}（開發模式）` }
  return current ? { email: current.email } : null
}

export async function signIn(email, password) {
  current = toSession(await tokenRequest('password', { email, password }))
  save(current)
  return currentUser()
}

export function signOut() {
  current = null
  save(null)
}

let refreshing = null

// Returns the headers that identify the user to the backend, refreshing the token when needed.
export async function authHeaders() {
  if (DEV_MODE) return { 'X-Dev-User': DEV_USER }
  if (!current) throw new AuthError('請先登入')
  if (current.expires_at - 60 < Date.now() / 1000) {
    refreshing ??= tokenRequest('refresh_token', { refresh_token: current.refresh_token })
      .then((data) => {
        current = toSession(data)
        save(current)
      })
      .catch(() => {
        signOut()
        throw new AuthError('登入已過期，請重新登入')
      })
      .finally(() => {
        refreshing = null
      })
    await refreshing
  }
  return { Authorization: `Bearer ${current.access_token}` }
}

export class AuthError extends Error {}
