import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatPaise, rupeesToPaise } from '../money.js'
import { flushTelemetry } from '../telemetry.js'
import { outcome } from '../decision.js'
import { Notice, PageHeader } from '../ui.jsx'

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

  const chosen = payees.find((p) => p.payee_id === payeeId)
  const preview = rupeesToPaise(amount)

  return (
    <div data-kya-page="transfer">
      <PageHeader title="Send money">Transfers go out from your savings account straight away.</PageHeader>
      <div className="split">
        <div className="panel">
          <form data-kya-id="transfer.form" onSubmit={submit}>
            <label htmlFor="tpayee" style={{ marginTop: 0 }}>To</label>
            <select id="tpayee" data-kya-id="transfer.payee" value={payeeId} onChange={(e) => setPayeeId(e.target.value)}>
              <option value="">Choose a payee</option>
              {payees.map((p) => <option key={p.payee_id} value={p.payee_id}>{p.name}</option>)}
            </select>
            <label htmlFor="tamount">Amount</label>
            <div className="amount-input">
              <span>₹</span>
              <input id="tamount" data-kya-id="transfer.amount" inputMode="decimal" value={amount}
                     onChange={(e) => setAmount(e.target.value)} placeholder="0" autoComplete="off" />
            </div>
            <label htmlFor="tnote">Note <span className="field-hint" style={{ display: 'inline' }}>(only you see this)</span></label>
            <input id="tnote" data-kya-id="transfer.note" value={note} onChange={(e) => setNote(e.target.value)}
                   placeholder="Rent for November" />
            {chosen && preview ? (
              <p className="summary">You are sending <strong className="money">{formatPaise(preview)}</strong> to <strong>{chosen.name}</strong>.</p>
            ) : null}
            <div className="actions">
              <button type="submit" data-kya-id="transfer.submit">Send</button>
            </div>
            <Notice msg={msg} />
          </form>
        </div>
        <div className="panel">
          <h2>Before you send</h2>
          <p className="hint">Check the name and amount. A payment that has gone out cannot be called back.</p>
          <p className="hint">Paying someone new? Add them first on the Payees page.</p>
        </div>
      </div>
    </div>
  )
}
