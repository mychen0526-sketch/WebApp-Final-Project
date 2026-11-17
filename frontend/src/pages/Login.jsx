import { useState } from 'react'
import { signIn } from '../lib/auth.js'

export function LoginPage({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      onLogin(await signIn(email.trim(), password))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand" style={{ marginBottom: 18 }}>
          <div className="mark" />
          <div>
            <b>orbit.studio</b>
            <span>內容工作台</span>
          </div>
        </div>
        <h3>登入</h3>
        <p className="sub">用 Supabase 裡建立的帳號登入。</p>
        <label className="field">
          電子郵件
          <input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label className="field" style={{ marginTop: 10 }}>
          密碼
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        </label>
        {error ? <p className="notice bad" style={{ marginTop: 12 }}>{error}</p> : null}
        <button className="btn primary" type="submit" disabled={busy} style={{ marginTop: 16, width: '100%' }}>
          {busy ? '登入中…' : '登入'}
        </button>
      </form>
    </div>
  )
}
