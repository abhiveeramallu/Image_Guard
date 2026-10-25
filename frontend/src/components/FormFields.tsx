import type { ReactNode } from 'react'

export function SliderField({ label, value, min, max, step = 1, unit = '', onChange, disabled }: {
  label: string; value: number; min: number; max: number; step?: number; unit?: string
  onChange: (v: number) => void; disabled?: boolean
}) {
  const id = `f-${label.replace(/\W+/g, '-').toLowerCase()}`
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="label">{label}</label>
        <span className="text-xs tabular-nums text-slate-600">{value}{unit}</span>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-accent-600" />
    </div>
  )
}

export function Field({ label, htmlFor, children }: { label: string; htmlFor?: string; children: ReactNode }) {
  return <div><label htmlFor={htmlFor} className="label">{label}</label>{children}</div>
}
