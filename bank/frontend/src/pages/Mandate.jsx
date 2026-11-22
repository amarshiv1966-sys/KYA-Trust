import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatPaise, rupeesToPaise } from '../money.js'
import { flushTelemetry } from '../telemetry.js'

// "Assistants": the customer gives one registered agent a limited permission
// (a mandate). The bank signs it; the agent can use it but never widen it.

function selected(e) {
  return Array.from(e.target.selectedOptions, (o) => o.value)
}

export default function Mandate() {
  const [agents, setAgents] = useState([])
  const [merchants, setMerchants] = useState([])
  const [payees, setPayees] = useState([])
  const [mandates, setMandates] = useState([])
  const [form, setForm] = useState({ agent: '', categories: [], payees: [], perTxn: '', total: '', perDay: '3', days: '7' })
  const [issued, setIssued] = useState(null)
  const [msg, setMsg] = useState({ ok: '', error: '' })

  function load() {
    api('GET', '/api/mandates').then((d) => setMandates(d.mandates)).catch(() => {})
  }

  useEffect(() => {
    api('GET', '/api/agents').then((d) => setAgents(d.agents)).catch(() => {})
    api('GET', '/api/merchants').then((d) => setMerchants(d.merchants)).catch(() => {})
    api('GET', '/api/payees').then((d) => setPayees(d.payees)).catch(() => {})
    load()
  }, [])

  const categories = [...new Set(merchants.map((m) => m.category))].sort()
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    setMsg({ ok: '', error: '' })
    setIssued(null)
    const perTxn = rupeesToPaise(form.perTxn)
    const total = rupeesToPaise(form.total)
    if (!form.agent) return setMsg({ ok: '', error: 'Choose an assistant' })
    if (!form.categories.length && !form.payees.length) return setMsg({ ok: '', error: 'Choose at least one category or payee' })
    if (!perTxn || !total) return setMsg({ ok: '', error: 'Enter both limits in rupees' })
    try {
      await flushTelemetry()
      const d = await api('POST', '/api/mandates', {
        agent_id: form.agent,
        merchant_categories: form.categories,
        payees: form.payees,
        max_per_txn_paise: perTxn,
        max_total_paise: total,
        max_txn_per_day: parseInt(form.perDay, 10),
        expiry_days: parseInt(form.days, 10),
      })
      setIssued(d)
      setMsg({ ok: `Permission ${d.mandate_id} given to ${form.agent}`, error: '' })
      load()
    } catch (err) {
      setMsg({ ok: '', error: err.message })
    }
  }

  async function revoke(id) {
    try {
      await flushTelemetry()
      await api('POST', `/api/mandates/${id}/revoke`)
      load()
    } catch (err) {
      setMsg({ ok: '', error: err.message })
    }
  }

  return (
    <div data-kya-page="mandate">
      <div className="card">
        <h2>Give an assistant permission</h2>
        <p className="muted">The assistant can only pay inside these limits. You can take the permission back at any time.</p>
        <form data-kya-id="mandate.form" onSubmit={submit}>
          <label htmlFor="magent">Assistant</label>
          <select id="magent" data-kya-id="mandate.agent" value={form.agent} onChange={set('agent')}>
            <option value="">Choose an assistant</option>
            {agents.map((a) => <option key={a.agent_id} value={a.agent_id}>{a.agent_id} ({a.issuer})</option>)}
          </select>

          <label htmlFor="mcats">May pay merchants in these categories (Ctrl-click for several)</label>
          <select id="mcats" multiple size={5} data-kya-id="mandate.categories" value={form.categories}
                  onChange={(e) => setForm({ ...form, categories: selected(e) })}>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>

          <label htmlFor="mpayees">Only these payees (leave empty for any in the categories)</label>
          <select id="mpayees" multiple size={5} data-kya-id="mandate.payees" value={form.payees}
                  onChange={(e) => setForm({ ...form, payees: selected(e) })}>
            {merchants.map((m) => <option key={m.merchant_id} value={m.merchant_id}>{m.name} ({m.category})</option>)}
            {payees.map((p) => <option key={p.payee_id} value={p.payee_id}>{p.name} (your payee)</option>)}
          </select>

          <label htmlFor="mper">Most per payment (₹)</label>
          <input id="mper" data-kya-id="mandate.max_per_txn" inputMode="decimal" value={form.perTxn} onChange={set('perTxn')} />
          <label htmlFor="mtotal">Most in total (₹)</label>
          <input id="mtotal" data-kya-id="mandate.max_total" inputMode="decimal" value={form.total} onChange={set('total')} />
          <label htmlFor="mday">Most payments per day</label>
          <input id="mday" data-kya-id="mandate.max_per_day" inputMode="numeric" value={form.perDay} onChange={set('perDay')} />
          <label htmlFor="mdays">Valid for (days)</label>
          <input id="mdays" data-kya-id="mandate.expiry_days" inputMode="numeric" value={form.days} onChange={set('days')} />

          <button type="submit" data-kya-id="mandate.submit">Give permission</button>
          {msg.ok && <p className="ok">{msg.ok}</p>}
          {msg.error && <p className="error">{msg.error}</p>}
        </form>
        {issued && (
          <div>
            <label htmlFor="mtoken">Give this to your assistant</label>
            <textarea id="mtoken" readOnly rows={4} value={issued.token} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} />
          </div>
        )}
      </div>

      <div className="card" data-kya-id="mandate.list">
        <h3>Permissions you have given</h3>
        {mandates.length === 0 && <p className="muted">None yet.</p>}
        {mandates.map((m) => (
          <div key={m.mandate_id} className="row">
            <span>
              <strong>{m.agent_id}</strong> · {m.merchant_categories.concat(m.payees).join(', ')} ·
              up to {formatPaise(m.max_per_txn_paise)} each, {formatPaise(m.consumed_paise)} of {formatPaise(m.max_total_paise)} used ·
              {' '}{m.status}
            </span>
            {m.status === 'active' && (
              <button data-kya-id={`mandate.revoke.${m.mandate_id}`} onClick={() => revoke(m.mandate_id)}>Revoke</button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
