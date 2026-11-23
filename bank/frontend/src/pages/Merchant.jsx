import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatPaise, rupeesToPaise } from '../money.js'
import { flushTelemetry } from '../telemetry.js'
import { outcome } from '../decision.js'
import { Notice, PageHeader, categoryName } from '../ui.jsx'

export default function Merchant() {
  const [merchants, setMerchants] = useState([])
  const [merchantId, setMerchantId] = useState('')
  const [amount, setAmount] = useState('')
  const [msg, setMsg] = useState({ ok: '', error: '' })

  useEffect(() => {
    api('GET', '/api/merchants').then((d) => setMerchants(d.merchants)).catch(() => {})
  }, [])

  async function submit(e) {
    e.preventDefault()
    setMsg({ ok: '', error: '' })
    const paise = rupeesToPaise(amount)
    if (!merchantId) return setMsg({ ok: '', error: 'Choose a merchant' })
    if (!paise) return setMsg({ ok: '', error: 'Enter an amount like 499 or 499.00' })
    try {
      await flushTelemetry()
      const d = await api('POST', '/api/merchant/pay', { merchant_id: merchantId, amount_paise: paise, currency: 'INR' })
      setMsg(outcome(d, `Paid ${formatPaise(paise)}. New balance ${formatPaise(d.balance_paise)}`))
      if (d.status === 'executed') setAmount('')
    } catch (err) {
      setMsg({ ok: '', error: err.message })
    }
  }

  const byCategory = {}
  for (const m of merchants) (byCategory[m.category] ||= []).push(m)
  const chosen = merchants.find((m) => m.merchant_id === merchantId)
  const preview = rupeesToPaise(amount)

  return (
    <div data-kya-page="merchant">
      <PageHeader title="Pay a bill">Electricity, internet, shopping and more, paid from your savings account.</PageHeader>
      <div className="split">
        <div className="panel">
          <form data-kya-id="merchant.form" onSubmit={submit}>
            <label htmlFor="mmerchant" style={{ marginTop: 0 }}>Pay to</label>
            <select id="mmerchant" data-kya-id="merchant.merchant" value={merchantId}
                    onChange={(e) => setMerchantId(e.target.value)}>
              <option value="">Choose a biller or shop</option>
              {Object.keys(byCategory).sort().map((c) => (
                <optgroup key={c} label={categoryName(c)}>
                  {byCategory[c].map((m) => <option key={m.merchant_id} value={m.merchant_id}>{m.name}</option>)}
                </optgroup>
              ))}
            </select>
            <label htmlFor="mamount">Amount</label>
            <div className="amount-input">
              <span>₹</span>
              <input id="mamount" data-kya-id="merchant.amount" inputMode="decimal" value={amount}
                     onChange={(e) => setAmount(e.target.value)} placeholder="0" autoComplete="off" />
            </div>
            {chosen && preview ? (
              <p className="summary">You are paying <strong className="money">{formatPaise(preview)}</strong> to <strong>{chosen.name}</strong>.</p>
            ) : null}
            <div className="actions">
              <button type="submit" data-kya-id="merchant.submit">Pay</button>
            </div>
            <Notice msg={msg} />
          </form>
        </div>
        <div className="panel">
          <h2>Billers</h2>
          <p className="hint">{merchants.length} billers and shops in {Object.keys(byCategory).length} categories.</p>
          <p className="hint">Want an assistant to pay bills for you? Set its limits on the Assistants page.</p>
        </div>
      </div>
    </div>
  )
}
