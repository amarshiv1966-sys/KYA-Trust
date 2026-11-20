import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatPaise, rupeesToPaise } from '../money.js'
import { flushTelemetry } from '../telemetry.js'

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
      setMsg({ ok: `Paid ${formatPaise(paise)}. New balance ${formatPaise(d.balance_paise)}`, error: '' })
      setAmount('')
    } catch (err) {
      setMsg({ ok: '', error: err.message })
    }
  }

  return (
    <div data-kya-page="merchant">
      <div className="card">
        <h2>Pay a merchant</h2>
        <form data-kya-id="merchant.form" onSubmit={submit}>
          <label htmlFor="mmerchant">Merchant</label>
          <select id="mmerchant" data-kya-id="merchant.merchant" value={merchantId}
                  onChange={(e) => setMerchantId(e.target.value)}>
            <option value="">Choose a merchant</option>
            {merchants.map((m) => <option key={m.merchant_id} value={m.merchant_id}>{m.name} ({m.category})</option>)}
          </select>
          <label htmlFor="mamount">Amount (₹)</label>
          <input id="mamount" data-kya-id="merchant.amount" inputMode="decimal" value={amount}
                 onChange={(e) => setAmount(e.target.value)} />
          <button type="submit" data-kya-id="merchant.submit">Pay</button>
          {msg.ok && <p className="ok">{msg.ok}</p>}
          {msg.error && <p className="error">{msg.error}</p>}
        </form>
      </div>
    </div>
  )
}
