import { useRef } from 'react'
import { ImagePlus, Type } from 'lucide-react'
import type { WatermarkPosition, WatermarkSettings } from '../types/api'
import { formatBytes } from '../utils/files'
import { Field, SliderField } from './FormFields'
import Segmented from './Segmented'

const POSITIONS: WatermarkPosition[] = [
  'top-left', 'top-center', 'top-right', 'middle-left', 'center', 'middle-right', 'bottom-left', 'bottom-center', 'bottom-right',
]

export default function WatermarkControls({ value, onChange, logo, onLogo, logoError, maxFont }: {
  value: WatermarkSettings; onChange: (v: WatermarkSettings) => void
  logo: File | null; onLogo: (f: File | null) => void; logoError: string | null; maxFont: number
}) {
  const set = <K extends keyof WatermarkSettings>(k: K, v: WatermarkSettings[K]) => onChange({ ...value, [k]: v })
  const logoInput = useRef<HTMLInputElement>(null)
  const isText = value.watermark_type === 'text'
  return (
    <div className="card space-y-5 p-4">
      <Segmented label="Watermark type" value={value.watermark_type} onChange={(v) => set('watermark_type', v)}
        options={[{ value: 'text', label: 'Text' }, { value: 'logo', label: 'Logo' }]} />

      {isText ? (
        <>
          <Field label="Watermark text" htmlFor="wm-text">
            <textarea id="wm-text" rows={2} maxLength={200} value={value.text} className="input"
              placeholder="e.g. © Your Name" onChange={(e) => set('text', e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Text colour" htmlFor="wm-color">
              <div className="flex items-center gap-2">
                <input id="wm-color" type="color" value={value.color} onChange={(e) => set('color', e.target.value)}
                  className="h-9 w-12 cursor-pointer rounded border border-slate-300" />
                <span className="text-sm tabular-nums text-slate-600">{value.color}</span>
              </div>
            </Field>
            <div className="space-y-2 pt-5 text-sm">
              <label className="flex items-center gap-2"><input type="checkbox" checked={value.outline} onChange={(e) => set('outline', e.target.checked)} /> Outline</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={value.shadow} onChange={(e) => set('shadow', e.target.checked)} /> Shadow</label>
            </div>
          </div>
          <SliderField label="Font size" unit=" px" value={Math.min(value.font_size, maxFont)} min={8} max={maxFont}
            onChange={(v) => set('font_size', v)} />
        </>
      ) : (
        <>
          <div>
            <span className="label">Logo file</span>
            <input ref={logoInput} type="file" accept="image/png,image/jpeg" className="sr-only" aria-label="Upload logo" data-testid="logo-input"
              onChange={(e) => { onLogo(e.target.files?.[0] ?? null); e.target.value = '' }} />
            <button className="btn-secondary" onClick={() => logoInput.current?.click()}>
              <ImagePlus size={16} aria-hidden /> {logo ? 'Replace logo' : 'Choose logo'}
            </button>
            {logo && <span className="ml-3 text-sm text-slate-600">{logo.name} ({formatBytes(logo.size)})</span>}
            {logoError && <p role="alert" className="mt-1 text-sm font-medium text-red-700">{logoError}</p>}
            <p className="mt-1 text-xs text-slate-500">PNG with transparency recommended. Max 2 MB.</p>
          </div>
          <SliderField label="Logo width" unit=" % of image" value={value.logo_scale} min={2} max={100} onChange={(v) => set('logo_scale', v)} />
        </>
      )}

      <SliderField label="Opacity" unit="%" value={Math.round(value.opacity * 100)} min={0} max={100} onChange={(v) => set('opacity', v / 100)} />
      <SliderField label="Rotation" unit="°" value={value.rotation} min={-180} max={180} onChange={(v) => set('rotation', v)} />

      <Segmented label="Layout" value={value.layout} onChange={(v) => set('layout', v)}
        options={[{ value: 'single', label: 'Single' }, { value: 'tiled', label: 'Tiled' }]} />

      {value.layout === 'single' ? (
        <>
          <div>
            <span className="label">Position</span>
            <div role="radiogroup" aria-label="Position" className="grid w-40 grid-cols-3 gap-1">
              {POSITIONS.map((p) => (
                <button key={p} role="radio" aria-checked={value.position === p} aria-label={p.replace('-', ' ')} title={p.replace('-', ' ')}
                  onClick={() => set('position', p)}
                  className={`h-9 rounded border transition ${value.position === p ? 'border-accent-600 bg-accent-500' : 'border-slate-300 bg-slate-100 hover:bg-slate-200'}`} />
              ))}
            </div>
          </div>
          <SliderField label="Margin" unit=" px" value={value.margin} min={0} max={300} onChange={(v) => set('margin', v)} />
        </>
      ) : (
        <SliderField label="Tile spacing" unit=" px" value={value.tile_spacing} min={0} max={300} onChange={(v) => set('tile_spacing', v)} />
      )}

      <Field label="Download format" htmlFor="wm-format">
        <select id="wm-format" className="input" value={value.output_format}
          onChange={(e) => set('output_format', e.target.value as WatermarkSettings['output_format'])}>
          <option value="png">PNG (lossless)</option>
          <option value="jpeg">JPEG</option>
        </select>
      </Field>
      {isText && <p className="flex items-center gap-1.5 text-xs text-slate-500"><Type size={12} aria-hidden /> Visible watermarks deter casual reuse; they can be cropped or removed and do not prove authenticity.</p>}
    </div>
  )
}
