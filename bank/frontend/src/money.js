// Money is integer paise everywhere. Convert rupee text like "2,500.50"
// without floating point, so 0.1 + 0.2 problems can never reach the bank.

export function rupeesToPaise(text) {
  const clean = String(text).replace(/,/g, '').trim()
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  const [whole, frac = ''] = clean.split('.')
  return Number(whole) * 100 + Number(frac.padEnd(2, '0'))
}

export function formatPaise(paise) {
  const sign = paise < 0 ? '-' : ''
  const abs = Math.abs(paise)
  const rupees = Math.floor(abs / 100).toLocaleString('en-IN')
  const p = String(abs % 100).padStart(2, '0')
  return `${sign}₹${rupees}.${p}`
}
