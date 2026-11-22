// Behaviour telemetry (K7). Records how the person (or bot) uses the pages and
// sends it to the bank over the WebSocket /ws/telemetry. Event format:
// docs/schema.md section 2.
//
// What it records: page views, pointer movement (about 20 samples a second),
// clicks and key timings on elements with a data-kya-id, scrolling, and a
// summary of each form when it is submitted.
// What it never records: which key was pressed (only its class, like
// "letter"), anything in a password field, page text, or elements without a
// data-kya-id. The server enforces the same rules again (ingest.py).
//
// Sending: events wait in a buffer and go out as one batch every second.
// Each batch stays in `unacked` until the server answers {"ack": batch_id},
// and is sent again after a reconnect. The server drops events it already has.
// flushTelemetry() is awaited before every form request, so the bank has the
// last seconds of behaviour before it sees the payment.

const SEND_EVERY_MS = 1000
const POINTER_EVERY_MS = 50          // about 20 Hz
const POINTS_PER_EVENT = 20
const SCROLL_EVERY_MS = 250
const FLUSH_TIMEOUT_MS = 1500        // a broken socket must never block a payment
const SECRET_IDS = new Set(['login.password', 'stepup.pin'])

const PAGES = {
  '/': 'home', '/login': 'login', '/statements': 'statements', '/payees': 'payees',
  '/transfer': 'transfer', '/merchant': 'merchant', '/mandate': 'mandate',
  '/shop': 'shop', '/stepup': 'stepup',
}

let ws = null
let wsReady = false
let started = false
let buffer = []                  // events not yet put in a batch
const unacked = new Map()        // batch_id -> batch, until the server acks it
const ackWaiters = new Map()     // batch_id -> resolve()
let reconnectDelay = 500

let page = null
let client = null
let points = []                  // pointer samples for the next pointer_move event
let pointsStart = 0
let lastPointerAt = 0
let pressDown = null             // { el, t } from the last pointerdown
const keyDown = new Map()        // e.code -> keydown time
let lastKeyUp = null             // for flight_ms; reset on every page
let scrollAcc = { dx: 0, dy: 0, at: 0, x: 0, y: 0 }
const typedFields = new Set()    // data-kya-ids that got at least one keystroke
const pastes = new Map()         // form id -> paste count

// ---------- helpers ----------

function randomId(prefix) {
  const b = crypto.getRandomValues(new Uint8Array(8))
  return prefix + Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
}

function kyaId(el) {
  const found = el && el.closest ? el.closest('[data-kya-id]') : null
  return found ? found.getAttribute('data-kya-id') : null
}

function isSecret(el) {
  if (!el) return false
  if (el.type === 'password') return true
  return SECRET_IDS.has(el.getAttribute && el.getAttribute('data-kya-id'))
}

function keyClass(key) {
  if (key === 'Backspace' || key === 'Delete') return 'backspace'
  if (key === 'Enter') return 'enter'
  if (key === 'Tab') return 'tab'
  if (key === ' ') return 'space'
  if (key.length === 1) {
    if (/[0-9]/.test(key)) return 'digit'
    if (/\p{L}/u.test(key)) return 'letter'
    return 'punct'
  }
  return 'other' // arrows, shift, ctrl, ...
}

// Coarse device classes only (schema.md section 3). Nothing that identifies a person.
function readClient() {
  const ua = navigator.userAgent.toLowerCase()
  const touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches
  let os = 'other'
  if (ua.includes('windows')) os = 'windows'
  else if (ua.includes('iphone') || ua.includes('ipad')) os = 'ios'
  else if (ua.includes('mac os')) os = 'macos'
  else if (ua.includes('android')) os = 'android'
  else if (ua.includes('linux')) os = 'linux'
  let browser = 'other'
  if (ua.includes('edg/')) browser = 'edge'
  else if (ua.includes('firefox')) browser = 'firefox'
  else if (ua.includes('chrome')) browser = 'chrome'
  else if (ua.includes('safari')) browser = 'safari'
  let deviceClass = 'desktop'
  if (touch) deviceClass = Math.min(screen.width, screen.height) < 600 ? 'phone' : 'tablet'
  const cookie = document.cookie.split('; ').find((c) => c.startsWith('kya_dev='))
  return {
    device_id: cookie ? cookie.slice('kya_dev='.length) : null,
    device_class: deviceClass,
    os_family: os,
    browser_family: browser,
    input_type: touch ? 'touch' : 'mouse',
    webdriver: navigator.webdriver === true,
    languages_count: (navigator.languages || []).length,
    timezone_offset_min: -new Date().getTimezoneOffset(), // IST = 330
  }
}

