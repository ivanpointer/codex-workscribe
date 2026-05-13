async function requestJson(path) {
  const response = await fetch(path)
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`)
  }
  return payload
}

export function fetchMeta() {
  return requestJson('/api/meta')
}

export function fetchTables() {
  return requestJson('/api/tables')
}

export function fetchRows({ table, limit, offset, sort, direction, search, filters }) {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  if (sort) params.set('sort', sort)
  if (direction) params.set('direction', direction)
  if (search) params.set('search', search)
  for (const [key, value] of Object.entries(filters || {})) {
    if (value) params.set(`filter_${key}`, value)
  }
  return requestJson(`/api/tables/${encodeURIComponent(table)}/rows?${params.toString()}`)
}

export function fetchRowDetail(table, id) {
  return requestJson(`/api/tables/${encodeURIComponent(table)}/rows/${encodeURIComponent(id)}`)
}
