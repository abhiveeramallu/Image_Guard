import { RefreshCw, Trash2 } from 'lucide-react'
import type { LoadedImage } from '../hooks/useImageFile'
import { formatBytes } from '../utils/files'

export default function ImageSummary({ image, onReplace, onRemove, disabled }: {
  image: LoadedImage; onReplace: (f: File) => void; onRemove: () => void; disabled?: boolean
}) {
  return (
    <div className="card flex flex-col gap-4 p-4 sm:flex-row sm:items-center">
      <div className="checker flex h-28 w-full shrink-0 items-center justify-center overflow-hidden rounded-lg sm:w-40">
        <img src={image.url} alt="Uploaded preview" className="max-h-28 max-w-full object-contain" />
      </div>
      <dl className="grid min-w-0 flex-1 grid-cols-3 gap-x-4 gap-y-1 text-sm">
        <dt className="col-span-3 truncate font-semibold text-slate-800" title={image.file.name}>{image.file.name}</dt>
        <div><dt className="label !mb-0">Dimensions</dt><dd>{image.width} × {image.height}</dd></div>
        <div><dt className="label !mb-0">Size</dt><dd>{formatBytes(image.file.size)}</dd></div>
        <div><dt className="label !mb-0">Type</dt><dd>{image.file.type || 'image'}</dd></div>
      </dl>
      <div className="flex gap-2">
        <label className={`btn-secondary cursor-pointer ${disabled ? 'pointer-events-none opacity-50' : ''}`}>
          <RefreshCw size={16} aria-hidden /> Replace
          <input type="file" accept="image/jpeg,image/png" className="sr-only" aria-label="Replace image" disabled={disabled}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) onReplace(f); e.target.value = '' }} />
        </label>
        <button className="btn-secondary" onClick={onRemove} disabled={disabled}><Trash2 size={16} aria-hidden /> Remove</button>
      </div>
    </div>
  )
}
