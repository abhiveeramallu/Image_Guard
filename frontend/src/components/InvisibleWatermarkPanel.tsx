import { useEffect, useRef, useState } from 'react'
import { Download, Fingerprint, Loader2, PlugZap, ShieldCheck, ShieldQuestion, ShieldX } from 'lucide-react'
import Alert from './Alert'
import ImageDropzone from './ImageDropzone'
import ImageSummary from './ImageSummary'
import { Field } from './FormFields'
import { useCapabilities } from '../hooks/useCapabilities'
import { useImageFile } from '../hooks/useImageFile'
import { embedInvisible, fetchArtifact, isCancelled, verifyInvisible } from '../services/api'
import type { InvisibleEmbedResult, InvisibleStrength, InvisibleVerifyResult } from '../types/api'
import { downloadBlob } from '../utils/files'
import { sanitizeBaseName } from '../utils/names'

export default function InvisibleWatermarkPanel() {
  const { caps, error: capsError, loading } = useCapabilities()
  const cap = caps?.invisible_watermark
  return (
    <div className="space-y-5">
      <Alert kind="info" title="Invisible watermark ≠ proof of ownership or integrity">
        A payload is hidden in the image's frequency data and protected by a server-side keyed check (HMAC). A successful verification shows that
        someone holding this server's key embedded it. It does not prove who owns the image or that the image is unmodified, and it does not survive resizing or rotation.
      </Alert>
      {loading && <p role="status" className="text-sm text-slate-500">Checking server capabilities…</p>}
      {capsError && <Alert kind="error" title="Cannot reach the server">{capsError}</Alert>}
      {cap && !cap.available && (
        <Alert kind="warning" title="Invisible watermarking is unavailable"><span className="flex items-center gap-1"><PlugZap size={14} aria-hidden /> {cap.reason}</span></Alert>
      )}
      {cap?.available && (
        <div className="grid gap-5 xl:grid-cols-2">
          <EmbedCard />
          <VerifyCard />
        </div>
      )}
    </div>
  )
}

function EmbedCard() {
  const { image, error: fileError, select, clear } = useImageFile()
  const [owner, setOwner] = useState('')
  const [strength, setStrength] = useState<InvisibleStrength>('standard')
  const [format, setFormat] = useState<'png' | 'jpeg'>('png')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<InvisibleEmbedResult | null>(null)
  const abort = useRef<AbortController | null>(null)
  useEffect(() => () => abort.current?.abort(), [])

  const embed = async () => {
    if (!image) return
    const ctl = new AbortController(); abort.current = ctl
    setBusy(true); setError(null); setResult(null)
    try { setResult(await embedInvisible(image.file, owner.trim(), strength, format, { signal: ctl.signal })) }
    catch (e) { if (!isCancelled(e)) setError((e as Error).message) }
    finally { setBusy(false) }
  }
  const download = async () => {
    if (!result || !image) return
    try {
      downloadBlob(await fetchArtifact(result.artifact), `${sanitizeBaseName(image.file.name)}_invisible.${result.output_format === 'jpeg' ? 'jpg' : 'png'}`)
    } catch (e) { setError((e as Error).message) }
  }
  const valid = /^[\x20-\x7e]{1,12}$/.test(owner.trim()) && owner.trim().length > 0

  return (
    <section className="card space-y-4 p-4" aria-label="Embed invisible watermark">
      <h2 className="flex items-center gap-2 font-semibold text-slate-800"><Fingerprint size={18} className="text-accent-600" aria-hidden /> Embed</h2>
      {!image ? <ImageDropzone onFile={async (f) => { if (await select(f)) { setResult(null); setError(null) } }} error={fileError} label="Image to watermark invisibly" />
        : <ImageSummary image={image} onReplace={async (f) => { if (await select(f)) { setResult(null) } }} onRemove={() => { clear(); setResult(null) }} disabled={busy} />}
      <Field label="Owner / identifier (1–12 ASCII characters)" htmlFor="iw-owner">
        <input id="iw-owner" className="input" maxLength={12} value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="e.g. Acme-2026" />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Strength" htmlFor="iw-strength">
          <select id="iw-strength" className="input" value={strength} onChange={(e) => setStrength(e.target.value as InvisibleStrength)}>
            <option value="low">Low (least visible)</option><option value="standard">Standard</option><option value="high">High (most robust)</option>
          </select>
        </Field>
        <Field label="Output format" htmlFor="iw-format">
          <select id="iw-format" className="input" value={format} onChange={(e) => setFormat(e.target.value as 'png' | 'jpeg')}>
            <option value="png">PNG (recommended)</option><option value="jpeg">JPEG (lossy)</option>
          </select>
        </Field>
      </div>
      <button className="btn-primary" disabled={!image || !valid || busy} onClick={embed}>
        {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Fingerprint size={16} aria-hidden />} Embed invisible watermark
      </button>
      {error && <Alert kind="error" title="Embedding failed" action={<button className="btn-secondary shrink-0" onClick={embed}>Retry</button>}>{error}</Alert>}
      {result && (
        <div className="space-y-3">
          <Alert kind="info" title="Invisible watermark embedded">
            Payload “{result.owner}” was embedded ({result.algorithm.name}). Visible distortion: PSNR {result.metrics.psnr_db} dB, step {result.metrics.quantization_step}, ~{result.metrics.copies_per_bit} copies per bit.
            Verify the downloaded file to confirm it. No visible watermark was applied.
          </Alert>
          {result.warnings.map((w) => <Alert key={w} kind="warning">{w}</Alert>)}
          <button className="btn-secondary" onClick={download}><Download size={16} aria-hidden /> Download watermarked image</button>
          <details className="text-xs text-slate-600"><summary className="cursor-pointer font-semibold">Limitations</summary>
            <ul className="mt-1 list-disc pl-5">{result.limitations.map((l) => <li key={l}>{l}</li>)}</ul></details>
        </div>
      )}
    </section>
  )
}

