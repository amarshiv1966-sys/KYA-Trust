import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { flushTelemetry, followSession } from '../telemetry.js'

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      await flushTelemetry()
      const user = await api('POST', '/api/login', { username, password })
      await followSession(user.session_id) // safety net: same session for behaviour and payments
      onLogin(user)
      navigate('/')
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="login" data-kya-page="login">
      <div className="login-side">
        <div className="brand"><span className="brand-mark">K</span>KYA Bank</div>
        <div>
          <h2>Your money, and who is moving it.</h2>
          <p>Send money, pay bills and give your assistants limited permission, all from one account.</p>
        </div>
        <p style={{ fontSize: 13 }}>A demo bank for the KYA-Trust study. No real money moves.</p>
      </div>
      <div className="login-form">
        <h1>Log in</h1>
        <form data-kya-id="login.form" onSubmit={submit}>
          <label htmlFor="username">Customer ID</label>
          <input id="username" data-kya-id="login.username" value={username}
                 onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
          <label htmlFor="password">Password</label>
          {/* password fields never produce telemetry events */}
          <input id="password" type="password" data-kya-id="login.password" value={password}
                 onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          <button type="submit" data-kya-id="login.submit">Log in</button>
          {error && <p className="notice error">{error}</p>}
        </form>
      </div>
    </div>
  )
}
