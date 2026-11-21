import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatPaise } from '../money.js'

export default function Home({ onExpired }) {
  const [balance, setBalance] = useState(null)
  const [rows, setRows] = useState([])

  useEffect(() => {
    api('GET', '/api/balance').then((d) => setBalance(d.balance_paise)).catch(onExpired)
    api('GET', '/api/statements?range=30').then((d) => setRows(d.rows.slice(0, 5))).catch(() => {})
  }, [])

  return (
    <div data-kya-page="home">
      <div className="card">
        <div>Available balance</div>
        <div className="balance" data-kya-id="home.balance">
          {balance === null ? '…' : formatPaise(balance)}
        </div>
      </div>
      <div className="card" data-kya-id="home.recent">
        <h3>Recent payments</h3>
        {rows.length === 0 ? <p>No payments in the last 30 days.</p> : (
          <table>
            <tbody>
              {rows.map((r) => (
                <tr key={r.txn_id}>
                  <td>{new Date(r.ts_ms).toLocaleString('en-IN')}</td>
                  <td>{r.counterparty}</td>
                  <td className={r.amount_paise < 0 ? 'neg' : ''}>{formatPaise(r.amount_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
