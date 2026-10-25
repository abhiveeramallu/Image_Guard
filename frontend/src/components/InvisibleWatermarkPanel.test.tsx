import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError } from '../services/api'
import { capabilities, png } from '../test/helpers'
import type { InvisibleVerifyResult } from '../types/api'
import InvisibleWatermarkPanel from './InvisibleWatermarkPanel'

const api = vi.hoisted(() => ({ getCapabilities: vi.fn(), embedInvisible: vi.fn(), verifyInvisible: vi.fn(), fetchArtifact: vi.fn() }))
vi.mock('../services/api', async (orig) => ({ ...(await orig<typeof import('../services/api')>()), ...api }))
const files = vi.hoisted(() => ({ downloadBlob: vi.fn() }))
vi.mock('../utils/files', async (orig) => ({
  ...(await orig<typeof import('../utils/files')>()),
  readImageDimensions: vi.fn().mockResolvedValue({ width: 640, height: 480 }),
  downloadBlob: files.downloadBlob,
}))

const verifyResult = (over: Partial<InvisibleVerifyResult> = {}): InvisibleVerifyResult => ({
  status: 'verified', status_reason: 'A payload with a valid integrity check (HMAC) made with this server\'s key was recovered.',
  owner: 'Acme-2026', integrity_verified: true, algorithm: { name: 'dct-qim-hmac', version: '1' },
  metrics: { bit_strength: 0.99 }, processing_ms: 120, warnings: [], limitations: ['Not proof of ownership.'], ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.getCapabilities.mockResolvedValue(capabilities())
})

const uploadTo = async (section: string, name = 'photo.png') => {
  const region = await screen.findByRole('region', { name: section })
  await userEvent.upload(within(region).getByTestId('file-input'), png(name))
  await within(region).findByText(name)
  return region
}

