export interface SegmentOption<T extends string> { value: T; label: string; disabled?: boolean }

export default function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: SegmentOption<T>[]; onChange: (v: T) => void; label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-lg bg-slate-200/70 p-1">
      {options.map((o) => (
        <button
          key={o.value} role="tab" aria-selected={value === o.value} disabled={o.disabled}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition disabled:opacity-40 ${
            value === o.value ? 'bg-white text-ink-900 shadow-sm' : 'text-slate-600 hover:text-ink-900'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
