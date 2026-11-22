import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatPaise, rupeesToPaise } from '../money.js'
import { flushTelemetry } from '../telemetry.js'
import { outcome } from '../decision.js'

export default function Transfer() {
  const [payees, setPayees] = useState([])
  const [payeeId, setPayeeId] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('') // shown to the user only, never sent or stored
  const [msg, setMsg] = useState({ ok: '', error: '' })

  useEffect(() => {
    api('GET', '/api/payees').then((d) => setPayees(d.payees)).catch(() => {})
  }, [])

  async function submit(e) {
    e.preventDefault()
    setMsg({ ok: '', error: '' })
    const paise = rupeesToPaise(amount)
    if (!payeeId) return setMsg({ ok: '', error: 'Choose a payee' })
    if (!paise) return setMsg({ ok: '', error: 'Enter an amount like 2500 or 2500.50' })
    try {
      await flushTelemetry()
      const d = await api('POST', '/api/transfer', { payee_id: payeeId, amount_paise: paise, currency: 'INR' })
      setMsg(outcome(d, `Sent ${formatPaise(paise)}. New balance ${formatPaise(d.balance_paise)}`))
      if (d.status === 'executed') { setAmount(''); setNote('') }
    } catch (err) {
      setMsg({ ok: '', error: err.message })
    }
  }

  return (
    <div data-kya-page="transfer">
      <div className="card">
        <h2>Send money</h2>
        <form data-kya-id="transfer.form" onSubmit={submit}>
          <label htmlFor="tpayee">To</label>
          <select id="tpayee" data-kya-id="transfer.payee" value={payeeId} onChange={(e) => setPayeeId(e.target.value)}>
            <option value="">Choose a payee</option>
            {payees.map((p) => <option key={p.payee_id} value={p.payee_id}>{p.name}</option>)}
          </select>
          <label htmlFor="tamount">Amount (₹)</label>
          <input id="tamount" data-kya-id="transfer.amount" inputMode="decimal" value={amount}
                 onChange={(e) => setAmount(e.target.value)} />
          <label htmlFor="tnote">Note (optional)</label>
          <input id="tnote" data-kya-id="transfer.note" value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="submit" data-kya-id="transfer.submit">Send</button>
          {msg.ok && <p className="ok">{msg.ok}</p>}
          {msg.error && <p className="error">{msg.error}</p>}
        </form>
      </div>
    </div>
  )
}