describe('InvisibleWatermarkPanel', () => {
  it('always states that an invisible watermark is not proof of ownership or integrity', async () => {
    render(<InvisibleWatermarkPanel />)
    expect(await screen.findByText(/does not prove who owns the image/)).toBeInTheDocument()
  })

  it('reports unavailable (with the reason) when the server has no key, and offers no controls', async () => {
    api.getCapabilities.mockResolvedValue(capabilities({ invisible_watermark: { available: false, experimental: false, reason: 'IMAGEGUARD_WATERMARK_KEY is not set on the server.', model: null, description: '' } }))
    render(<InvisibleWatermarkPanel />)
    expect(await screen.findByText('Invisible watermarking is unavailable')).toBeInTheDocument()
    expect(screen.getByText(/WATERMARK_KEY is not set/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Embed invisible watermark' })).not.toBeInTheDocument()
  })

  it('shows a server connection error', async () => {
    api.getCapabilities.mockRejectedValue(new ApiRequestError('Cannot reach the ImageGuard server.', 'network'))
    render(<InvisibleWatermarkPanel />)
    expect(await screen.findByText('Cannot reach the server')).toBeInTheDocument()
  })

  it('validates the owner string before enabling embed', async () => {
    render(<InvisibleWatermarkPanel />)
    const embed = await uploadTo('Embed invisible watermark')
    const btn = within(embed).getByRole('button', { name: /embed invisible watermark/i })
    expect(btn).toBeDisabled()
    await userEvent.type(within(embed).getByLabelText(/owner/i), 'café')
    expect(btn).toBeDisabled()
    await userEvent.clear(within(embed).getByLabelText(/owner/i))
    await userEvent.type(within(embed).getByLabelText(/owner/i), 'Acme-2026')
    expect(btn).toBeEnabled()
  })

  it('embeds with the chosen parameters, reports the result, and downloads the real artifact', async () => {
    api.embedInvisible.mockResolvedValue({
      watermark_id: 'w1', algorithm: { name: 'dct-qim-hmac', version: '1' }, owner: 'Acme-2026', integrity: 'HMAC',
      metrics: { psnr_db: 44.7, blocks: 4800, copies_per_bit: 33.3, quantization_step: 32 }, output_format: 'png',
      artifact: '/api/results/w1/watermarked.png', warnings: [], limitations: ['Resizing destroys it.'],
    })
    api.fetchArtifact.mockResolvedValue(new Blob(['png']))
    render(<InvisibleWatermarkPanel />)
    const embed = await uploadTo('Embed invisible watermark', 'holiday.png')
    await userEvent.type(within(embed).getByLabelText(/owner/i), 'Acme-2026')
    await userEvent.selectOptions(within(embed).getByLabelText('Strength'), 'high')
    await userEvent.click(within(embed).getByRole('button', { name: /embed invisible watermark/i }))
    expect(await within(embed).findByText('Invisible watermark embedded')).toBeInTheDocument()
    expect(api.embedInvisible.mock.calls[0].slice(1, 4)).toEqual(['Acme-2026', 'high', 'png'])
    expect(within(embed).getByText(/PSNR 44.7 dB/)).toBeInTheDocument()
    expect(within(embed).getByText(/No visible watermark was applied/)).toBeInTheDocument()
    await userEvent.click(within(embed).getByRole('button', { name: /download watermarked image/i }))
    await waitFor(() => expect(files.downloadBlob).toHaveBeenCalled())
    expect(api.fetchArtifact).toHaveBeenCalledWith('/api/results/w1/watermarked.png')
    expect(files.downloadBlob.mock.calls[0][1]).toBe('holiday_invisible.png')
  })

  it('shows embed errors and retries', async () => {
    api.embedInvisible.mockRejectedValueOnce(new ApiRequestError('Image is too small for a reliable invisible watermark.', 'image_too_small', 422))
    api.embedInvisible.mockResolvedValueOnce({ watermark_id: 'w', algorithm: { name: 'a', version: '1' }, owner: 'x', integrity: '', metrics: { psnr_db: 40, blocks: 1, copies_per_bit: 1, quantization_step: 24 }, output_format: 'png', artifact: '/a', warnings: [], limitations: [] })
    render(<InvisibleWatermarkPanel />)
    const embed = await uploadTo('Embed invisible watermark')
    await userEvent.type(within(embed).getByLabelText(/owner/i), 'x')
    await userEvent.click(within(embed).getByRole('button', { name: /embed invisible watermark/i }))
    expect(await within(embed).findByText('Embedding failed')).toBeInTheDocument()
    expect(within(embed).getByText(/too small/)).toBeInTheDocument()
    await userEvent.click(within(embed).getByRole('button', { name: 'Retry' }))
    expect(await within(embed).findByText('Invisible watermark embedded')).toBeInTheDocument()
  })

  it('displays a verified result with the recovered payload and integrity status', async () => {
    api.verifyInvisible.mockResolvedValue(verifyResult())
    render(<InvisibleWatermarkPanel />)
    const v = await uploadTo('Verify invisible watermark')
    await userEvent.click(within(v).getByRole('button', { name: /verify watermark/i }))
    expect(await within(v).findByText('Invisible watermark verified')).toBeInTheDocument()
    expect(within(v).getByText('Acme-2026')).toBeInTheDocument()
    expect(within(v).getByText('valid')).toBeInTheDocument()
  })

  it('displays inconclusive and not-detected outcomes without implying authenticity or tampering', async () => {
    api.verifyInvisible.mockResolvedValueOnce(verifyResult({ status: 'inconclusive', owner: null, integrity_verified: false, status_reason: 'integrity check failed' }))
    api.verifyInvisible.mockResolvedValueOnce(verifyResult({ status: 'not_detected', owner: null, integrity_verified: false, status_reason: 'No payload matching this server\'s key was found.' }))
    render(<InvisibleWatermarkPanel />)
    const v = await uploadTo('Verify invisible watermark')
    await userEvent.click(within(v).getByRole('button', { name: /verify watermark/i }))
    expect(await within(v).findByText('Verification inconclusive')).toBeInTheDocument()
    expect(within(v).queryByText('Recovered payload')).not.toBeInTheDocument()
    await userEvent.click(within(v).getByRole('button', { name: /verify watermark/i }))
    expect(await within(v).findByText(/Verification unsuccessful/)).toBeInTheDocument()
    expect(within(v).queryByText('Recovered payload')).not.toBeInTheDocument()
  })

  it('shows verification errors and retries', async () => {
    api.verifyInvisible.mockRejectedValueOnce(new ApiRequestError('Invisible watermarking is unavailable: key not set.', 'watermark_unavailable', 503))
    api.verifyInvisible.mockResolvedValueOnce(verifyResult())
    render(<InvisibleWatermarkPanel />)
    const v = await uploadTo('Verify invisible watermark')
    await userEvent.click(within(v).getByRole('button', { name: /verify watermark/i }))
    expect(await within(v).findByText('Verification failed to run')).toBeInTheDocument()
    await userEvent.click(within(v).getByRole('button', { name: 'Retry' }))
    expect(await within(v).findByText('Invisible watermark verified')).toBeInTheDocument()
  })
})
