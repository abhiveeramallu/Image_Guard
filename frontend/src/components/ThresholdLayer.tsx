import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { fetchThresholdLayer, isCancelled } from '../services/api'
import type { MethodId } from '../types/api'

/** Re-applies a threshold on the server's stored score map and draws the resulting mask over the original. */
export default function ThresholdLayer({ analysisId, method, originalUrl, initial, semantics }: {
  analysisId: string; method: MethodId; originalUrl: string; initial: number; semantics: string | null
}) {
  const [t, setT] = useState(initial)
  const [layerUrl, setLayerUrl] = useState<string | null>(null)
  const [count, setCount] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const current = useRef<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    const timer = setTimeout(async () => {
      setBusy(true); setError(null)
      try {
        const { blob, regionCount } = await fetchThresholdLayer(analysisId, method, t, ctl.signal)
        const url = URL.createObjectURL(blob)
        if (current.current) URL.revokeObjectURL(current.current)
        current.current = url
        setLayerUrl(url); setCount(regionCount)
      } catch (e) {
        if (!isCancelled(e)) setError((e as Error).message)
      } finally { if (!ctl.signal.aborted) setBusy(false) }
    }, 250)
    return () => { clearTimeout(timer); ctl.abort() }
  }, [analysisId, method, t])
  useEffect(() => () => { if (current.current) URL.revokeObjectURL(current.current) }, [])

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-4">
        <label htmlFor={`thr-${method}`} className="label !mb-0">Visualization threshold</label>
        <input id={`thr-${method}`} type="range" min={0.05} max={0.95} step={0.05} value={t} onChange={(e) => setT(Number(e.target.value))} />
        <span className="text-sm tabular-nums">{t.toFixed(2)}</span>
        {busy && <Loader2 size={14} className="animate-spin text-slate-500" aria-label="Updating" />}
        {count !== null && !busy && <span className="text-xs text-slate-600">{count} region{count === 1 ? '' : 's'} at this threshold</span>}
      </div>
      {semantics && <p className="mb-2 text-xs text-slate-500">Threshold meaning: {semantics}.</p>}
      {error && <p role="alert" className="mb-2 text-sm text-red-700">{error}</p>}
      <div className="checker relative max-h-[70vh] overflow-auto rounded-lg border border-slate-200">
        <img src={originalUrl} alt="Original for threshold view" className="block h-auto w-full" />
        {layerUrl && <img src={layerUrl} alt="Threshold mask layer" className="pointer-events-none absolute inset-0 h-full w-full" />}
      </div>
    </div>
  )
}
