import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError } from '../services/api'
import { analysisResult, capabilities, detectionResult, methodResult, png } from '../test/helpers'
import type { DetectionResult } from '../types/api'
import DetectionPage from './DetectionPage'

const api = vi.hoisted(() => ({ detectCopyMove: vi.fn(), fetchArtifact: vi.fn(), getCapabilities: vi.fn(), analyzeImage: vi.fn(), fetchThresholdLayer: vi.fn() }))
vi.mock('../services/api', async (orig) => ({ ...(await orig<typeof import('../services/api')>()), ...api }))
const files = vi.hoisted(() => ({ downloadBlob: vi.fn() }))
vi.mock('../utils/files', async (orig) => ({
  ...(await orig<typeof import('../utils/files')>()),
  readImageDimensions: vi.fn().mockResolvedValue({ width: 800, height: 600 }),
  downloadBlob: files.downloadBlob,
}))

const setup = () => render(<MemoryRouter><DetectionPage /></MemoryRouter>)
const upload = async (f = png()) => { await userEvent.upload(screen.getByTestId('file-input'), f); await screen.findByText('Start analysis') }

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchArtifact.mockResolvedValue(new Blob(['x']))
  api.getCapabilities.mockResolvedValue(capabilities())
})

describe('DetectionPage', () => {
  it('rejects unsupported files with a clear message', async () => {
    setup()
    await userEvent.upload(screen.getByTestId('file-input'), new File([new Uint8Array(5)], 'a.gif', { type: 'image/gif' }), { applyAccept: false })
    expect(await screen.findByRole('alert')).toHaveTextContent(/JPEG or PNG/)
    expect(screen.queryByText('Start analysis')).not.toBeInTheDocument()
  })

  it('shows file name, dimensions and size after upload, and lets the user remove it', async () => {
    setup()
    await upload(png('evidence.png', 2048))
    expect(screen.getByText('evidence.png')).toBeInTheDocument()
    expect(screen.getByText('800 × 600')).toBeInTheDocument()
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /remove/i }))
    expect(screen.getByText(/drag & drop/i)).toBeInTheDocument()
  })

  it('sends the chosen settings, shows loading, then renders real result data', async () => {
    let resolve!: (r: DetectionResult) => void
    api.detectCopyMove.mockReturnValue(new Promise((r) => { resolve = r }))
    setup()
    await upload()
    fireEvent.change(screen.getByLabelText('Minimum matches per region'), { target: { value: '12' } })
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))

    expect(screen.getByRole('button', { name: /start analysis/i })).toBeDisabled()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(api.detectCopyMove.mock.calls[0][1]).toMatchObject({ min_matches: 12, ratio: 0.75 })

    await act(async () => { resolve(detectionResult()) })
    expect(await screen.findByText('Candidate copy-move regions detected')).toBeInTheDocument()
    const stats = within(screen.getByText('Statistics').parentElement!)
    expect(stats.getByText('4999')).toBeInTheDocument()
    expect(stats.getByText('37')).toBeInTheDocument()
    expect(stats.getByText('199 ms')).toBeInTheDocument()
    expect(screen.getByText('92, 92, 129, 112')).toBeInTheDocument()
    expect(api.fetchArtifact).toHaveBeenCalledTimes(3)
  })

  it('switches between original, annotated, mask and heatmap views', async () => {
    api.detectCopyMove.mockResolvedValue(detectionResult())
    setup()
    await upload()
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    await screen.findByText('Candidate copy-move regions detected')
    expect(screen.getByAltText('annotated view')).toBeInTheDocument()
    for (const [tab, alt] of [['Mask', 'mask view'], ['Heatmap', 'heatmap view'], ['Original', 'original view']] as const) {
      await userEvent.click(screen.getByRole('tab', { name: tab }))
      expect(screen.getByAltText(alt)).toBeInTheDocument()
    }
    await userEvent.click(screen.getByRole('tab', { name: 'Side by side' }))
    expect(screen.getByAltText('Original image')).toBeInTheDocument()
    expect(screen.getByAltText('Annotated image')).toBeInTheDocument()
  })

  it('never presents a negative result as proof of authenticity', async () => {
    api.detectCopyMove.mockResolvedValue(detectionResult({
      status: 'no_candidate_regions_found', status_reason: 'Only 3 descriptor matches survived filtering.',
      regions: [], candidate_region_count: 0, matches_retained: 0,
    }))
    setup()
    await upload()
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    expect(await screen.findByText(/No candidate regions detected by the selected method/)).toBeInTheDocument()
    expect(screen.getByText(/does not show that the image is authentic/)).toBeInTheDocument()
  })

  it('renders the inconclusive status', async () => {
    api.detectCopyMove.mockResolvedValue(detectionResult({ status: 'inconclusive', status_reason: 'Too little texture.', regions: [] }))
    setup()
    await upload()
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    expect(await screen.findByText('Analysis inconclusive')).toBeInTheDocument()
  })

  it('shows an error with a retry that re-runs the analysis', async () => {
    api.detectCopyMove.mockRejectedValueOnce(new ApiRequestError('Cannot reach the ImageGuard server.', 'network'))
    api.detectCopyMove.mockResolvedValueOnce(detectionResult())
    setup()
    await upload()
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    expect(await screen.findByText('Analysis failed')).toBeInTheDocument()
    expect(screen.getByText(/Cannot reach/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Candidate copy-move regions detected')).toBeInTheDocument()
    expect(api.detectCopyMove).toHaveBeenCalledTimes(2)
  })

  it('downloads artifacts through the backend', async () => {
    api.detectCopyMove.mockResolvedValue(detectionResult())
    setup()
    await upload(png('my photo.png'))
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    await screen.findByText('Candidate copy-move regions detected')
    api.fetchArtifact.mockClear()
    await userEvent.click(screen.getByRole('button', { name: /report \(json\)/i }))
    await waitFor(() => expect(files.downloadBlob).toHaveBeenCalled())
    expect(api.fetchArtifact).toHaveBeenCalledWith('/r.json')
    expect(files.downloadBlob.mock.calls[0][1]).toBe('my_photo_report.json')
  })

  it('revokes preview object URLs when the image is replaced', async () => {
    setup()
    await upload()
    const before = (URL.revokeObjectURL as ReturnType<typeof vi.fn>).mock.calls.length
    await userEvent.click(screen.getByRole('button', { name: /remove/i }))
    expect((URL.revokeObjectURL as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(before)
  })
})

describe('DetectionPage: multi-method analysis', () => {
  const pick = async (label: RegExp) => { await userEvent.click(await screen.findByRole('checkbox', { name: label })) }

  it('only enables available methods, marks splicing experimental, and explains why localization is unavailable', async () => {
    setup()
    await upload()
    expect(await screen.findByText('Experimental')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /model-based localization/i })).toBeDisabled()
    expect(screen.getByText(/Unavailable: No localization model is configured/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /copy-move detection/i })).toBeChecked()
  })

  it('disables non-baseline methods when the server cannot be reached', async () => {
    api.getCapabilities.mockRejectedValue(new ApiRequestError('Cannot reach the ImageGuard server.', 'network'))
    setup()
    await upload()
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /splicing heuristic/i })).toBeDisabled())
    expect(screen.getByRole('checkbox', { name: /copy-move detection/i })).toBeEnabled()
  })

  it('runs selected methods through the analyze endpoint and renders each result independently', async () => {
    api.analyzeImage.mockResolvedValue(analysisResult([
      methodResult({ method: 'copy_move', category: 'copy_move', evidence_type: 'feature_match_regions', experimental: false,
        method_name: 'orb-hamming-ransac', status: 'no_candidate_regions_found', status_reason: 'Only 3 matches.', region_count: 0, regions: [],
        artifacts: { annotated: '/a', mask: '/cm', heatmap: '/ch' }, threshold: null, threshold_semantics: null }),
      methodResult(),
    ]))
    setup()
    await upload()
    await pick(/splicing heuristic/i)
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    expect(await screen.findByRole('region', { name: /Splicing heuristic result/ })).toBeInTheDocument()
    expect(api.analyzeImage.mock.calls[0][1]).toEqual(['copy_move', 'splicing'])
    expect(api.detectCopyMove).not.toHaveBeenCalled()
    const cm = screen.getByRole('region', { name: /Copy-move detection \(ORB\) result/ })
    expect(within(cm).getByText('No candidate regions detected by this method')).toBeInTheDocument()
    expect(within(cm).getByText(/does not show that the image is authentic/)).toBeInTheDocument()
    const sp = screen.getByRole('region', { name: /Splicing heuristic result/ })
    expect(within(sp).getByText('Possible local inconsistencies (heuristic)')).toBeInTheDocument()
    expect(within(sp).getByText('Experimental')).toBeInTheDocument()
    expect(within(sp).getByText(/not a probability/)).toBeInTheDocument()
    expect(api.fetchArtifact).toHaveBeenCalledWith('/o', expect.anything())
  })

  it('shows an explicit unavailable state (no fabricated maps) and can fall back to copy-move', async () => {
    api.getCapabilities.mockResolvedValue(capabilities({ methods: { ...capabilities().methods,
      localization: { available: true, experimental: false, reason: null, model: null, description: '' } } }))
    api.analyzeImage.mockResolvedValue(analysisResult([methodResult({
      method: 'localization', category: 'local_manipulation', evidence_type: 'model_probability_map', status: 'unavailable',
      status_reason: 'The model file does not exist.', experimental: false, artifacts: {}, regions: [], region_count: 0, threshold: null, threshold_semantics: null })]))
    api.detectCopyMove.mockResolvedValue(detectionResult())
    setup()
    await upload()
    await pick(/model-based localization/i)
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    const panel = await screen.findByRole('region', { name: /Model-based localization result/ })
    expect(within(panel).getByText('Method unavailable')).toBeInTheDocument()
    expect(within(panel).getByText('The model file does not exist.')).toBeInTheDocument()
    expect(within(panel).queryByRole('tab')).not.toBeInTheDocument()
    expect(within(panel).queryByRole('img')).not.toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('button', { name: /run copy-move detection instead/i }))
    expect(await screen.findByText('Candidate copy-move regions detected')).toBeInTheDocument()
    expect(api.detectCopyMove).toHaveBeenCalled()
  })

  it('shows model information for a localization result and re-thresholds through the backend', async () => {
    const model = { id: 'org/m', name: 'Test model', version: '2', source: 'https://example.org/w', license: 'MIT', intended_use: 'x', output_semantics: 'probability', provider: 'CPUExecutionProvider' }
    api.getCapabilities.mockResolvedValue(capabilities({ methods: { ...capabilities().methods,
      localization: { available: true, experimental: false, reason: null, model, description: '' } } }))
    api.analyzeImage.mockResolvedValue(analysisResult([methodResult({
      method: 'localization', category: 'local_manipulation', evidence_type: 'model_probability_map', experimental: false, model,
      method_name: 'onnx-manipulation-localization', method_version: '1.0.0', threshold: 0.5,
      threshold_semantics: 'model-defined per-pixel manipulation probability' })]))
    api.fetchThresholdLayer.mockResolvedValue({ blob: new Blob(['l']), regionCount: 3 })
    setup()
    await upload()
    await pick(/model-based localization/i)
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    const panel = await screen.findByRole('region', { name: /Model-based localization result/ })
    expect(within(panel).getByText(/Test model \(v2\)/)).toBeInTheDocument()
    expect(within(panel).getByText('MIT')).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('tab', { name: 'Adjust threshold' }))
    fireEvent.change(within(panel).getByLabelText('Visualization threshold'), { target: { value: '0.8' } })
    await waitFor(() => expect(api.fetchThresholdLayer).toHaveBeenLastCalledWith('an1', 'localization', 0.8, expect.anything()), { timeout: 2000 })
    expect(await within(panel).findByText('3 regions at this threshold')).toBeInTheDocument()
  })

  it('shows a failed method as failed, with no output images', async () => {
    api.analyzeImage.mockResolvedValue(analysisResult([methodResult({ status: 'failed', status_reason: 'The method failed while processing this image.', artifacts: {}, regions: [], region_count: 0 })]))
    setup()
    await upload()
    await pick(/splicing heuristic/i)
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    const panel = await screen.findByRole('region', { name: /Splicing heuristic result/ })
    expect(within(panel).getByText('Method failed')).toBeInTheDocument()
    expect(within(panel).queryByRole('img')).not.toBeInTheDocument()
  })

  it('"All supported methods" selects only the available ones and downloads the combined report', async () => {
    api.analyzeImage.mockResolvedValue(analysisResult([methodResult()]))
    setup()
    await upload()
    await userEvent.click(await screen.findByRole('button', { name: 'All supported methods' }))
    expect(screen.getByRole('checkbox', { name: /splicing heuristic/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /model-based localization/i })).not.toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    await screen.findByRole('region', { name: /Splicing heuristic result/ })
    api.fetchArtifact.mockClear()
    await userEvent.click(screen.getByRole('button', { name: /download report/i }))
    await waitFor(() => expect(files.downloadBlob).toHaveBeenCalled())
    expect(api.fetchArtifact).toHaveBeenCalledWith('/api/results/an1/analysis.json')
  })

  it('reports analyze errors and retries', async () => {
    api.analyzeImage.mockRejectedValueOnce(new ApiRequestError('The server is busy.', 'server_busy', 503))
    api.analyzeImage.mockResolvedValueOnce(analysisResult([methodResult()]))
    setup()
    await upload()
    await pick(/splicing heuristic/i)
    await userEvent.click(screen.getByRole('button', { name: /start analysis/i }))
    expect(await screen.findByText('Analysis failed')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('region', { name: /Splicing heuristic result/ })).toBeInTheDocument()
  })
})
