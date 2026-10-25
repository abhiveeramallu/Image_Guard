import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  FileJson,
  Loader2,
  ScanSearch,
  X,
} from 'lucide-react'
import Alert from '../components/Alert'
import DetectionResults from '../components/DetectionResults'
import DetectionSettingsPanel from '../components/DetectionSettingsPanel'
import ImageDropzone from '../components/ImageDropzone'
import ImageSummary from '../components/ImageSummary'
import MethodResultPanel from '../components/MethodResultPanel'
import MethodSelector from '../components/MethodSelector'
import Segmented from '../components/Segmented'
import SplicingTestWorkspace, { type SplicingTestInput } from '../components/SplicingTestWorkspace'
import { useBlobUrls } from '../hooks/useBlobUrls'
import { useCapabilities } from '../hooks/useCapabilities'
import { useImageFile } from '../hooks/useImageFile'
import { analyzeImage, detectCopyMove, fetchArtifact, isCancelled } from '../services/api'
import {
  DEFAULT_DETECTION_SETTINGS,
  type AnalysisResult,
  type DetectionResult,
  type DetectionSettings,
  type MethodId,
} from '../types/api'
import { downloadBlob } from '../utils/files'
import { sanitizeBaseName } from '../utils/names'

type WorkflowMode = 'single' | 'splicing_test'
type Phase = 'idle' | 'uploading' | 'analysing' | 'fetching'
type Blobs = Record<string, Blob>

const COPY_MOVE_ONLY: MethodId[] = ['copy_move']
const VIEW_ARTIFACTS = [
  'annotated',
  'overlay',
  'mask',
  'heatmap',
  'ela',
  'noise',
  'ground_truth',
] as const

