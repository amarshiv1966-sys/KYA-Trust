import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './style.css'
import { startTelemetry } from './telemetry.js'

// Device cookie: a random id so the bank can count how many accounts one
// device has used. It is not a fingerprint. Our pages set it; API-only
// clients don't have it, which is how the server tells the channels apart.
if (!document.cookie.includes('kya_dev=')) {
  const id = 'dv_' + crypto.getRandomValues(new Uint32Array(1))[0].toString(16).padStart(8, '0')
  document.cookie = `kya_dev=${id}; path=/; max-age=31536000; samesite=strict`
}

// Start (or resume) a session before anything renders, so telemetry from the
// login page already belongs to the session the user is about to log into.
// A page with nobody logged in (in this tab) asks for an anonymous session,
// so an old logged-in session left open in the browser is not reused.
const loggedIn = Boolean(sessionStorage.getItem('kya_user'))
fetch('/api/session/start', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ anonymous: !loggedIn }),
})
  .then((r) => r.json())
  .catch(() => ({}))
  .then((d) => {
    startTelemetry(d.session_id) // after the session exists, so the socket joins it
    createRoot(document.getElementById('root')).render(
      <BrowserRouter>
        <App />
      </BrowserRouter>
    )
  })