function VerifyCard() {
  const { image, error: fileError, select, clear } = useImageFile()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<InvisibleVerifyResult | null>(null)
  const abort = useRef<AbortController | null>(null)
  useEffect(() => () => abort.current?.abort(), [])

  const run = async () => {
    if (!image) return
    const ctl = new AbortController(); abort.current = ctl
    setBusy(true); setError(null); setResult(null)
    try { setResult(await verifyInvisible(image.file, { signal: ctl.signal })) }
    catch (e) { if (!isCancelled(e)) setError((e as Error).message) }
    finally { setBusy(false) }
  }
  const V = result && ({
    verified: { Icon: ShieldCheck, title: 'Invisible watermark verified', kind: 'info' as const },
    inconclusive: { Icon: ShieldQuestion, title: 'Verification inconclusive', kind: 'warning' as const },
    not_detected: { Icon: ShieldX, title: 'Verification unsuccessful: no matching watermark found', kind: 'warning' as const },
  })[result.status]

  return (
    <section className="card space-y-4 p-4" aria-label="Verify invisible watermark">
      <h2 className="flex items-center gap-2 font-semibold text-slate-800"><ShieldCheck size={18} className="text-accent-600" aria-hidden /> Verify</h2>
      {!image ? <ImageDropzone onFile={async (f) => { if (await select(f)) { setResult(null); setError(null) } }} error={fileError} label="Image to check for a watermark" />
        : <ImageSummary image={image} onReplace={async (f) => { if (await select(f)) { setResult(null) } }} onRemove={() => { clear(); setResult(null) }} disabled={busy} />}
      <button className="btn-primary" disabled={!image || busy} onClick={run}>
        {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <ShieldCheck size={16} aria-hidden />} Verify watermark
      </button>
      {busy && <p role="status" className="text-sm text-slate-600">Searching block alignments…</p>}
      {error && <Alert kind="error" title="Verification failed to run" action={<button className="btn-secondary shrink-0" onClick={run}>Retry</button>}>{error}</Alert>}
      {result && V && (
        <div className="space-y-3">
          <Alert kind={V.kind} title={V.title}>{result.status_reason}</Alert>
          {result.status === 'verified' && (
            <dl className="space-y-1 text-sm">
              <div className="flex justify-between"><dt className="text-slate-500">Recovered payload</dt><dd className="font-mono font-semibold">{result.owner}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Integrity check (HMAC)</dt><dd className="font-medium">{result.integrity_verified ? 'valid' : 'invalid'}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Vote strength</dt><dd className="tabular-nums">{String(result.metrics.bit_strength)}</dd></div>
            </dl>
          )}
          {result.warnings.map((w) => <Alert key={w} kind="warning">{w}</Alert>)}
          <details className="text-xs text-slate-600"><summary className="cursor-pointer font-semibold">Limitations</summary>
            <ul className="mt-1 list-disc pl-5">{result.limitations.map((l) => <li key={l}>{l}</li>)}</ul></details>
        </div>
      )}
    </section>
  )
}
