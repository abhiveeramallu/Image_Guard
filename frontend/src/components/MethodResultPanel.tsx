import { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, CircleAlert, Download, FlaskConical, HelpCircle, PlugZap, ScanSearch } from 'lucide-react'
import type { MethodId, MethodResult, MethodStatus } from '../types/api'
import { downloadBlob } from '../utils/files'
import { fetchArtifact } from '../services/api'
import Alert from './Alert'
import Segmented from './Segmented'
import ThresholdLayer from './ThresholdLayer'
import ZoomableImage from './ZoomableImage'

const TITLES: Record<MethodId, string> = {
  copy_move: 'Copy-move detection (ORB)', splicing: 'Splicing heuristic', localization: 'Model-based localization',
}
const EVIDENCE: Record<MethodResult['evidence_type'], string> = {
  feature_match_regions: 'Feature-match regions: approximate hulls around matched keypoints, not pixel-level.',
  heuristic_forensic_map: 'Heuristic forensic map: normalised score, not a probability.',
  model_probability_map: 'Model-predicted per-pixel map, interpreted per the model card.',
}
const STATUS: Record<MethodStatus, { text: (m: MethodId) => string; kind: 'warning' | 'info' | 'error'; Icon: typeof ScanSearch }> = {
  candidate_regions_found: {
    text: (m) => (m === 'copy_move' ? 'Candidate copy-move regions detected' : m === 'splicing' ? 'Possible local inconsistencies (heuristic)' : 'Model flagged candidate regions'),
    kind: 'warning', Icon: ScanSearch,
  },
  no_candidate_regions_found: { text: () => 'No candidate regions detected by this method', kind: 'info', Icon: CheckCircle2 },
  inconclusive: { text: () => 'Analysis inconclusive', kind: 'info', Icon: HelpCircle },
  unavailable: { text: () => 'Method unavailable', kind: 'warning', Icon: PlugZap },
  failed: { text: () => 'Method failed', kind: 'error', Icon: CircleAlert },
}

type Tab = 'original' | 'annotated' | 'overlay' | 'heatmap' | 'mask' | 'threshold'
const TAB_LABEL: Record<Tab, string> = {
  original: 'Original', annotated: 'Annotated', overlay: 'Mask overlay', heatmap: 'Heatmap', mask: 'Mask', threshold: 'Adjust threshold',
}

