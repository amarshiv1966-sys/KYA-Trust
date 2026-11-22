import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { formatPaise } from '../money.js'
import { Avatar, describe, groupByDay } from '../ui.jsx'

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

export function Passbook({ rows }) {
  if (!rows.length) return <p className="empty">No money has moved in this period.</p>
  return groupByDay(rows).map((g) => (
    <section className="day" key={g.label}>
      <div className="day-label">{g.label}</div>
      {g.rows.map((r) => (
        <div className="entry" key={r.txn_id}>
          <Avatar name={r.name} />
          <div>
            <div className="name">{r.name}</div>
            <div className="what">
              {describe(r)}, {new Date(r.ts_ms).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}
            </div>
          </div>
          <div className={`amt ${r.amount_paise > 0 ? 'in' : ''}`}>
            {r.amount_paise > 0 ? '+' : '−'}{formatPaise(Math.abs(r.amount_paise))}
            <span className="after">Balance {formatPaise(r.balance_after)}</span>
          </div>
        </div>
      ))}
    </section>
  ))
}

export default function Home({ name, onExpired }) {
  const [balance, setBalance] = useState(null)
  const [account, setAccount] = useState('')
  const [rows, setRows] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    api('GET', '/api/balance').then((d) => { setBalance(d.balance_paise); setAccount(d.account_id) }).catch(onExpired)
    api('GET', '/api/statements?range=30').then((d) => setRows(d.rows.slice(0, 12))).catch(() => setRows([]))
  }, [])

  return (
    <div data-kya-page="home">
      <p className="hello">{greeting()}, {name.startsWith('Volunteer') ? name : name.split(' ')[0]}</p>
      <div className="balance-block">
        <div>
          <div className="balance-label">Available balance</div>
          {/* bots read this text: keep it exactly the formatted amount */}
          <div className="balance" data-kya-id="home.balance">{balance === null ? '…' : formatPaise(balance)}</div>
          <div className="account-line">Savings account {account && `ending ${account.replace(/\D/g, '').padStart(4, '0').slice(-4)}`}</div>
        </div>
        <div className="quick">
          <button data-kya-id="home.send" onClick={() => navigate('/transfer')}>Send money</button>
          <button className="secondary" data-kya-id="home.pay" onClick={() => navigate('/merchant')}>Pay a bill</button>
          <button className="secondary" data-kya-id="home.add_payee" onClick={() => navigate('/payees')}>Add a payee</button>
        </div>
      </div>

      <div className="panel passbook" data-kya-id="home.recent">
        <h2>Recent activity</h2>
        {rows === null ? <p className="empty">Loading…</p> : <Passbook rows={rows} />}
      </div>
    </div>
  )
}
