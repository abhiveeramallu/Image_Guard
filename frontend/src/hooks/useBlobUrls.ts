import { useEffect, useRef, useState } from 'react'

/** Turns a record of blobs into object URLs and revokes the previous set whenever the blobs change. */
export function useBlobUrls<K extends string>(blobs: Partial<Record<K, Blob>> | null): Partial<Record<K, string>> {
  const [urls, setUrls] = useState<Partial<Record<K, string>>>({})
  const prev = useRef<string[]>([])
  useEffect(() => {
    prev.current.forEach((u) => URL.revokeObjectURL(u))
    const next: Partial<Record<K, string>> = {}
    prev.current = []
    if (blobs) {
      for (const k of Object.keys(blobs) as K[]) {
        const b = blobs[k]
        if (b) { const u = URL.createObjectURL(b); next[k] = u; prev.current.push(u) }
      }
    }
    setUrls(next)
  }, [blobs])
  useEffect(() => () => prev.current.forEach((u) => URL.revokeObjectURL(u)), [])
  return urls
}
