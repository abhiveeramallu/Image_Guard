import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { capabilities, png } from '../test/helpers'
import ManualForgeryLabPage from './ManualForgeryLabPage'

const api = vi.hoisted(() => ({
  getCapabilities: vi.fn(),
  analyzeManualForgery: vi.fn(),
  fetchArtifact: vi.fn(),
}))

vi.mock('../services/api', async (orig) => ({
  ...(await orig<typeof import('../services/api')>()),
  ...api,
}))

const files = vi.hoisted(() => ({
  downloadBlob: vi.fn(),
  readImageDimensions: vi.fn(),
}))

vi.mock('../utils/files', async (orig) => ({
  ...(await orig<typeof import('../utils/files')>()),
  downloadBlob: files.downloadBlob,
  readImageDimensions: files.readImageDimensions,
}))

// Mock HTMLCanvasElement methods for JSDOM
const dummyImageData = {
  data: new Uint8ClampedArray(800 * 600 * 4),
  width: 800,
  height: 600,
  colorSpace: 'srgb' as PredefinedColorSpace,
}

const mockContext2D = {
  drawImage: vi.fn(),
  fillRect: vi.fn(),
  clearRect: vi.fn(),
  getImageData: vi.fn(() => dummyImageData),
  putImageData: vi.fn(),
  beginPath: vi.fn(),
  arc: vi.fn(),
  fill: vi.fn(),
  stroke: vi.fn(),
  moveTo: vi.fn(),
  lineTo: vi.fn(),
  clip: vi.fn(),
  save: vi.fn(),
  restore: vi.fn(),
  setLineDash: vi.fn(),
  fillText: vi.fn(),
  lineWidth: 1,
  strokeStyle: '#000',
  fillStyle: '#000',
  lineCap: 'butt',
  lineJoin: 'miter',
  font: '10px sans-serif',
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getCapabilities.mockResolvedValue(capabilities())
  files.readImageDimensions.mockResolvedValue({ width: 800, height: 600 })

  class MockImage {
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    naturalWidth = 800
    naturalHeight = 600
    set src(_: string) {
      setTimeout(() => this.onload?.(), 0)
    }
  }
  window.Image = MockImage as any
  ;(globalThis as any).Image = MockImage

  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(mockContext2D) as any
  HTMLCanvasElement.prototype.toBlob = vi.fn((cb) => {
    cb(new Blob(['test-png-blob'], { type: 'image/png' }))
  }) as any
})

const mockAnalysisResult = {
  experiment_id: 'exp-manual-1',
  image: { width: 800, height: 600, format: 'PNG' },
  baseline: {
    width: 800,
    height: 600,
    format: 'PNG',
    has_visible_watermark: false,
    has_invisible_watermark: false,
  },
  history: [],
  ground_truth: {
    has_mask: true,
    regions: [{ type: 'brush_scratch', pixel_count: 500 }],
  },
  detection_results: [
    {
      method: 'copy_move',
      method_name: 'ORB Copy-Move Detector',
      category: 'copy_move',
      status: 'candidate_regions_found',
      status_reason: '1 candidate region cluster detected',
      region_count: 1,
      regions: [{ bbox: { x: 50, y: 50, width: 80, height: 80 } }],
      metrics: { keypoints: 420 },
      processing_ms: 120,
      artifacts: { overlay: '/api/forgery-lab/artifacts/exp-manual-1/copy_move.overlay.png' },
    },
    {
      method: 'splicing',
      method_name: 'Splicing Detector (ELA & Noise)',
      category: 'splicing',
      status: 'no_candidate_regions_found',
      status_reason: 'No high-confidence splicing regions found',
      region_count: 0,
      regions: [],
      metrics: {},
      processing_ms: 85,
      artifacts: {},
    },
  ],
  watermark_verification: {
    status: 'verified',
    status_reason: 'Invisible watermark verified successfully.',
    owner: 'IMG-01',
    integrity_verified: true,
  },
  evaluation: [
    {
      method: 'copy_move',
      metrics: {
        tp: 450,
        fp: 50,
        fn: 50,
        tn: 479450,
        precision: 0.9,
        recall: 0.9,
        f1: 0.9,
        iou: 0.818,
        semantics_note: 'Pixel-level overlap with ground truth',
      },
      notes: 'Evaluated against ground truth',
    },
  ],
  answers: {
    question_a: 'Simulated',
    question_b: 'Simulated',
    question_c: 'Simulated',
  },
  artifacts: {
    modified_image: '/api/forgery-lab/artifacts/exp-manual-1/modified.png',
    ground_truth_mask: '/api/forgery-lab/artifacts/exp-manual-1/ground_truth.png',
    'copy_move.overlay': '/api/forgery-lab/artifacts/exp-manual-1/copy_move.overlay.png',
  },
  report_json: '/api/forgery-lab/reports/exp-manual-1?format=json',
  report_html: '/api/forgery-lab/reports/exp-manual-1?format=html',
  processing_ms: 205,
  warnings: [],
  disclaimer: 'Indicators for review, not proof of authenticity.',
}

