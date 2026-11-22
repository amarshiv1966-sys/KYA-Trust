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
    <div className="center" data-kya-page="login">
      <div className="card">
        <h2>Log in to KYA Bank</h2>
        <form data-kya-id="login.form" onSubmit={submit}>
          <label htmlFor="username">Customer id</label>
          <input id="username" data-kya-id="login.username" value={username}
                 onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
          <label htmlFor="password">Password</label>
          {/* password fields never produce telemetry events */}
          <input id="password" type="password" data-kya-id="login.password" value={password}
                 onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          <button type="submit" data-kya-id="login.submit">Log in</button>
          {error && <p className="error">{error}</p>}
        </form>
      </div>
    </div>
  )
}
