import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { flushTelemetry } from '../telemetry.js'
import { outcome } from '../decision.js'

export default function Payees() {
  const [payees, setPayees] = useState([])
  const [name, setName] = useState('')
  const [account, setAccount] = useState('')
  const [ifsc, setIfsc] = useState('')
  const [msg, setMsg] = useState({ ok: '', error: '' })

  function load() {
    api('GET', '/api/payees').then((d) => setPayees(d.payees)).catch(() => {})
  }
  useEffect(load, [])

  async function submit(e) {
    e.preventDefault()
    setMsg({ ok: '', error: '' })
    try {
      await flushTelemetry()
      const d = await api('POST', '/api/payees', {
        name, account_number: account, ifsc: ifsc.toUpperCase(),
      })
      setMsg(outcome(d, `Payee added (${d.payee_id})`))
      if (d.status === 'executed') { setName(''); setAccount(''); setIfsc(''); load() }
    } catch (err) {
      setMsg({ ok: '', error: err.message })
    }
  }

  return (
    <div data-kya-page="payees">
      <div className="card" data-kya-id="payees.list">
        <h2>Your payees</h2>
        <table>
          <tbody>
            {payees.map((p) => <tr key={p.payee_id}><td>{p.name}</td><td>{p.ifsc}</td><td>{p.payee_id}</td></tr>)}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h3>Add a payee</h3>
        <form data-kya-id="payees.form" onSubmit={submit}>
          <label htmlFor="pname">Name</label>
          <input id="pname" data-kya-id="payees.name" value={name} onChange={(e) => setName(e.target.value)} />
          <label htmlFor="pacc">Account number</label>
          <input id="pacc" data-kya-id="payees.account" inputMode="numeric" value={account}
                 onChange={(e) => setAccount(e.target.value)} />
          <label htmlFor="pifsc">IFSC</label>
          <input id="pifsc" data-kya-id="payees.ifsc" value={ifsc} onChange={(e) => setIfsc(e.target.value)}
                 placeholder="KYAB0001234" />
          <button type="submit" data-kya-id="payees.submit">Add payee</button>
          {msg.ok && <p className="ok">{msg.ok}</p>}
          {msg.error && <p className="error">{msg.error}</p>}
        </form>
      </div>
    </div>
  )
}
