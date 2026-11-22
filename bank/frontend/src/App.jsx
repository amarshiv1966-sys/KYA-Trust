import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api } from './api.js'
import { flushTelemetry, restartTelemetry, telemetryPage } from './telemetry.js'
import Login from './pages/Login.jsx'
import Home from './pages/Home.jsx'
import Statements from './pages/Statements.jsx'
import Payees from './pages/Payees.jsx'
import Transfer from './pages/Transfer.jsx'
import Merchant from './pages/Merchant.jsx'
import Mandate from './pages/Mandate.jsx'
import Placeholder from './pages/Placeholder.jsx'

// Every clickable element carries a data-kya-id from contracts/element_ids.md.
// Bots click by these ids, and telemetry.js (K7) records only these elements.

function Nav({ name, onLogout }) {
  return (
    <nav className="nav">
      <strong>KYA Bank</strong>
      <Link data-kya-id="nav.home" to="/">Home</Link>
      <Link data-kya-id="nav.statements" to="/statements">Statements</Link>
      <Link data-kya-id="nav.payees" to="/payees">Payees</Link>
      <Link data-kya-id="nav.transfer" to="/transfer">Transfer</Link>
      <Link data-kya-id="nav.merchant" to="/merchant">Pay a merchant</Link>
      <Link data-kya-id="nav.mandate" to="/mandate">Assistants</Link>
      <Link data-kya-id="nav.shop" to="/shop">Shop</Link>
      <span className="spacer" />
      <span>{name}</span>
      <button data-kya-id="nav.logout" onClick={onLogout}>Log out</button>
    </nav>
  )
}

export default function App() {
  // null = not logged in; the server is the real judge, this only drives the UI
  const [user, setUser] = useState(() => JSON.parse(sessionStorage.getItem('kya_user') || 'null'))
  const navigate = useNavigate()
  const location = useLocation()

  // One page_view per real page. Skip the in-between paths that only
  // redirect (for example "/" before login, which jumps to "/login").
  useEffect(() => {
    const onLogin = location.pathname === '/login'
    if (user ? !onLogin : onLogin) telemetryPage(location.pathname)
  }, [location.pathname, user])

  useEffect(() => {
    if (user) sessionStorage.setItem('kya_user', JSON.stringify(user))
    else sessionStorage.removeItem('kya_user')
  }, [user])

  async function logout() {
    await flushTelemetry() // the logout click belongs to the old session
    try { await api('POST', '/api/logout') } catch { /* already logged out */ }
    // a fresh anonymous session, so the next login page is recorded too
    let fresh = null
    try { fresh = await api('POST', '/api/session/start', { anonymous: true }) } catch { /* bank offline */ }
    await restartTelemetry(fresh?.session_id) // reconnect the socket to the new session
    setUser(null)
    navigate('/login')
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login onLogin={setUser} />} />
        <Route path="*" element={<Navigate to="/login" />} />
      </Routes>
    )
  }

  return (
    <>
      <Nav name={user.name} onLogout={logout} />
      <main>
        <Routes>
          <Route path="/" element={<Home onExpired={() => setUser(null)} />} />
          <Route path="/statements" element={<Statements />} />
          <Route path="/payees" element={<Payees />} />
          <Route path="/transfer" element={<Transfer />} />
          <Route path="/merchant" element={<Merchant />} />
          <Route path="/mandate" element={<Mandate />} />
          <Route path="/shop" element={<Placeholder page="shop" step="K10" />} />
          <Route path="/login" element={<Navigate to="/" />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </>
  )
}
