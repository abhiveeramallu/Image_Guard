import { RotateCcw } from 'lucide-react'
import { DEFAULT_DETECTION_SETTINGS, type DetectionSettings } from '../types/api'
import { SliderField } from './FormFields'

export default function DetectionSettingsPanel({ value, onChange, disabled }: {
  value: DetectionSettings; onChange: (v: DetectionSettings) => void; disabled?: boolean
}) {
  const set = <K extends keyof DetectionSettings>(k: K, v: DetectionSettings[K]) => onChange({ ...value, [k]: v })
  return (
    <details className="card p-4" open>
      <summary className="cursor-pointer text-sm font-semibold text-slate-800">Detection settings</summary>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <SliderField label="Analysis size (max px)" value={value.max_dimension} min={256} max={3000} step={64} disabled={disabled}
          onChange={(v) => set('max_dimension', v)} />
        <SliderField label="ORB keypoint budget" value={value.n_features} min={500} max={20000} step={500} disabled={disabled}
          onChange={(v) => set('n_features', v)} />
        <SliderField label="Match ratio (lower = stricter)" value={value.ratio} min={0.5} max={0.95} step={0.01} disabled={disabled}
          onChange={(v) => set('ratio', v)} />
        <SliderField label="Minimum matches per region" value={value.min_matches} min={4} max={60} disabled={disabled}
          onChange={(v) => set('min_matches', v)} />
        <SliderField label="Minimum copy distance (px)" value={value.min_displacement} min={4} max={200} disabled={disabled}
          onChange={(v) => set('min_displacement', v)} />
        <div className="flex items-end">
          <button className="btn-secondary" disabled={disabled} onClick={() => onChange(DEFAULT_DETECTION_SETTINGS)}>
            <RotateCcw size={16} aria-hidden /> Reset defaults
          </button>
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Stricter settings reduce false alarms but can miss real duplications. Defaults were chosen on synthetic test images only.
      </p>
    </details>
  )
}