describe('ManualForgeryLabPage', () => {
  it('renders the header and three panels', async () => {
    render(
      <MemoryRouter>
        <ManualForgeryLabPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('Manual Forgery Lab')).toBeInTheDocument()
    expect(screen.getByText(/Panel A: Original Image/i)).toBeInTheDocument()
    expect(screen.getByText(/Panel B: Editing Canvas/i)).toBeInTheDocument()
    expect(screen.getByText(/Panel C: Forensic Detection/i)).toBeInTheDocument()
  })

  it('uploads an image and displays file metadata and canvas tools', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ManualForgeryLabPage />
      </MemoryRouter>,
    )

    const file = png('sample_photo.png', 4096)
    const input = screen.getByTestId('file-input')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText('sample_photo.png')).toBeInTheDocument()
      expect(screen.getByText(/800 × 600 px/i)).toBeInTheDocument()
    })

    // Altered pixel counter defaults to baseline
    expect(screen.getByText(/Clean Baseline/i)).toBeInTheDocument()

    // Tools exist
    expect(screen.getByText(/Brush \/ Scratch/i)).toBeInTheDocument()
    expect(screen.getByText(/Copy-Move Tool/i)).toBeInTheDocument()
    expect(screen.getByText(/Eraser/i)).toBeInTheDocument()
  })

  it('switches between tools and adjusts settings', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ManualForgeryLabPage />
      </MemoryRouter>,
    )

    const file = png('sample_photo.png', 4096)
    const input = screen.getByTestId('file-input')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText('sample_photo.png')).toBeInTheDocument()
    })

    // Click Copy-Move Tool
    await user.click(screen.getByText(/Copy-Move Tool/i))
    expect(screen.getByText(/Drag a rectangle on the canvas to select source region/i)).toBeInTheDocument()

    // Click Eraser
    await user.click(screen.getByText(/Eraser/i))
    expect(screen.getByText(/Eraser Size:/i)).toBeInTheDocument()
  })

  it('runs forgery detection and displays results and metrics', async () => {
    const user = userEvent.setup()
    api.analyzeManualForgery.mockResolvedValue(mockAnalysisResult)
    api.fetchArtifact.mockResolvedValue(new Blob(['mock-data']))

    render(
      <MemoryRouter>
        <ManualForgeryLabPage />
      </MemoryRouter>,
    )

    const file = png('sample_photo.png', 4096)
    const input = screen.getByTestId('file-input')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText('sample_photo.png')).toBeInTheDocument()
    })

    const runBtn = screen.getByRole('button', { name: /Run Forgery Detection/i })
    await user.click(runBtn)

    await waitFor(() => {
      expect(api.analyzeManualForgery).toHaveBeenCalled()
      expect(screen.getByText(/ORB Copy-Move Detector/i)).toBeInTheDocument()
      expect(screen.getByText(/^candidate regions found$/i)).toBeInTheDocument()
      expect(screen.getByText(/Ground-Truth Evaluation/i)).toBeInTheDocument()
      expect(screen.getByText('JSON Report')).toBeInTheDocument()
      expect(screen.getByText('HTML Report')).toBeInTheDocument()
    })

    // Click HTML report download
    const htmlBtn = screen.getByRole('button', { name: /HTML Report/i })
    await user.click(htmlBtn)
    await waitFor(() => {
      expect(api.fetchArtifact).toHaveBeenCalledWith('/api/forgery-lab/reports/exp-manual-1?format=html')
      expect(files.downloadBlob).toHaveBeenCalled()
    })
  })

  it('displays error when analysis fails', async () => {
    const user = userEvent.setup()
    api.analyzeManualForgery.mockRejectedValue(new Error('Backend processing timeout'))

    render(
      <MemoryRouter>
        <ManualForgeryLabPage />
      </MemoryRouter>,
    )

    const file = png('sample_photo.png', 4096)
    const input = screen.getByTestId('file-input')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText('sample_photo.png')).toBeInTheDocument()
    })

    const runBtn = screen.getByRole('button', { name: /Run Forgery Detection/i })
    await user.click(runBtn)

    await waitFor(() => {
      expect(screen.getByText(/Backend processing timeout/i)).toBeInTheDocument()
    })
  })

  it('resets canvas to original and clears results when reset is clicked', async () => {
    const user = userEvent.setup()
    api.analyzeManualForgery.mockResolvedValue(mockAnalysisResult)
    api.fetchArtifact.mockResolvedValue(new Blob(['mock-data']))

    render(
      <MemoryRouter>
        <ManualForgeryLabPage />
      </MemoryRouter>,
    )

    const file = png('sample_photo.png', 4096)
    const input = screen.getByTestId('file-input')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText('sample_photo.png')).toBeInTheDocument()
    })

    // Run detection
    const runBtn = screen.getByRole('button', { name: /Run Forgery Detection/i })
    await user.click(runBtn)
    await waitFor(() => {
      expect(screen.getByText(/ORB Copy-Move Detector/i)).toBeInTheDocument()
    })

    // Click Reset to Original
    const resetBtn = screen.getByTitle(/Reset all modifications back to pristine original/i)
    await user.click(resetBtn)

    // Verify stale results are cleared
    expect(screen.queryByText(/ORB Copy-Move Detector/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Clean Baseline/i)).toBeInTheDocument()
  })
})