export default function DetectionPage() {
  const [mode, setMode] = useState<WorkflowMode>('single')

  // Single-image workflow state
  const { image, error: fileError, select, clear } = useImageFile()
  const { caps, error: capsError, loading: capsLoading } = useCapabilities()
  const [methods, setMethods] = useState<MethodId[]>(COPY_MOVE_ONLY)
  const [settings, setSettings] = useState<DetectionSettings>(DEFAULT_DETECTION_SETTINGS)

  // Execution & results state
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<DetectionResult | null>(null)
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null)
  const [blobs, setBlobs] = useState<Blobs | null>(null)
  const urls = useBlobUrls(blobs)
  const abort = useRef<AbortController | null>(null)

  // Splicing test metadata
  const [splicingMeta, setSplicingMeta] = useState<SplicingTestInput | null>(null)

  useEffect(() => () => abort.current?.abort(), [])

  const reset = useCallback(() => {
    setResult(null)
    setAnalysis(null)
    setBlobs(null)
    setError(null)
    setSplicingMeta(null)
  }, [])

  const onFile = useCallback(
    async (f: File) => {
      if (await select(f)) reset()
    },
    [select, reset],
  )

  // Run single-image detection
  const run = async (override?: MethodId[]) => {
    if (!image) return
    const chosen = override ?? methods
    if (override) setMethods(override)
    reset()
    const ctl = new AbortController()
    abort.current = ctl
    setPhase('uploading')
    setProgress(0)
    const onProgress = (f: number) => {
      setProgress(f)
      if (f >= 1) setPhase('analysing')
    }

    try {
      if (chosen.length === 1 && chosen[0] === 'copy_move') {
        const res = await detectCopyMove(image.file, settings, { signal: ctl.signal, onProgress })
        setPhase('fetching')
        const [annotated, mask, heatmap] = await Promise.all([
          fetchArtifact(res.artifacts.annotated, ctl.signal),
          fetchArtifact(res.artifacts.mask, ctl.signal),
          fetchArtifact(res.artifacts.heatmap, ctl.signal),
        ])
        setResult(res)
        setBlobs({ annotated, mask, heatmap })
      } else {
        const res = await analyzeImage(
          image.file,
          chosen,
          { ...settings, splicing_threshold: 0.5 },
          { signal: ctl.signal, onProgress },
        )
        setPhase('fetching')
        const flat: Blobs = {}
        await Promise.all(
          res.results.flatMap((r) =>
            VIEW_ARTIFACTS.filter((k) => r.artifacts[k]).map(async (k) => {
              flat[`${r.method}.${k}`] = await fetchArtifact(r.artifacts[k], ctl.signal)
            }),
          ),
        )
        setAnalysis(res)
        setBlobs(flat)
      }
    } catch (e) {
      if (!isCancelled(e)) setError((e as Error).message)
    } finally {
      setPhase('idle')
      abort.current = null
    }
  }

  // Run cross-image splicing test
  const runSplicingTest = async (testInput: SplicingTestInput) => {
    reset()
    setSplicingMeta(testInput)
    const ctl = new AbortController()
    abort.current = ctl
    setPhase('uploading')
    setProgress(0)
    const onProgress = (f: number) => {
      setProgress(f)
      if (f >= 1) setPhase('analysing')
    }

    try {
      const res = await analyzeImage(
        testInput.compositeFile,
        ['splicing'],
        { ...settings, splicing_threshold: 0.5 },
        { signal: ctl.signal, onProgress },
        testInput.groundTruthFile,
      )
      setPhase('fetching')
      const flat: Blobs = {}
      await Promise.all([
        ...res.results.flatMap((r) =>
          VIEW_ARTIFACTS.filter((k) => r.artifacts[k]).map(async (k) => {
            flat[`${r.method}.${k}`] = await fetchArtifact(r.artifacts[k], ctl.signal)
          }),
        ),
        res.ground_truth
          ? (async () => {
              flat['ground_truth'] = await fetchArtifact(res.ground_truth!, ctl.signal)
            })()
          : Promise.resolve(),
      ])
      setAnalysis(res)
      setBlobs(flat)
    } catch (e) {
      if (!isCancelled(e)) setError((e as Error).message)
    } finally {
      setPhase('idle')
      abort.current = null
    }
  }

  const downloadReport = async () => {
    if (!analysis) return
    const base = splicingMeta
      ? `splicing_test_${sanitizeBaseName(splicingMeta.backgroundName)}`
      : image
        ? sanitizeBaseName(image.file.name)
        : 'analysis'
    try {
      downloadBlob(await fetchArtifact(analysis.report_json), `${base}_analysis.json`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const busy = phase !== 'idle'
  const multi = useMemo(() => !(methods.length === 1 && methods[0] === 'copy_move'), [methods])
  const statusText =
    phase === 'uploading'
      ? `Uploading… ${Math.round(progress * 100)}%`
      : phase === 'analysing'
        ? mode === 'splicing_test'
          ? 'Running cross-image splicing analysis…'
          : `Running ${methods.length} method${methods.length === 1 ? '' : 's'}…`
        : phase === 'fetching'
          ? 'Fetching diagnostic artifacts…'
          : ''

  const activeDisplayUrl = splicingMeta ? splicingMeta.compositePreviewUrl : image ? image.url : ''

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-ink-900">Forgery Detection</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Screen images for clone-masking and composite manipulation using classical computer vision cues.
            Results are independent diagnostic indicators, not definitive legal proof of authenticity.
          </p>
        </div>

        {/* Workflow Switcher */}
        <Segmented
          label="Workflow mode"
          value={mode}
          onChange={(m) => {
            setMode(m)
            reset()
          }}
          options={[
            { value: 'single', label: 'Single Image Analysis' },
            { value: 'splicing_test', label: 'Cross-Image Splicing Test' },
          ]}
        />
      </header>

      {/* Mode 1: Single Image Forensic Workflow */}
      {mode === 'single' && (
        <div className="space-y-5">
          {!image ? (
            <ImageDropzone onFile={onFile} error={fileError} label="Drag & drop the image to analyse" />
          ) : (
            <>
              <ImageSummary
                image={image}
                onReplace={onFile}
                onRemove={() => {
                  clear()
                  reset()
                }}
                disabled={busy}
              />
              {fileError && (
                <p role="alert" className="text-sm font-medium text-red-700">
                  {fileError}
                </p>
              )}
            </>
          )}

          {image && (
            <MethodSelector
              caps={caps}
              error={capsError}
              loading={capsLoading}
              selected={methods}
              onChange={setMethods}
              disabled={busy}
            />
          )}

          {image && methods.includes('copy_move') && (
            <DetectionSettingsPanel value={settings} onChange={setSettings} disabled={busy} />
          )}

          {image && (
            <div className="flex flex-wrap items-center gap-3">
              <button
                className="btn-primary"
                onClick={() => run()}
                disabled={busy || methods.length === 0}
              >
                {busy ? (
                  <Loader2 size={16} className="animate-spin" aria-hidden />
                ) : (
                  <ScanSearch size={16} aria-hidden />
                )}
                Start analysis
              </button>
              {busy && (
                <>
                  <button className="btn-secondary" onClick={() => abort.current?.abort()}>
                    <X size={16} aria-hidden /> Cancel
                  </button>
                  <span role="status" className="text-sm text-slate-600">
                    {statusText}
                  </span>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Mode 2: Cross-Image Splicing Test Workflow */}
      {mode === 'splicing_test' && (
        <div className="space-y-5">
          <SplicingTestWorkspace onRunTest={runSplicingTest} busy={busy} />
          {busy && (
            <div className="card p-4 flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-slate-700">
                <Loader2 size={16} className="animate-spin text-brand-600" />
                <span>{statusText}</span>
              </div>
              <button className="btn-secondary" onClick={() => abort.current?.abort()}>
                <X size={16} aria-hidden /> Cancel
              </button>
            </div>
          )}
        </div>
      )}

      {/* Global Error Banner */}
      {error && (
        <Alert
          kind="error"
          title="Analysis failed"
          action={
            <button
              className="btn-secondary shrink-0"
              onClick={() => {
                if (mode === 'splicing_test' && splicingMeta) {
                  runSplicingTest(splicingMeta)
                } else {
                  run()
                }
              }}
            >
              Retry
            </button>
          }
        >
          {error}
        </Alert>
      )}

      {/* Legacy Copy-Move Single Detector Results */}
      {!multi && mode === 'single' && result && image && urls.annotated && (
        <DetectionResults
          result={result}
          baseName={sanitizeBaseName(image.file.name)}
          urls={{
            original: image.url,
            annotated: urls.annotated,
            mask: urls.mask,
            heatmap: urls.heatmap,
          }}
        />
      )}

      {/* Multi-Method Analysis & Splicing Test Results */}
      {analysis && activeDisplayUrl && (
        <div className="space-y-5" aria-label="Analysis results">
          {splicingMeta && (
            <div className="card p-4 bg-slate-50 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div>
                <span className="font-semibold text-slate-800">Splicing Test Target: </span>
                <span className="text-slate-600">
                  {splicingMeta.backgroundName} + {splicingMeta.donorName}
                </span>
                {splicingMeta.isUntouchedControl && (
                  <span className="ml-2 font-bold text-blue-700 bg-blue-100 px-1.5 py-0.5 rounded uppercase text-[10px]">
                    Untouched Control
                  </span>
                )}
              </div>
              <span className="text-slate-500 uppercase font-semibold">
                Format: {splicingMeta.compositeFormat}
              </span>
            </div>
          )}

          <Alert kind="info" title="Read results independently">
            {analysis.disclaimer}
          </Alert>

          {analysis.results.map((r) => (
            <MethodResultPanel
              key={r.method}
              analysisId={analysis.analysis_id}
              result={r}
              originalUrl={activeDisplayUrl}
              urls={urls}
              onFallback={mode === 'single' ? () => run(COPY_MOVE_ONLY) : undefined}
            />
          ))}

          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-secondary" onClick={downloadReport}>
              <FileJson size={16} aria-hidden /> Download report (JSON)
            </button>
            <span className="text-xs text-slate-500">
              Results are kept in server memory for {Math.round(analysis.artifact_ttl_seconds / 60)} minutes.
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
