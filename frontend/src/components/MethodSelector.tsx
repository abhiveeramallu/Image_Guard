import { FlaskConical } from 'lucide-react'
import type { Capabilities, MethodId } from '../types/api'

const META: Record<MethodId, { label: string; blurb: string; experimental?: boolean }> = {
  copy_move: { label: 'Copy-move detection', blurb: 'ORB feature matching; finds regions duplicated within the image.' },
  splicing: { label: 'Splicing heuristic', blurb: 'Noise / error-level inconsistencies. Not a trained or validated detector.', experimental: true },
  localization: { label: 'Model-based localization', blurb: 'Pixel-level manipulation probability map from a configured ONNX model.' },
}
const ORDER: MethodId[] = ['copy_move', 'splicing', 'localization']

export default function MethodSelector({ caps, error, loading, selected, onChange, disabled }: {
  caps: Capabilities | null; error: string | null; loading: boolean
  selected: MethodId[]; onChange: (m: MethodId[]) => void; disabled?: boolean
}) {
  const state = (m: MethodId): { enabled: boolean; note: string | null } => {
    if (m === 'copy_move') return { enabled: true, note: null }
    if (!caps) return { enabled: false, note: loading ? 'Checking server capabilities…' : `Unavailable: ${error ?? 'capabilities unknown'}` }
    const c = caps.methods[m]
    return { enabled: c.available, note: c.available ? null : `Unavailable: ${c.reason ?? 'not configured'}` }
  }
  const available = ORDER.filter((m) => state(m).enabled)
  const toggle = (m: MethodId) => {
    const next = selected.includes(m) ? selected.filter((x) => x !== m) : [...selected, m]
    onChange(ORDER.filter((x) => next.includes(x)))
  }
  const all = available.length > 1 && available.every((m) => selected.includes(m))
  return (
    <fieldset className="card p-4" disabled={disabled}>
      <legend className="sr-only">Detection methods</legend>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-800">Detection methods</h2>
        <button type="button" className="text-xs font-semibold text-accent-700 hover:underline disabled:opacity-40"
          disabled={available.length < 2 || disabled} onClick={() => onChange(all ? ['copy_move'] : available)}>
          {all ? 'Copy-move only' : 'All supported methods'}
        </button>
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        {ORDER.map((m) => {
          const { enabled, note } = state(m)
          const id = `method-${m}`
          return (
            <label key={m} htmlFor={id}
              className={`flex cursor-pointer gap-3 rounded-lg border p-3 text-sm ${enabled ? 'border-slate-200 hover:border-accent-500' : 'cursor-not-allowed border-dashed border-slate-300 bg-slate-50 text-slate-500'}`}>
              <input id={id} type="checkbox" className="mt-1" checked={selected.includes(m)} disabled={!enabled}
                onChange={() => toggle(m)} />
              <span>
                <span className="flex flex-wrap items-center gap-2 font-semibold text-slate-800">
                  {META[m].label}
                  {META[m].experimental && (
                    <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-amber-800">
                      <FlaskConical size={10} aria-hidden /> Experimental
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block text-xs text-slate-600">{META[m].blurb}</span>
                {note && <span className="mt-1 block text-xs font-medium text-amber-700">{note}</span>}
                {m === 'localization' && caps?.methods.localization.model && (
                  <span className="mt-1 block text-xs text-slate-500">Model: {caps.methods.localization.model.name} v{caps.methods.localization.model.version}</span>
                )}
              </span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