export default function MethodResultPanel({ analysisId, result, originalUrl, urls, onFallback }: {
  analysisId: string; result: MethodResult; originalUrl: string; urls: Record<string, string | undefined>
  onFallback?: () => void
}) {
  const st = STATUS[result.status]
  const hasMap = result.artifacts.score !== undefined
  const tabs = useMemo<Tab[]>(() => {
    const t: Tab[] = ['original']
    for (const k of ['annotated', 'overlay', 'heatmap', 'mask'] as const) if (result.artifacts[k]) t.push(k)
    if (hasMap) t.push('threshold')
    return t
  }, [result.artifacts, hasMap])
  const [tab, setTab] = useState<Tab>(result.artifacts.annotated ? 'annotated' : result.artifacts.overlay ? 'overlay' : 'original')
  const [dlError, setDlError] = useState<string | null>(null)
  const prefix = result.method

  const download = async (name: string) => {
    setDlError(null)
    try { downloadBlob(await fetchArtifact(result.artifacts[name]), `${prefix}_${name}.png`) } catch (e) { setDlError((e as Error).message) }
  }
  const src = tab === 'original' ? originalUrl : urls[`${prefix}.${tab}`]
  const metricEntries = Object.entries(result.metrics).filter(([, v]) => typeof v !== 'object' || v === null)

  return (
    <section aria-label={`${TITLES[result.method]} result`} className="card space-y-4 p-4">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-ink-900">{TITLES[result.method]}</h2>
        {result.experimental && (
          <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-amber-800">
            <FlaskConical size={10} aria-hidden /> Experimental
          </span>
        )}
        <span className="text-xs text-slate-500">{result.method_name} v{result.method_version} · {result.processing_ms.toFixed(0)} ms</span>
      </header>
      <p className="text-xs text-slate-500">{EVIDENCE[result.evidence_type]}</p>

      <Alert kind={st.kind} title={st.text(result.method)}>
        {result.status_reason}
        {result.status === 'no_candidate_regions_found' && ' This does not show that the image is authentic or unedited.'}
      </Alert>

      {(result.status === 'unavailable' || result.status === 'failed') && result.method !== 'copy_move' && onFallback && (
        <button className="btn-secondary" onClick={onFallback}><ScanSearch size={16} aria-hidden /> Run copy-move detection instead</button>
      )}

      {result.model && (
        <dl className="grid gap-x-6 gap-y-1 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-2">
          <div><dt className="inline font-semibold">Model: </dt><dd className="inline">{result.model.name} (v{result.model.version})</dd></div>
          <div><dt className="inline font-semibold">ID: </dt><dd className="inline">{result.model.id}</dd></div>
          <div><dt className="inline font-semibold">License: </dt><dd className="inline">{result.model.license}</dd></div>
          <div><dt className="inline font-semibold">Runs on: </dt><dd className="inline">{result.model.provider}</dd></div>
          <div className="sm:col-span-2"><dt className="inline font-semibold">Source: </dt><dd className="inline break-all">{result.model.source}</dd></div>
        </dl>
      )}

      {tabs.length > 1 && (
        <>
          <Segmented label={`${TITLES[result.method]} view`} value={tab} onChange={setTab} options={tabs.map((v) => ({ value: v, label: TAB_LABEL[v] }))} />
          {tab === 'threshold' ? (
            <ThresholdLayer analysisId={analysisId} method={result.method} originalUrl={originalUrl}
              initial={result.threshold ?? 0.5} semantics={result.threshold_semantics} />
          ) : src ? <ZoomableImage src={src} alt={`${prefix} ${tab} view`} /> : <p className="text-sm text-slate-500">Loading artifact…</p>}
        </>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-800">Computed metrics</h3>
          <dl className="space-y-1 text-sm">
            <Row k="Candidate regions" v={result.region_count} />
            {result.threshold !== null && <Row k="Threshold used" v={result.threshold} />}
            {metricEntries.map(([k, v]) => <Row key={k} k={k.replace(/_/g, ' ')} v={String(v)} />)}
          </dl>
        </div>
        {result.regions.length > 0 && (
          <div className="overflow-x-auto">
            <h3 className="mb-2 text-sm font-semibold text-slate-800">Regions</h3>
            <table className="w-full text-left text-xs tabular-nums">
              <thead className="uppercase text-slate-500"><tr><th>#</th><th>x, y, w, h</th><th>{result.method === 'copy_move' ? 'Matches' : 'Area px'}</th></tr></thead>
              <tbody>
                {result.regions.map((r, i) => <RegionRow key={i} method={result.method} r={r} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {result.warnings.length > 0 && (
        <Alert kind="warning" title="Notes"><ul className="list-disc pl-5">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Alert>
      )}
      {result.limitations.length > 0 && (
        <details className="text-sm text-slate-600"><summary className="cursor-pointer font-semibold text-slate-800">Limitations</summary>
          <ul className="mt-1 list-disc space-y-1 pl-5">{result.limitations.map((l) => <li key={l}>{l}</li>)}</ul></details>
      )}
      {(['annotated', 'overlay', 'heatmap', 'mask'] as const).some((k) => result.artifacts[k]) && (
        <div className="flex flex-wrap gap-2">
          {(['annotated', 'overlay', 'heatmap', 'mask'] as const).filter((k) => result.artifacts[k]).map((k) => (
            <button key={k} className="btn-secondary" aria-label={`Download ${prefix} ${k}`} onClick={() => download(k)}>
              <Download size={16} aria-hidden /> {TAB_LABEL[k]}
            </button>
          ))}
        </div>
      )}
      {dlError && <p role="alert" className="text-sm text-red-700">{dlError}</p>}
      {result.status === 'failed' && <p className="flex items-center gap-1 text-xs text-slate-500"><AlertTriangle size={12} aria-hidden /> No output was produced; nothing is shown in place of a result.</p>}
    </section>
  )
}

function RegionRow({ method, r }: { method: MethodId; r: Record<string, unknown> }) {
  const bbox = (r.bbox ?? (r.region_a as { bbox?: Record<string, number> } | undefined)?.bbox) as Record<string, number> | undefined
  const b = bbox ? `${bbox.x}, ${bbox.y}, ${bbox.width}, ${bbox.height}` : '-'
  const extra = method === 'copy_move' ? (r.matches as number) : (r.area_px as number)
  return <tr className="border-t border-slate-100"><td className="py-1 pr-2">{String(r.id)}</td><td className="pr-2">{b}{method === 'copy_move' && ' (A)'}</td><td>{extra}</td></tr>
}

function Row({ k, v }: { k: string; v: string | number }) {
  return <div className="flex justify-between gap-3"><dt className="capitalize text-slate-500">{k}</dt><dd className="max-w-[60%] truncate text-right font-medium tabular-nums" title={String(v)}>{v}</dd></div>
}
