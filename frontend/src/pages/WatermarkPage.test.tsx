import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError } from '../services/api'
import { capabilities, png } from '../test/helpers'
import WatermarkPage from './WatermarkPage'

const api = vi.hoisted(() => ({ applyWatermark: vi.fn(), getCapabilities: vi.fn() }))
vi.mock('../services/api', async (orig) => ({ ...(await orig<typeof import('../services/api')>()), ...api }))
const files = vi.hoisted(() => ({ downloadBlob: vi.fn() }))
vi.mock('../utils/files', async (orig) => ({
  ...(await orig<typeof import('../utils/files')>()),
  readImageDimensions: vi.fn().mockResolvedValue({ width: 1000, height: 800 }),
  downloadBlob: files.downloadBlob,
}))

const setup = () => render(<MemoryRouter><WatermarkPage /></MemoryRouter>)
const upload = async () => { await userEvent.upload(screen.getByTestId('file-input'), png('holiday.png')); await screen.findByText('Apply watermark') }
const lastCall = () => api.applyWatermark.mock.calls.at(-1)!

beforeEach(() => {
  vi.clearAllMocks()
  api.getCapabilities.mockResolvedValue(capabilities())
  api.applyWatermark.mockResolvedValue({ blob: new Blob(['wm']), filename: 'holiday_watermarked.png' })
})

describe('WatermarkPage', () => {
  it('renders a live preview using the default settings scaled to the image', async () => {
    setup()
    await upload()
    await waitFor(() => expect(api.applyWatermark).toHaveBeenCalled(), { timeout: 3000 })
    const [file, settings] = lastCall()
    expect(file.name).toBe('holiday.png')
    expect(settings).toMatchObject({ watermark_type: 'text', text: 'ImageGuard', position: 'bottom-right', layout: 'single', font_size: 50, margin: 20 })
    expect(await screen.findByAltText('Watermarked image')).toBeInTheDocument()
  })

  it('sends changed settings (opacity, text, layout, position, format)', async () => {
    setup()
    await upload()
    fireEvent.change(screen.getByLabelText('Opacity'), { target: { value: '30' } })
    await userEvent.clear(screen.getByLabelText('Watermark text'))
    await userEvent.type(screen.getByLabelText('Watermark text'), '(c) me')
    await userEvent.click(screen.getByRole('tab', { name: 'Tiled' }))
    await userEvent.selectOptions(screen.getByLabelText('Download format'), 'jpeg')
    await userEvent.click(screen.getByRole('button', { name: /apply watermark/i }))
    await waitFor(() => expect(lastCall()[1]).toMatchObject({ opacity: 0.3, text: '(c) me', layout: 'tiled', output_format: 'jpeg' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Single' }))
    await userEvent.click(screen.getByRole('radio', { name: 'top left' }))
    await userEvent.click(screen.getByRole('button', { name: /apply watermark/i }))
    await waitFor(() => expect(lastCall()[1]).toMatchObject({ layout: 'single', position: 'top-left' }))
  })

  it('switches between text and logo modes and requires a logo', async () => {
    setup()
    await upload()
    await userEvent.click(screen.getByRole('tab', { name: 'Logo' }))
    expect(screen.queryByLabelText('Watermark text')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /choose logo/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /apply watermark/i })).toBeDisabled()
    await userEvent.upload(screen.getByTestId('logo-input'), png('logo.png'))
    expect(screen.getByRole('button', { name: /apply watermark/i })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: /apply watermark/i }))
    await waitFor(() => expect(lastCall()[2]?.name).toBe('logo.png'))
    expect(lastCall()[1].watermark_type).toBe('logo')
  })

  it('rejects an oversized or wrong-type logo', async () => {
    setup()
    await upload()
    await userEvent.click(screen.getByRole('tab', { name: 'Logo' }))
    await userEvent.upload(screen.getByTestId('logo-input'), png('big.png', 3 * 1024 * 1024))
    expect(await screen.findByRole('alert')).toHaveTextContent(/limit/)
    expect(screen.getByRole('button', { name: /apply watermark/i })).toBeDisabled()
  })

  it('blocks rendering with empty text', async () => {
    setup()
    await upload()
    await userEvent.clear(screen.getByLabelText('Watermark text'))
    expect(screen.getByRole('button', { name: /apply watermark/i })).toBeDisabled()
    expect(screen.getByText(/Enter watermark text/)).toBeInTheDocument()
  })

  it('shows backend errors and retries', async () => {
    api.applyWatermark.mockRejectedValueOnce(new ApiRequestError('opacity must be between 0 and 1.', 'invalid_parameters', 422))
    setup()
    await upload()
    expect(await screen.findByText('Could not apply watermark', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText(/opacity must be/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByAltText('Watermarked image')).toBeInTheDocument()
  })

  it('downloads the rendered image with the server-provided filename, and disables download when stale', async () => {
    setup()
    await upload()
    const dl = screen.getByRole('button', { name: /download png/i })
    await waitFor(() => expect(dl).toBeEnabled(), { timeout: 3000 })
    await userEvent.click(dl)
    expect(files.downloadBlob).toHaveBeenCalledWith(expect.any(Blob), 'holiday_watermarked.png')
    fireEvent.change(screen.getByLabelText('Rotation'), { target: { value: '45' } })
    expect(screen.getByRole('button', { name: /download png/i })).toBeDisabled()
    expect(screen.getByText(/Settings changed/)).toBeInTheDocument()
  })
})

describe('WatermarkPage: visible vs invisible', () => {
  it('keeps visible and invisible watermarking as separate tools', async () => {
    setup()
    expect(screen.getByRole('tab', { name: 'Visible watermark' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('region', { name: 'Embed invisible watermark' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Invisible watermark' }))
    expect(await screen.findByRole('region', { name: 'Embed invisible watermark' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Verify invisible watermark' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Visible watermark' }))
    expect(screen.getByText(/can be cropped or edited out/)).toBeInTheDocument()
  })
})
