import { useState } from 'react'
import { api } from '../api.js'
import { formatPaise } from '../money.js'
import { flushTelemetry } from '../telemetry.js'

export default function Statements() {
  const [range, setRange] = useState('30')
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')

  async function view() {
    setError('')
    try {
      const d = await api('GET', `/api/statements?range=${range}`)
      setRows(d.rows)
    } catch (err) {
      setError(err.message)
    }
  }

  async function download() {
    await flushTelemetry() // a download is a sensitive action: behaviour first
    // the browser downloads the CSV with the session cookie attached
    window.location.href = `/api/statements/download?range=${range}`
  }

  return (
    <div data-kya-page="statements">
      <div className="card">
        <h2>Statements</h2>
        <label htmlFor="range">Period</label>
        <select id="range" data-kya-id="statements.range" value={range} onChange={(e) => setRange(e.target.value)}>
          <option value="30">Last 30 days</option>
          <option value="60">Last 60 days</option>
          <option value="90">Last 90 days</option>
        </select>
        <button data-kya-id="statements.view" onClick={view}>View</button>{' '}
        <button data-kya-id="statements.download" onClick={download}>Download CSV</button>
        {error && <p className="error">{error}</p>}
      </div>
      {rows && (
        <div className="card">
          {rows.length === 0 ? <p>No transactions in this period.</p> : (
            <table>
              <thead><tr><th>Date</th><th>To</th><th>Type</th><th>Amount</th><th>Balance</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.txn_id}>
                    <td>{new Date(r.ts_ms).toLocaleDateString('en-IN')}</td>
                    <td>{r.counterparty}</td>
                    <td>{r.action}</td>
                    <td className={r.amount_paise < 0 ? 'neg' : ''}>{formatPaise(r.amount_paise)}</td>
                    <td>{formatPaise(r.balance_after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
