import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { flushTelemetry } from '../telemetry.js'
import { outcome } from '../decision.js'
import { Avatar, Notice, PageHeader } from '../ui.jsx'

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
      <PageHeader title="Payees">People you send money to. Add someone once, then pay them from Send money.</PageHeader>
      <div className="split">
        <div className="panel" data-kya-id="payees.list">
          <h2>Saved payees</h2>
          {payees.length === 0 && <p className="empty">You have no saved payees yet.</p>}
          {payees.map((p) => (
            <div className="payee" key={p.payee_id}>
              <Avatar name={p.name} />
              <div>
                <div style={{ fontWeight: 600 }}>{p.name}</div>
                <div className="meta">IFSC {p.ifsc}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="panel">
          <h2>Add a payee</h2>
          <form data-kya-id="payees.form" onSubmit={submit}>
            <label htmlFor="pname">Name</label>
            <input id="pname" data-kya-id="payees.name" value={name} onChange={(e) => setName(e.target.value)}
                   autoComplete="off" />
            <label htmlFor="pacc">Account number
              <span className="field-hint">9 to 18 digits, as on their cheque book</span>
            </label>
            <input id="pacc" data-kya-id="payees.account" inputMode="numeric" value={account}
                   onChange={(e) => setAccount(e.target.value)} autoComplete="off" />
            <label htmlFor="pifsc">IFSC
              <span className="field-hint">11 characters, for example KYAB0001234</span>
            </label>
            <input id="pifsc" data-kya-id="payees.ifsc" value={ifsc} onChange={(e) => setIfsc(e.target.value)}
                   autoComplete="off" />
            <div className="actions">
              <button type="submit" data-kya-id="payees.submit">Add payee</button>
            </div>
            <Notice msg={msg} />
          </form>
        </div>
      </div>
    </div>
  )
}
