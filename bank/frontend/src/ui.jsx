// Small shared pieces for the pages. Kept plain on purpose: the bank should
// feel ordinary, so volunteers use it the way they use their own bank.

export function PageHeader({ title, children }) {
  return (
    <header className="page-header">
      <h1>{title}</h1>
      {children && <p>{children}</p>}
    </header>
  )
}

// Outcome of an action. Success uses .ok, everything else .error: the bots
// wait for these two class names, so they must not change.
export function Notice({ msg }) {
  if (msg.ok) return <p className="notice ok" role="status">{msg.ok}</p>
  if (msg.error) return <p className={`notice error ${msg.tone || ''}`} role="alert">{msg.error}</p>
  return null
}

const TINTS = ['#D8EBE5', '#E9E2F2', '#F4E6D3', '#DCE6F3', '#F2DDE0', '#E3ECD5']

export function Avatar({ name }) {
  const initials = (name || '?').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  let h = 0
  for (const c of name || '') h = (h * 31 + c.charCodeAt(0)) >>> 0
  return <span className="avatar" style={{ background: TINTS[h % TINTS.length] }} aria-hidden="true">{initials}</span>
}

const CATEGORY_NAMES = {
  salary: 'Salary', grocery: 'Groceries', utilities: 'Electricity', telecom: 'Internet',
  food_delivery: 'Food delivery', electronics: 'Electronics', travel: 'Travel',
  entertainment: 'Subscriptions', education: 'Education', gift_cards: 'Gift cards',
  crypto_exchange: 'Crypto exchange',
}

export function describe(row) {
  if (row.action === 'credit') return 'Money received'
  if (row.action === 'transfer') return 'Bank transfer'
  return CATEGORY_NAMES[row.category] || 'Payment'
}

export function categoryName(c) {
  return CATEGORY_NAMES[c] || c
}

export function dayLabel(ts) {
  const d = new Date(ts)
  const today = new Date()
  const y = new Date(); y.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === y.toDateString()) return 'Yesterday'
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

export function groupByDay(rows) {
  const groups = []
  for (const r of rows) {
    const label = dayLabel(r.ts_ms)
    if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, rows: [] })
    groups[groups.length - 1].rows.push(r)
  }
  return groups
}
