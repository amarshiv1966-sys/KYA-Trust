import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatPaise } from '../money.js'
import { flushTelemetry } from '../telemetry.js'
import { PageHeader, categoryName, describe } from '../ui.jsx'

export default function Statements() {
  const [range, setRange] = useState('30')
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')

  // show the last 30 days straight away; View reloads for the chosen period
  useEffect(() => { view() }, [])

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

  const totals = (rows || []).reduce((t, r) => {
    if (r.amount_paise > 0) t.in += r.amount_paise; else t.out -= r.amount_paise
    return t
  }, { in: 0, out: 0 })

  return (
    <div data-kya-page="statements">
      <PageHeader title="Statements">Every payment in and out of your savings account.</PageHeader>
      <div className="panel">
        <div className="controls">
          <div>
            <label htmlFor="range">Period</label>
            <select id="range" data-kya-id="statements.range" value={range} onChange={(e) => setRange(e.target.value)}>
              <option value="30">Last 30 days</option>
              <option value="60">Last 60 days</option>
              <option value="90">Last 90 days</option>
            </select>
          </div>
          <button data-kya-id="statements.view" onClick={view}>Show</button>
          <button className="secondary" data-kya-id="statements.download" onClick={download}>Download CSV</button>
        </div>
        {error && <p className="notice error">{error}</p>}
        {rows && (
          <p className="summary">
            {rows.length} transactions. Money in <strong className="money in">{formatPaise(totals.in)}</strong>,
            money out <strong className="money">{formatPaise(totals.out)}</strong>.
          </p>
        )}
      </div>
      {rows && (
        <div className="panel">
          {rows.length === 0 ? <p className="empty">No money moved in this period.</p> : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr><th>Date</th><th>Description</th><th className="num">Money out</th><th className="num">Money in</th><th className="num">Balance</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.txn_id}>
                      <td className="money">{new Date(r.ts_ms).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</td>
                      <td>{r.name}<div className="what">{r.action === 'credit' ? 'Money received' : r.category ? categoryName(r.category) : describe(r)}</div></td>
                      <td className="num">{r.amount_paise < 0 ? formatPaise(-r.amount_paise) : ''}</td>
                      <td className="num in">{r.amount_paise > 0 ? formatPaise(r.amount_paise) : ''}</td>
                      <td className="num">{formatPaise(r.balance_after)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