function record(type, data) {
  buffer.push({
    event_id: randomId('ev_'),
    client_ts_ms: Date.now(),
    type,
    page,
    client,
    data,
  })
}

// ---------- pointer and scroll (kept in small accumulators, emitted in bulk) ----------

function emitPoints() {
  if (points.length) {
    record('pointer_move', { points })
    points = []
  }
}

function emitScroll() {
  if (scrollAcc.dx || scrollAcc.dy) {
    record('scroll', { dx: scrollAcc.dx, dy: scrollAcc.dy })
    scrollAcc.dx = 0
    scrollAcc.dy = 0
  }
}

function onPointerMove(e) {
  const t = performance.now()
  if (t - lastPointerAt < POINTER_EVERY_MS) return
  lastPointerAt = t
  if (!points.length) pointsStart = t
  points.push([Math.round(t - pointsStart), Math.round(e.pageX), Math.round(e.pageY)])
  if (points.length >= POINTS_PER_EVENT) emitPoints()
}

function onScroll() {
  const x = window.scrollX
  const y = window.scrollY
  scrollAcc.dx += x - scrollAcc.x
  scrollAcc.dy += y - scrollAcc.y
  scrollAcc.x = x
  scrollAcc.y = y
  const t = performance.now()
  if (t - scrollAcc.at >= SCROLL_EVERY_MS) {
    scrollAcc.at = t
    emitScroll()
  }
}

// ---------- clicks ----------

function onPointerDown(e) {
  pressDown = { el: e.target, t: performance.now() }
}

function onClick(e) {
  const el = e.target.closest ? e.target.closest('[data-kya-id]') : null
  if (!el || isSecret(el)) return
  const r = el.getBoundingClientRect()
  const cx = r.left + r.width / 2
  const cy = r.top + r.height / 2
  // A click with no pointer behind it (detail 0) comes from a script's
  // el.click() or from pressing Enter/Space. It has no real position, so we
  // record the element's centre and no press time.
  const real = e.detail > 0 && pressDown && el.contains(pressDown.el)
  const clientX = real ? e.clientX : cx
  const clientY = real ? e.clientY : cy
  emitPoints() // keep the order: movement first, then the click it led to
  record('click', {
    target: el.getAttribute('data-kya-id'),
    x: Math.round(clientX + window.scrollX),
    y: Math.round(clientY + window.scrollY),
    target_w: Math.round(r.width),
    target_h: Math.round(r.height),
    offset_x: Math.round((clientX - cx) * 10) / 10,
    offset_y: Math.round((clientY - cy) * 10) / 10,
    press_ms: real ? Math.round(performance.now() - pressDown.t) : null,
  })
  pressDown = null
}

// ---------- keys (timings and key class only, never the key) ----------

function onKeyDown(e) {
  if (e.repeat || isSecret(e.target) || !kyaId(e.target)) return
  keyDown.set(e.code || e.key, { t: performance.now(), flight: lastKeyUp === null ? null : performance.now() - lastKeyUp })
}

function onKeyUp(e) {
  const down = keyDown.get(e.code || e.key)
  if (!down) return
  keyDown.delete(e.code || e.key)
  if (isSecret(e.target)) return
  const target = kyaId(e.target)
  if (!target) return
  const t = performance.now()
  lastKeyUp = t
  typedFields.add(target)
  record('keystroke', {
    target,
    key_class: keyClass(e.key),
    dwell_ms: Math.round(t - down.t),
    flight_ms: down.flight === null ? null : Math.round(down.flight),
  })
}

function onPaste(e) {
  if (isSecret(e.target)) return
  const form = e.target.closest && e.target.closest('form[data-kya-id]')
  if (!form) return
  const id = form.getAttribute('data-kya-id')
  pastes.set(id, (pastes.get(id) || 0) + 1)
}

// ---------- forms ----------

