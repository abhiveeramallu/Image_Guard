import { useEffect, useState } from 'react'
import { getCapabilities } from '../services/api'
import type { Capabilities } from '../types/api'

/** Loads what the server can actually do. `error` is set when the server cannot be reached. */
export function useCapabilities() {
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const ctl = new AbortController()
    getCapabilities(ctl.signal)
      .then((c) => { setCaps(c); setError(null) })
      .catch((e: Error) => { if ((e as { code?: string }).code !== 'cancelled') setError(e.message) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [])
  return { caps, error, loading }
}
