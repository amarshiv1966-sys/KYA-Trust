import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './style.css'

// Device cookie: a random id so the bank can count how many accounts one
// device has used. It is not a fingerprint. Our pages set it; API-only
// clients don't have it, which is how the server tells the channels apart.
if (!document.cookie.includes('kya_dev=')) {
  const id = 'dv_' + crypto.getRandomValues(new Uint32Array(1))[0].toString(16).padStart(8, '0')
  document.cookie = `kya_dev=${id}; path=/; max-age=31536000; samesite=strict`
}

createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>
)
