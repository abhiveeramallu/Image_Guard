import { useCallback, useEffect, useRef, useState } from 'react'
import {
  CheckCircle2,
  Crop,
  FileImage,
  Layers,
  Move,
  RotateCcw,
  Sparkles,
  UploadCloud,
} from 'lucide-react'
import Alert from './Alert'
import { formatBytes } from '../utils/files'

export interface SplicingTestInput {
  compositeFile: File
  groundTruthFile: File
  compositePreviewUrl: string
  backgroundName: string
  donorName: string
  compositeFormat: 'png' | 'jpeg'
  isUntouchedControl?: boolean
}

interface LoadedImage {
  file: File
  img: HTMLImageElement
  url: string
  width: number
  height: number
}

interface CropRect {
  x: number
  y: number
  w: number
  h: number
}

interface PlacementRect {
  x: number
  y: number
  scale: number
}

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
const MAX_PIXELS = 16_000_000

export default function SplicingTestWorkspace({
  onRunTest,
  busy,
}: {
  onRunTest: (testInput: SplicingTestInput) => void
  busy: boolean
}) {
  const [bg, setBg] = useState<LoadedImage | null>(null)
  const [donor, setDonor] = useState<LoadedImage | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Crop from donor image
  const [crop, setCrop] = useState<CropRect>({ x: 0, y: 0, w: 100, h: 100 })
  // Placement on background canvas
  const [placement, setPlacement] = useState<PlacementRect>({ x: 20, y: 20, scale: 1.0 })

  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const patchCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const [compositeUrl, setCompositeUrl] = useState<string | null>(null)

  // Helper to load image file and create HTMLImageElement
  const loadImage = useCallback((file: File): Promise<LoadedImage> => {
    return new Promise((resolve, reject) => {
      if (!['image/jpeg', 'image/png'].includes(file.type)) {
        return reject(new Error('Only PNG and JPEG formats are supported.'))
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        return reject(new Error(`File exceeds maximum size of ${formatBytes(MAX_UPLOAD_BYTES)}.`))
      }
      const url = URL.createObjectURL(file)
      const img = new Image()
      img.onload = () => {
        if (img.naturalWidth * img.naturalHeight > MAX_PIXELS) {
          URL.revokeObjectURL(url)
          return reject(new Error('Image exceeds the 16 megapixel limit.'))
        }
        resolve({
          file,
          img,
          url,
          width: img.naturalWidth,
          height: img.naturalHeight,
        })
      }
      img.onerror = () => {
        URL.revokeObjectURL(url)
        reject(new Error('Failed to decode image.'))
      }
      img.src = url
    })
  }, [])

  const handleBgUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null)
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const loaded = await loadImage(file)
      setBg((prev) => {
        if (prev) URL.revokeObjectURL(prev.url)
        return loaded
      })
      // Position donor patch near center of background
      setPlacement((p) => ({
        ...p,
        x: Math.max(10, Math.round(loaded.width * 0.2)),
        y: Math.max(10, Math.round(loaded.height * 0.2)),
      }))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const handleDonorUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null)
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const loaded = await loadImage(file)
      setDonor((prev) => {
        if (prev) URL.revokeObjectURL(prev.url)
        return loaded
      })
      // Default crop: center 40% of donor
      const cw = Math.max(32, Math.round(loaded.width * 0.4))
      const ch = Math.max(32, Math.round(loaded.height * 0.4))
      const cx = Math.max(0, Math.round((loaded.width - cw) / 2))
      const cy = Math.max(0, Math.round((loaded.height - ch) / 2))
      setCrop({ x: cx, y: cy, w: cw, h: ch })
    } catch (err) {
      setError((err as Error).message)
    }
  }

  // Cleanup object URLs on unmount
  useEffect(() => {
    return () => {
      if (bg) URL.revokeObjectURL(bg.url)
      if (donor) URL.revokeObjectURL(donor.url)
      if (compositeUrl) URL.revokeObjectURL(compositeUrl)
    }
  }, [bg, donor, compositeUrl])

  // Destination width & height on the background
  const destWidth = Math.round(crop.w * placement.scale)
  const destHeight = Math.round(crop.h * placement.scale)

  // Clamp crop values when donor changes
  useEffect(() => {
    if (!donor) return
    setCrop((c) => {
      const w = Math.min(Math.max(16, c.w), donor.width)
      const h = Math.min(Math.max(16, c.h), donor.height)
      const x = Math.min(Math.max(0, c.x), donor.width - w)
      const y = Math.min(Math.max(0, c.y), donor.height - h)
      return { x, y, w, h }
    })
  }, [donor])

  // Clamp placement coordinates when background or crop size changes
  useEffect(() => {
    if (!bg) return
    setPlacement((p) => {
      const dw = Math.round(crop.w * p.scale)
      const dh = Math.round(crop.h * p.scale)
      const maxX = Math.max(0, bg.width - dw)
      const maxY = Math.max(0, bg.height - dh)
      const x = Math.min(Math.max(0, p.x), maxX)
      const y = Math.min(Math.max(0, p.y), maxY)
      return { ...p, x, y }
    })
  }, [bg, crop.w, crop.h, placement.scale])

  // Render donor crop patch preview
  useEffect(() => {
    if (!donor || !patchCanvasRef.current) return
    const cvs = patchCanvasRef.current
    cvs.width = crop.w
    cvs.height = crop.h
    const ctx = cvs.getContext('2d')
    if (!ctx) return
    ctx.drawImage(donor.img, crop.x, crop.y, crop.w, crop.h, 0, 0, crop.w, crop.h)
  }, [donor, crop])

  // Render live composite preview
  useEffect(() => {
    if (!bg || !donor || !previewCanvasRef.current) return
    const cvs = previewCanvasRef.current
    cvs.width = bg.width
    cvs.height = bg.height
    const ctx = cvs.getContext('2d')
    if (!ctx) return

    // Draw background
    ctx.drawImage(bg.img, 0, 0)
    // Draw donor patch
    ctx.drawImage(
      donor.img,
      crop.x,
      crop.y,
      crop.w,
      crop.h,
      placement.x,
      placement.y,
      destWidth,
      destHeight,
    )
  }, [bg, donor, crop, placement.x, placement.y, destWidth, destHeight])

  // Crop presets
  const applyPreset = (preset: 'center50' | 'center25' | 'all') => {
    if (!donor) return
    if (preset === 'all') {
      setCrop({ x: 0, y: 0, w: donor.width, h: donor.height })
    } else {
      const factor = preset === 'center50' ? 0.5 : 0.25
      const w = Math.round(donor.width * factor)
      const h = Math.round(donor.height * factor)
      const x = Math.round((donor.width - w) / 2)
      const y = Math.round((donor.height - h) / 2)
      setCrop({ x, y, w, h })
    }
  }

  // Generate composite & ground-truth mask, then run detection
  const runSplicingTest = useCallback(
    async (format: 'png' | 'jpeg') => {
      if (!bg || !donor) return
      setError(null)

      try {
        // 1. Offscreen composite canvas
        const compCanvas = document.createElement('canvas')
        compCanvas.width = bg.width
        compCanvas.height = bg.height
        const compCtx = compCanvas.getContext('2d')
        if (!compCtx) throw new Error('Cannot create composite canvas context.')
        compCtx.drawImage(bg.img, 0, 0)
        compCtx.drawImage(
          donor.img,
          crop.x,
          crop.y,
          crop.w,
          crop.h,
          placement.x,
          placement.y,
          destWidth,
          destHeight,
        )

        // 2. Offscreen ground-truth mask canvas
        const gtCanvas = document.createElement('canvas')
        gtCanvas.width = bg.width
        gtCanvas.height = bg.height
        const gtCtx = gtCanvas.getContext('2d')
        if (!gtCtx) throw new Error('Cannot create ground-truth canvas context.')
        // Fill black (background / unaltered)
        gtCtx.fillStyle = '#000000'
        gtCtx.fillRect(0, 0, bg.width, bg.height)
        // Fill white (donor inserted patch)
        gtCtx.fillStyle = '#ffffff'
        gtCtx.fillRect(placement.x, placement.y, destWidth, destHeight)

        // 3. Export composite blob
        const compMime = format === 'jpeg' ? 'image/jpeg' : 'image/png'
        const compQuality = format === 'jpeg' ? 0.9 : 1.0
        const compBlob = await new Promise<Blob | null>((res) =>
          compCanvas.toBlob(res, compMime, compQuality),
        )
        if (!compBlob) throw new Error('Failed to generate composite image blob.')

        // 4. Export ground-truth mask blob (lossless PNG)
        const gtBlob = await new Promise<Blob | null>((res) =>
          gtCanvas.toBlob(res, 'image/png'),
        )
        if (!gtBlob) throw new Error('Failed to generate ground-truth mask blob.')

        const compExt = format === 'jpeg' ? 'jpg' : 'png'
        const compFile = new File(
          [compBlob],
          `spliced_${bg.file.name.replace(/\.[^.]+$/, '')}.${compExt}`,
          { type: compMime },
        )
        const gtFile = new File([gtBlob], 'ground_truth_mask.png', { type: 'image/png' })

        const compPreview = URL.createObjectURL(compBlob)
        setCompositeUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev)
          return compPreview
        })

        onRunTest({
          compositeFile: compFile,
          groundTruthFile: gtFile,
          compositePreviewUrl: compPreview,
          backgroundName: bg.file.name,
          donorName: donor.file.name,
          compositeFormat: format,
          isUntouchedControl: false,
        })
      } catch (err) {
        setError((err as Error).message)
      }
    },
    [bg, donor, crop, placement, destWidth, destHeight, onRunTest],
  )

  // Untouched background control test
  const runUntouchedControl = useCallback(async () => {
    if (!bg) return
    setError(null)

    try {
      // Ground truth mask for untouched background is completely black (all zeros)
      const gtCanvas = document.createElement('canvas')
      gtCanvas.width = bg.width
      gtCanvas.height = bg.height
      const gtCtx = gtCanvas.getContext('2d')
      if (!gtCtx) throw new Error('Cannot create ground-truth canvas context.')
      gtCtx.fillStyle = '#000000'
      gtCtx.fillRect(0, 0, bg.width, bg.height)

      const gtBlob = await new Promise<Blob | null>((res) =>
        gtCanvas.toBlob(res, 'image/png'),
      )
      if (!gtBlob) throw new Error('Failed to generate control mask blob.')
      const gtFile = new File([gtBlob], 'ground_truth_control.png', { type: 'image/png' })

      onRunTest({
        compositeFile: bg.file,
        groundTruthFile: gtFile,
        compositePreviewUrl: bg.url,
        backgroundName: bg.file.name,
        donorName: 'None (Untouched Control)',
        compositeFormat: bg.file.type === 'image/jpeg' ? 'jpeg' : 'png',
        isUntouchedControl: true,
      })
    } catch (err) {
      setError((err as Error).message)
    }
  }, [bg, onRunTest])

  return (
    <div className="space-y-6">
      {/* Informative Header Banner */}
      <Alert kind="info" title="Cross-Image Splicing Test">
        Test how the splicing heuristic (Error Level Analysis &amp; Wavelet Noise Residuals) performs
        on a controlled composite. Both source images remain immutable. The ground-truth mask is generated
        solely for post-detection evaluation and is never leaked to the detector.
      </Alert>

      {error && <Alert kind="error" title="Setup Error">{error}</Alert>}

      {/* Upload Dropzones */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Background Image */}
        <div className="card p-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-100">
            <span className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
              <Layers size={16} className="text-brand-600" /> 1. Background Image (Base)
            </span>
            {bg && (
              <button
                type="button"
                className="text-xs text-red-600 hover:underline"
                onClick={() => setBg(null)}
                disabled={busy}
              >
                Change
              </button>
            )}
          </div>

          {!bg ? (
            <label className="mt-3 flex flex-col items-center justify-center p-6 border-2 border-dashed border-slate-300 rounded-lg cursor-pointer hover:border-brand-500 hover:bg-brand-50/20 transition-colors">
              <UploadCloud size={32} className="text-slate-400 mb-2" />
              <span className="text-sm font-medium text-slate-700">Choose Background Image</span>
              <span className="text-xs text-slate-500 mt-1">JPEG or PNG, up to 10MB</span>
              <input
                type="file"
                accept="image/png,image/jpeg"
                className="hidden"
                onChange={handleBgUpload}
                disabled={busy}
              />
            </label>
          ) : (
            <div className="mt-3 space-y-2">
              <div className="flex items-center gap-3">
                <img
                  src={bg.url}
                  alt="Background preview"
                  className="w-16 h-16 object-cover rounded border border-slate-200"
                />
                <div className="text-xs space-y-0.5 text-slate-600">
                  <p className="font-semibold text-slate-800 truncate max-w-[200px]">{bg.file.name}</p>
                  <p>Dimensions: {bg.width} × {bg.height} px</p>
                  <p>Size: {formatBytes(bg.file.size)}</p>
                  <span className="inline-block text-[10px] font-semibold uppercase px-1.5 py-0.5 bg-slate-100 rounded text-slate-700">
                    {bg.file.type.replace('image/', '')}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Donor Image */}
        <div className="card p-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-100">
            <span className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
              <Crop size={16} className="text-purple-600" /> 2. Donor Image (Source of Patch)
            </span>
            {donor && (
              <button
                type="button"
                className="text-xs text-red-600 hover:underline"
                onClick={() => setDonor(null)}
                disabled={busy}
              >
                Change
              </button>
            )}
          </div>

          {!donor ? (
            <label className="mt-3 flex flex-col items-center justify-center p-6 border-2 border-dashed border-slate-300 rounded-lg cursor-pointer hover:border-purple-500 hover:bg-purple-50/20 transition-colors">
              <UploadCloud size={32} className="text-slate-400 mb-2" />
              <span className="text-sm font-medium text-slate-700">Choose Donor Image</span>
              <span className="text-xs text-slate-500 mt-1">JPEG or PNG, up to 10MB</span>
              <input
                type="file"
                accept="image/png,image/jpeg"
                className="hidden"
                onChange={handleDonorUpload}
                disabled={busy}
              />
            </label>
          ) : (
            <div className="mt-3 space-y-2">
              <div className="flex items-center gap-3">
                <img
                  src={donor.url}
                  alt="Donor preview"
                  className="w-16 h-16 object-cover rounded border border-slate-200"
                />
                <div className="text-xs space-y-0.5 text-slate-600">
                  <p className="font-semibold text-slate-800 truncate max-w-[200px]">{donor.file.name}</p>
                  <p>Dimensions: {donor.width} × {donor.height} px</p>
                  <p>Size: {formatBytes(donor.file.size)}</p>
                  <span className="inline-block text-[10px] font-semibold uppercase px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded">
                    {donor.file.type.replace('image/', '')}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Editor & Composition Controls (Visible when both images loaded) */}
      {bg && donor && (
        <div className="card p-5 space-y-6">
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
            <div>
              <h2 className="text-base font-semibold text-slate-900">
                Composite Configuration &amp; Alignment
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Select a rectangular patch from the donor image, scale it, and position it onto the background.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-600">Presets:</span>
              <button
                type="button"
                className="btn-secondary !text-xs !py-1 !px-2"
                onClick={() => applyPreset('center50')}
                disabled={busy}
              >
                Center 50%
              </button>
              <button
                type="button"
                className="btn-secondary !text-xs !py-1 !px-2"
                onClick={() => applyPreset('center25')}
                disabled={busy}
              >
                Center 25%
              </button>
              <button
                type="button"
                className="btn-secondary !text-xs !py-1 !px-2"
                onClick={() => applyPreset('all')}
                disabled={busy}
              >
                Full Donor
              </button>
            </div>
          </header>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Left: Donor Crop Controls & Patch Preview */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
                <Crop size={15} className="text-purple-600" /> A. Select Donor Crop Region
              </h3>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block font-medium text-slate-600 mb-1">
                    Crop X ({crop.x} px)
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, donor.width - crop.w)}
                    value={crop.x}
                    onChange={(e) => setCrop((c) => ({ ...c, x: Number(e.target.value) }))}
                    className="w-full"
                    disabled={busy}
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-600 mb-1">
                    Crop Y ({crop.y} px)
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, donor.height - crop.h)}
                    value={crop.y}
                    onChange={(e) => setCrop((c) => ({ ...c, y: Number(e.target.value) }))}
                    className="w-full"
                    disabled={busy}
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-600 mb-1">
                    Crop Width ({crop.w} px)
                  </label>
                  <input
                    type="range"
                    min={16}
                    max={donor.width}
                    value={crop.w}
                    onChange={(e) => setCrop((c) => ({ ...c, w: Number(e.target.value) }))}
                    className="w-full"
                    disabled={busy}
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-600 mb-1">
                    Crop Height ({crop.h} px)
                  </label>
                  <input
                    type="range"
                    min={16}
                    max={donor.height}
                    value={crop.h}
                    onChange={(e) => setCrop((c) => ({ ...c, h: Number(e.target.value) }))}
                    className="w-full"
                    disabled={busy}
                  />
                </div>
              </div>

              {/* Crop Patch Preview */}
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
                <span className="text-xs font-semibold text-slate-700 block">
                  Extracted Patch ({crop.w} × {crop.h} px)
                </span>
                <div className="flex items-center justify-center bg-slate-200/50 rounded overflow-hidden p-2 min-h-[120px] max-h-[180px]">
                  <canvas
                    ref={patchCanvasRef}
                    className="max-h-[160px] max-w-full object-contain shadow-sm border border-slate-300"
                  />
                </div>
              </div>
            </div>

            {/* Right: Background Placement Controls */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
                <Move size={15} className="text-brand-600" /> B. Position on Background
              </h3>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block font-medium text-slate-600 mb-1">
                    Position X ({placement.x} px)
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, bg.width - destWidth)}
                    value={placement.x}
                    onChange={(e) => setPlacement((p) => ({ ...p, x: Number(e.target.value) }))}
                    className="w-full"
                    disabled={busy}
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-600 mb-1">
                    Position Y ({placement.y} px)
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, bg.height - destHeight)}
                    value={placement.y}
                    onChange={(e) => setPlacement((p) => ({ ...p, y: Number(e.target.value) }))}
                    className="w-full"
                    disabled={busy}
                  />
                </div>
                <div className="col-span-2">
                  <div className="flex justify-between items-center mb-1">
                    <label className="font-medium text-slate-600">
                      Patch Scale: {placement.scale.toFixed(2)}×
                    </label>
                    <span className="text-slate-500 tabular-nums">
                      Inserted size: {destWidth} × {destHeight} px (
                      {((destWidth * destHeight * 100) / (bg.width * bg.height)).toFixed(1)}% of canvas)
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0.2}
                    max={2.0}
                    step={0.05}
                    value={placement.scale}
                    onChange={(e) => setPlacement((p) => ({ ...p, scale: Number(e.target.value) }))}
                    className="w-full"
                    disabled={busy}
                  />
                </div>
              </div>

              {/* Destination Composite Preview */}
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-700">
                    Live Composite Preview ({bg.width} × {bg.height} px)
                  </span>
                  <span className="text-[10px] text-slate-500">Target Resolution</span>
                </div>
                <div className="flex items-center justify-center bg-slate-900/5 rounded overflow-hidden p-2 min-h-[140px] max-h-[220px]">
                  <canvas
                    ref={previewCanvasRef}
                    className="max-h-[200px] max-w-full object-contain shadow-sm border border-slate-300"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Action Execution Bar */}
          <div className="pt-4 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                className="btn-primary"
                onClick={() => runSplicingTest('png')}
                disabled={busy}
              >
                <Sparkles size={16} aria-hidden />
                Run Splicing Test (Lossless PNG)
              </button>

              <button
                type="button"
                className="btn-secondary"
                onClick={() => runSplicingTest('jpeg')}
                disabled={busy}
                title="Exports the composite as a recompressed JPEG (q=90) to simulate saving and sharing"
              >
                <FileImage size={16} aria-hidden />
                Test Recompressed JPEG Control
              </button>

              <button
                type="button"
                className="btn-secondary"
                onClick={runUntouchedControl}
                disabled={busy}
                title="Analyzes the background image alone with an empty ground-truth mask to verify false alarm rates"
              >
                <CheckCircle2 size={16} aria-hidden />
                Test Untouched Background
              </button>
            </div>

            <button
              type="button"
              className="text-xs text-slate-500 hover:text-slate-800 flex items-center gap-1"
              onClick={() => {
                setBg(null)
                setDonor(null)
                setError(null)
              }}
              disabled={busy}
            >
              <RotateCcw size={13} /> Reset Both Images
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
