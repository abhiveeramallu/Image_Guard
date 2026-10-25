import { useState } from 'react'
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react'

/** Image viewer with zoom buttons; the container scrolls when zoomed beyond 100%. */
export default function ZoomableImage({ src, alt, className = '' }: { src: string; alt: string; className?: string }) {
  const [zoom, setZoom] = useState(1)
  const set = (z: number) => setZoom(Math.min(8, Math.max(1, z)))
  return (
    <div className={`relative ${className}`}>
      <div className="absolute right-2 top-2 z-10 flex gap-1 rounded-lg bg-ink-900/85 p-1 text-white">
        <button className="rounded p-1.5 hover:bg-ink-700" aria-label="Zoom out" onClick={() => set(zoom / 1.5)}><ZoomOut size={16} /></button>
        <span className="min-w-10 self-center text-center text-xs tabular-nums" aria-live="polite">{Math.round(zoom * 100)}%</span>
        <button className="rounded p-1.5 hover:bg-ink-700" aria-label="Zoom in" onClick={() => set(zoom * 1.5)}><ZoomIn size={16} /></button>
        <button className="rounded p-1.5 hover:bg-ink-700" aria-label="Reset zoom" onClick={() => set(1)}><Maximize2 size={16} /></button>
      </div>
      <div className="checker max-h-[70vh] overflow-auto rounded-lg border border-slate-200">
        <img src={src} alt={alt} style={{ width: `${zoom * 100}%`, maxWidth: 'none' }} className="block h-auto" />
      </div>
    </div>
  )
}
