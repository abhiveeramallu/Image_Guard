import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Loader2, Stamp } from 'lucide-react'
import Alert from '../components/Alert'
import ImageDropzone from '../components/ImageDropzone'
import ImageSummary from '../components/ImageSummary'
import Segmented from '../components/Segmented'
import InvisibleWatermarkPanel from '../components/InvisibleWatermarkPanel'
import WatermarkControls from '../components/WatermarkControls'
import ZoomableImage from '../components/ZoomableImage'
import { useBlobUrls } from '../hooks/useBlobUrls'
import { useImageFile } from '../hooks/useImageFile'
import { applyWatermark, isCancelled } from '../services/api'
import { DEFAULT_WATERMARK_SETTINGS, type WatermarkResult, type WatermarkSettings } from '../types/api'
import { downloadBlob, validateImageFile } from '../utils/files'

type View = 'original' | 'processed' | 'compare'
const LIVE_MAX_BYTES = 3 * 1024 * 1024
const LOGO_MAX_BYTES = 2 * 1024 * 1024

type Mode = 'visible' | 'invisible'

export default function WatermarkPage() {
  const [mode, setMode] = useState<Mode>('visible')
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold text-ink-900">Watermark Studio</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          <b>Visible</b> watermarks overlay text or a logo. <b>Invisible</b> watermarks hide a keyed payload in the image data so it can be verified later. They are separate tools.
        </p>
      </header>
      <Segmented label="Watermark kind" value={mode} onChange={setMode}
        options={[{ value: 'visible', label: 'Visible watermark' }, { value: 'invisible', label: 'Invisible watermark' }]} />
      {mode === 'visible' ? <VisibleStudio /> : <InvisibleWatermarkPanel />}
    </div>
  )
}

function VisibleStudio() {
  const { image, error: fileError, select, clear } = useImageFile()
  const [settings, setSettings] = useState<WatermarkSettings>(DEFAULT_WATERMARK_SETTINGS)
  const [logo, setLogo] = useState<File | null>(null)
  const [logoError, setLogoError] = useState<string | null>(null)
  const [live, setLive] = useState(true)
  const [view, setView] = useState<View>('processed')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<(WatermarkResult & { key: string }) | null>(null)
  const abort = useRef<AbortController | null>(null)
  const blobs = useMemo(() => (result ? { processed: result.blob } : null), [result])
  const urls = useBlobUrls(blobs)

  const key = useMemo(() => JSON.stringify([settings, logo?.name, logo?.size, image?.url]), [settings, logo, image])
  const stale = !!result && result.key !== key
  const ready = !!image && (settings.watermark_type === 'text' ? settings.text.trim().length > 0 : !!logo)
  const liveAllowed = !!image && image.file.size <= LIVE_MAX_BYTES

  const onFile = useCallback(async (f: File) => {
    if (await select(f)) { setResult(null); setError(null) }
  }, [select])

  // Scale default font size / margin to the image the first time it loads.
  const imageUrl = image?.url
  const imageWidth = image?.width
  useEffect(() => {
    if (imageWidth) {
      setSettings((s) => ({ ...s, font_size: Math.min(400, Math.max(12, Math.round(imageWidth * 0.05))), margin: Math.round(imageWidth * 0.02) }))
    }
  }, [imageUrl, imageWidth])

  const onLogo = (f: File | null) => {
    if (!f) return
    const problem = validateImageFile(f, LOGO_MAX_BYTES)
    setLogoError(problem)
    if (!problem) setLogo(f)
  }

  const render = useCallback(async () => {
    if (!image || !ready) return
    abort.current?.abort()
    const ctl = new AbortController()
    abort.current = ctl
    setBusy(true); setError(null)
    try {
      const res = await applyWatermark(image.file, settings, logo, { signal: ctl.signal })
      setResult({ ...res, key })
    } catch (e) {
      if (!isCancelled(e)) setError((e as Error).message)
    } finally {
      if (abort.current === ctl) { setBusy(false); abort.current = null }
    }
  }, [image, ready, settings, logo, key])

  // Live preview: debounced, rendered by the real backend (so the preview equals the download).
  useEffect(() => {
    if (!live || !liveAllowed || !ready) return
    const t = setTimeout(render, 600)
    return () => clearTimeout(t)
  }, [live, liveAllowed, ready, render])
  useEffect(() => () => abort.current?.abort(), [])

  const maxFont = image ? Math.min(400, Math.max(48, Math.round(image.width / 4))) : 200
  const showView: View = result ? view : 'original'

  return (
    <div className="space-y-5">
      <p className="max-w-3xl text-sm text-slate-600">
        Add a visible text or logo watermark. Image dimensions are preserved. Rendering happens on the server; uploads are processed in memory and not stored.
        A visible watermark can be cropped or edited out and does not prove authenticity.
      </p>

      {!image ? <ImageDropzone onFile={onFile} error={fileError} label="Drag & drop the image to watermark" /> : (
        <>
          <ImageSummary image={image} onReplace={onFile} onRemove={() => { clear(); setResult(null); setError(null) }} disabled={busy} />
          {fileError && <p role="alert" className="text-sm font-medium text-red-700">{fileError}</p>}
          <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
            <div className="space-y-3">
              <WatermarkControls value={settings} onChange={setSettings} logo={logo} onLogo={onLogo} logoError={logoError} maxFont={maxFont} />
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input type="checkbox" checked={live && liveAllowed} disabled={!liveAllowed} onChange={(e) => setLive(e.target.checked)} />
                Live preview{!liveAllowed && ' (off for files over 3 MB)'}
              </label>
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary" onClick={render} disabled={!ready || busy}>
                  {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Stamp size={16} aria-hidden />} Apply watermark
                </button>
                <button className="btn-secondary" disabled={!result || stale || busy}
                  onClick={() => result && downloadBlob(result.blob, result.filename)}>
                  <Download size={16} aria-hidden /> Download {settings.output_format.toUpperCase()}
                </button>
              </div>
              {!ready && <p className="text-xs text-slate-500">{settings.watermark_type === 'text' ? 'Enter watermark text to continue.' : 'Choose a logo to continue.'}</p>}
              {stale && !busy && <p className="text-xs text-amber-700">Settings changed — apply the watermark to update the download.</p>}
            </div>

            <div className="min-w-0 space-y-3">
              {error && <Alert kind="error" title="Could not apply watermark" action={<button className="btn-secondary shrink-0" onClick={render}>Retry</button>}>{error}</Alert>}
              <div className="card p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <Segmented label="Preview" value={showView} onChange={setView}
                    options={[{ value: 'original', label: 'Original' }, { value: 'processed', label: 'Watermarked', disabled: !result },
                      { value: 'compare', label: 'Side by side', disabled: !result }]} />
                  {busy && <span role="status" className="flex items-center gap-1.5 text-xs text-slate-500"><Loader2 size={14} className="animate-spin" /> Rendering…</span>}
                </div>
                {showView === 'compare' && urls.processed ? (
                  <div className="grid gap-3 md:grid-cols-2">
                    <figure><figcaption className="label">Original</figcaption><ZoomableImage src={image.url} alt="Original image" /></figure>
                    <figure><figcaption className="label">Watermarked</figcaption><ZoomableImage src={urls.processed} alt="Watermarked image" /></figure>
                  </div>
                ) : showView === 'processed' && urls.processed ? (
                  <ZoomableImage src={urls.processed} alt="Watermarked image" />
                ) : (
                  <ZoomableImage src={image.url} alt="Original image" />
                )}
                {!result && <p className="mt-2 text-xs text-slate-500">The watermarked preview appears here after the first render.</p>}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
