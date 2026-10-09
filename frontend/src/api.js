async function request(path, options) {
  let res
  try {
    res = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new Error('Não foi possível conectar ao servidor. O backend está rodando?')
  }
  if (!res.ok) {
    let detail = `Erro ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = 'Requisição inválida.'
    } catch {
      /* corpo sem JSON */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const searchSongs = (query) =>
  request('/api/search', { method: 'POST', body: JSON.stringify({ query }) })

export const createKaraokeJob = (videoId, title, artist) =>
  request('/api/jobs', {
    method: 'POST',
    body: JSON.stringify({ video_id: videoId, title, artist }),
  })

export const getJob = (jobId) => request(`/api/jobs/${jobId}`)
