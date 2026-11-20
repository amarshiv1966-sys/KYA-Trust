// Small wrapper around fetch for the bank API. Cookies go along automatically
// because the pages and the API share one origin (see vite.config.js).

export async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try { data = await res.json() } catch { /* CSV or empty body */ }
  if (!res.ok) {
    const msg = typeof data?.detail === 'string' ? data.detail : `request failed (${res.status})`
    throw new Error(msg)
  }
  return data
}
