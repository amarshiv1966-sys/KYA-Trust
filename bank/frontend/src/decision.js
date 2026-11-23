// Turns the gate's answer into one line for the customer. Every sensitive
// action (transfer, merchant payment, add payee) now returns
// { status, decision, ... } where status is executed, step_up, held or blocked.

export function outcome(d, doneText) {
  const why = d.decision?.reason_codes?.[0]?.text
  const trust = d.decision?.trust_score
  const tail = trust == null ? '' : ` (trust ${trust}/100${why ? `: ${why}` : ''})`
  switch (d.status) {
    case 'executed':
      return { ok: doneText + (trust == null ? '' : ` · trust ${trust}/100`), error: '' }
    case 'step_up':
      return { ok: '', tone: 'warn', error: 'This needs an extra check before it can go through. Nothing has been sent yet' + tail }
    case 'held':
      return { ok: '', tone: 'warn', error: 'Held for review. Nothing has been sent' + tail }
    case 'blocked':
      return { ok: '', error: 'Blocked. Nothing has been sent' + tail }
    default:
      return { ok: '', error: `Unexpected answer from the bank (${d.status})` }
  }
}