// Runs in the capture phase, before React's onSubmit handler, so the
// form_submit event is already in the buffer when the page awaits
// flushTelemetry().
function onSubmit(e) {
  const form = e.target
  const id = form.getAttribute && form.getAttribute('data-kya-id')
  if (!id) return
  let filled = 0
  let withoutKeys = 0
  for (const field of form.querySelectorAll('input, select, textarea')) {
    // Password fields never produce key events, so they are left out of the
    // counts entirely (otherwise every login would look half scripted).
    if (field.type === 'submit' || field.type === 'button' || !field.value || isSecret(field)) continue
    filled += 1
    const fid = field.getAttribute('data-kya-id')
    // A dropdown is filled by clicking, not typing, so it never counts here.
    if (field.tagName !== 'SELECT' && !typedFields.has(fid)) withoutKeys += 1
  }
  emitPoints()
  emitScroll()
  record('form_submit', {
    form: id,
    fields_filled: filled,
    fields_without_keys: withoutKeys,
    paste_count: pastes.get(id) || 0,
  })
  pastes.delete(id)
  for (const field of form.querySelectorAll('[data-kya-id]')) typedFields.delete(field.getAttribute('data-kya-id'))
}

// ---------- sending ----------

function send(batch) {
  if (wsReady) ws.send(JSON.stringify(batch))
}

function sendBuffer() {
  if (!buffer.length) return null
  const batch = { batch_id: randomId('b_'), events: buffer }
  buffer = []
  unacked.set(batch.batch_id, batch)
  send(batch)
  return batch.batch_id
}

function tick() {
  emitPoints()
  emitScroll()
  sendBuffer()
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const sock = new WebSocket(`${proto}://${location.host}/ws/telemetry`)
  ws = sock
  sock.onopen = () => {
    if (ws !== sock) return
    wsReady = true
    reconnectDelay = 500
    for (const batch of unacked.values()) sock.send(JSON.stringify(batch)) // resend; duplicates are dropped
  }
  sock.onmessage = (m) => {
    let msg = null
    try { msg = JSON.parse(m.data) } catch { return }
    if (!msg || !msg.ack) return
    unacked.delete(msg.ack)
    const done = ackWaiters.get(msg.ack)
    if (done) { ackWaiters.delete(msg.ack); done() }
  }
  sock.onclose = () => {
    if (ws !== sock) return // replaced by restartTelemetry()
    wsReady = false
    setTimeout(connect, reconnectDelay)
    reconnectDelay = Math.min(reconnectDelay * 2, 8000)
  }
}

// ---------- public ----------

export function startTelemetry() {
  if (started) return
  started = true
  client = readClient()
  scrollAcc.x = window.scrollX
  scrollAcc.y = window.scrollY
  const opts = { capture: true, passive: true }
  window.addEventListener('pointermove', onPointerMove, opts)
  window.addEventListener('pointerdown', onPointerDown, opts)
  window.addEventListener('click', onClick, opts)
  window.addEventListener('keydown', onKeyDown, opts)
  window.addEventListener('keyup', onKeyUp, opts)
  window.addEventListener('paste', onPaste, opts)
  window.addEventListener('scroll', onScroll, opts)
  window.addEventListener('submit', onSubmit, { capture: true })
  setInterval(tick, SEND_EVERY_MS)
  connect()
}

// Called by App on every route change.
export function telemetryPage(pathname) {
  const next = PAGES[pathname] || null
  if (next === page) return
  emitPoints()
  const from = page
  page = next
  lastKeyUp = null
  record('page_view', { from_page: from, viewport_w: window.innerWidth, viewport_h: window.innerHeight })
}

// Send everything buffered and wait until the server has it (or give up
// after FLUSH_TIMEOUT_MS). Every page awaits this before a form request.
export async function flushTelemetry() {
  if (!started) return
  emitPoints()
  emitScroll()
  sendBuffer()
  if (!unacked.size) return
  // If the socket is down, onopen resends these batches and the acks still come.
  const waits = [...unacked.keys()].map((id) => new Promise((r) => ackWaiters.set(id, r)))
  const timeout = new Promise((r) => setTimeout(r, FLUSH_TIMEOUT_MS))
  await Promise.race([Promise.all(waits), timeout])
}

// After logout the server starts a new session. The socket belongs to the old
// one, so send what is left there, then reconnect for the new session.
export async function restartTelemetry() {
  if (!started) return
  await flushTelemetry()
  const old = ws
  ws = null
  wsReady = false
  unacked.clear()
  page = null // the next page_view starts the new session's history
  if (old) old.close()
  connect()
}
