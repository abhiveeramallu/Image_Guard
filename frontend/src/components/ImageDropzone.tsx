import { useRef, useState, type DragEvent } from 'react'
import { UploadCloud } from 'lucide-react'
import { ACCEPT_ATTR } from '../utils/files'

export default function ImageDropzone({ onFile, error, disabled, label = 'Drag & drop an image here' }: {
  onFile: (f: File) => void; error?: string | null; disabled?: boolean; label?: string
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  const drop = (e: DragEvent) => {
    e.preventDefault(); setOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f && !disabled) onFile(f)
  }
  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={drop}
        className={`flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition ${
          over ? 'border-accent-500 bg-accent-500/5' : 'border-slate-300 bg-white'}`}
      >
        <UploadCloud size={36} className="text-accent-600" aria-hidden />
        <div>
          <p className="font-semibold text-slate-800">{label}</p>
          <p className="mt-1 text-sm text-slate-500">JPEG or PNG, up to 10 MB</p>
        </div>
        <button type="button" className="btn-primary" disabled={disabled} onClick={() => input.current?.click()}>
          Choose file
        </button>
        <input
          ref={input} type="file" accept={ACCEPT_ATTR} className="sr-only" aria-label="Upload image" data-testid="file-input"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }}
        />
      </div>
      {error && <p role="alert" className="mt-2 text-sm font-medium text-red-700">{error}</p>}
    </div>
  )
}
