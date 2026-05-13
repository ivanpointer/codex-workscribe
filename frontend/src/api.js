const jsonHeaders = {
  Accept: 'application/json',
}

async function requestJson(path, params = {}) {
  const url = new URL(path, window.location.origin)

  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value)
    }
  }

  const response = await fetch(url, { headers: jsonHeaders })
  const payload = await response.json().catch(() => ({}))

  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`)
  }

  return payload
}

export function getMeta() {
  return requestJson('/api/meta')
}

export function getTables() {
  return requestJson('/api/tables')
}

export function getTableRows(table, options = {}) {
  const { filters = {}, ...params } = options
  const query = { ...params }

  for (const [column, value] of Object.entries(filters)) {
    query[`filter_${column}`] = value
  }

  return requestJson(`/api/tables/${encodeURIComponent(table)}/rows`, query)
}

export function getRowDetail(table, id) {
  return requestJson(`/api/tables/${encodeURIComponent(table)}/rows/${encodeURIComponent(id)}`)
}
