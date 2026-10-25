import { useMemo, useState } from 'react'
import { CheckCircle2, Download, FileJson, FileText, HelpCircle, ScanSearch } from 'lucide-react'
import type { DetectionResult, DetectionStatus } from '../types/api'
import { downloadBlob } from '../utils/files'
import { fetchArtifact, API_URL } from '../services/api'
import Alert from './Alert'
import Segmented from './Segmented'
import ZoomableImage from './ZoomableImage'

export interface ArtifactUrls { original: string; annotated?: string; mask?: string; heatmap?: string }
type View = 'original' | 'annotated' | 'mask' | 'heatmap' | 'compare'

const STATUS: Record<DetectionStatus, { title: string; kind: 'warning' | 'info'; Icon: typeof ScanSearch }> = {
  candidate_regions_found: { title: 'Candidate copy-move regions detected', kind: 'warning', Icon: ScanSearch },
  no_candidate_regions_found: { title: 'No candidate regions detected by the selected method', kind: 'info', Icon: CheckCircle2 },
  inconclusive: { title: 'Analysis inconclusive', kind: 'info', Icon: HelpCircle },
}

export default function DetectionResults({ result, urls, baseName }: {
  result: DetectionResult; urls: ArtifactUrls; baseName: string
}) {
  const [view, setView] = useState<View>('annotated')
  const [dlError, setDlError] = useState<string | null>(null)
  const st = STATUS[result.status]

  const download = async (key: 'annotated' | 'mask' | 'heatmap' | 'report_json' | 'report_html', file: string) => {
    setDlError(null)
    try { downloadBlob(await fetchArtifact(result.artifacts[key]), file) }
    catch (e) { setDlError((e as Error).message) }
  }

  const options = useMemo(() => [
    { value: 'original' as const, label: 'Original' },
    { value: 'annotated' as const, label: 'Annotated' },
    { value: 'mask' as const, label: 'Mask' },
    { value: 'heatmap' as const, label: 'Heatmap' },
    { value: 'compare' as const, label: 'Side by side' },
  ], [])

  const viewSrc = (v: Exclude<View, 'compare'>) => urls[v]

  return (
    <section aria-label="Analysis results" className="space-y-5">
      <Alert kind={st.kind} title={st.title}>
        {result.status_reason}
        {result.status === 'no_candidate_regions_found' && ' This does not show that the image is authentic or unedited.'}
      </Alert>

      <div className="card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <Segmented label="Result view" value={view} options={options} onChange={setView} />
          <p className="text-xs text-slate-500">
            {view === 'heatmap' && 'Density of retained match keypoints. Not a probability map.'}
            {view === 'mask' && 'White = approximate candidate areas (keypoint hulls), not pixel-exact.'}
            {view === 'annotated' && 'Solid outline = region A, dashed box = region B (same colour = matched pair).'}
          </p>
        </div>
        {view === 'compare' ? (
          <div className="grid gap-3 md:grid-cols-2">
            <figure><figcaption className="label">Original</figcaption><ZoomableImage src={urls.original} alt="Original image" /></figure>
            <figure><figcaption className="label">Annotated</figcaption>
              {urls.annotated && <ZoomableImage src={urls.annotated} alt="Annotated image" />}</figure>
          </div>
        ) : viewSrc(view)
          ? <ZoomableImage src={viewSrc(view)!} alt={`${view} view`} />
          : <p className="p-6 text-sm text-slate-500">Loading artifact…</p>}
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="card p-4 lg:col-span-1">
          <h3 className="mb-3 text-sm font-semibold text-slate-800">Statistics</h3>
          <dl className="space-y-2 text-sm">
            <Stat k="Image size" v={`${result.image.width} × ${result.image.height}`} />
            <Stat k="Analysis size" v={`${result.image.analysis_width} × ${result.image.analysis_height}`} />
            <Stat k="ORB keypoints" v={result.keypoints} />
            <Stat k="Matches before filtering" v={result.matches_before_filtering} />
            <Stat k="After descriptor filtering" v={result.matches_after_descriptor_filtering} />
            <Stat k="Retained matches" v={result.matches_retained} />
            <Stat k="Candidate regions" v={result.candidate_region_count} />
            <Stat k="Processing time" v={`${result.processing_ms.toFixed(0)} ms`} />
            <Stat k="Method" v={`${result.method.name} v${result.method.version}`} />
          </dl>
        </div>
        <div className="card overflow-x-auto p-4 lg:col-span-2">
          <h3 className="mb-3 text-sm font-semibold text-slate-800">Candidate regions</h3>
          {result.regions.length === 0 ? (
            <p className="text-sm text-slate-500">No regions to list.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr><th className="py-1 pr-3">#</th><th className="pr-3">Matches</th><th className="pr-3">Region A (x, y, w, h)</th>
                  <th className="pr-3">Region B (x, y, w, h)</th><th>Transform A→B</th></tr>
              </thead>
              <tbody className="tabular-nums">
                {result.regions.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100 align-top">
                    <td className="py-2 pr-3 font-semibold">{r.id}</td>
                    <td className="pr-3">{r.matches}</td>
                    <td className="pr-3">{box(r.region_a.bbox)}</td>
                    <td className="pr-3">{box(r.region_b.bbox)}</td>
                    <td>Δ({r.transform.translation_x.toFixed(0)}, {r.transform.translation_y.toFixed(0)}), {r.transform.rotation_degrees.toFixed(1)}°, ×{r.transform.scale.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="mt-3 text-xs text-slate-500">
            The method cannot tell which region is the original and which is the copy. Coordinates are in original-image pixels.
          </p>
        </div>
      </div>

      {result.warnings.length > 0 && (
        <Alert kind="warning" title="Notes from this run"><ul className="list-disc pl-5">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Alert>
      )}

      <div className="card p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">Interpretation &amp; limitations</h3>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          {result.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </div>

      <div className="card p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-800">Downloads</h3>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={() => download('annotated', `${baseName}_annotated.png`)}><Download size={16} aria-hidden /> Annotated</button>
          <button className="btn-secondary" onClick={() => download('mask', `${baseName}_mask.png`)}><Download size={16} aria-hidden /> Mask</button>
          <button className="btn-secondary" onClick={() => download('heatmap', `${baseName}_heatmap.png`)}><Download size={16} aria-hidden /> Heatmap</button>
          <button className="btn-secondary" onClick={() => download('report_json', `${baseName}_report.json`)}><FileJson size={16} aria-hidden /> Report (JSON)</button>
          <button className="btn-secondary" onClick={() => download('report_html', `${baseName}_report.html`)}><FileText size={16} aria-hidden /> Report (HTML)</button>
        </div>
        {dlError && <p role="alert" className="mt-2 text-sm text-red-700">{dlError}</p>}
        <p className="mt-2 text-xs text-slate-500">
          Results are held in server memory for {Math.round(result.artifact_ttl_seconds / 60)} minutes, then discarded. Server: {API_URL}
        </p>
      </div>
    </section>
  )
}

const box = (b: { x: number; y: number; width: number; height: number }) => `${b.x}, ${b.y}, ${b.width}, ${b.height}`

function Stat({ k, v }: { k: string; v: string | number }) {
  return <div className="flex justify-between gap-3"><dt className="text-slate-500">{k}</dt><dd className="text-right font-medium tabular-nums">{v}</dd></div>
}
