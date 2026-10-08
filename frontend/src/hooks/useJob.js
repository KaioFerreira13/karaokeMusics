import { useEffect, useState } from 'react'
import { getJob } from '../api'

const POLL_MS = 1500
const FINAL = ['completed', 'failed']

/** Faz polling de /api/jobs/{id} até o job terminar (completed/failed). */
export function useJob(jobId) {
  const [job, setJob] = useState(null)
  const [connectionError, setConnectionError] = useState(null)

  useEffect(() => {
    if (!jobId) return undefined
    let cancelled = false
    let timer

    const tick = async () => {
      try {
        const next = await getJob(jobId)
        if (cancelled) return
        setJob(next)
        setConnectionError(null)
        if (FINAL.includes(next.status)) return
      } catch (err) {
        if (cancelled) return
        setConnectionError(err.message) // tenta de novo no próximo ciclo
      }
      timer = setTimeout(tick, POLL_MS)
    }
    tick()

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [jobId])

  return { job: jobId ? job : null, connectionError }
}
