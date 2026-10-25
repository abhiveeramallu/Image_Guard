import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { capabilities } from './test/helpers'

const api = vi.hoisted(() => ({
  getCapabilities: vi.fn(),
  detectCopyMove: vi.fn(),
  analyzeImage: vi.fn(),
  renderWatermark: vi.fn(),
  fetchArtifact: vi.fn(),
}))

vi.mock('./services/api', async (orig) => ({
  ...(await orig<typeof import('./services/api')>()),
  ...api,
}))

describe('App navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getCapabilities.mockResolvedValue(capabilities())
  })

  it('renders sidebar navigation with only the four approved items', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    const nav = screen.getByRole('navigation', { name: /main/i })
    expect(nav).toBeInTheDocument()

    // Confirms retained items exist in sidebar
    expect(within(nav).getByRole('link', { name: /dashboard/i })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: /forgery detection/i })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: /watermark studio/i })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: /how it works/i })).toBeInTheDocument()

    // Confirms Manual Forgery Lab is completely absent
    expect(within(nav).queryByRole('link', { name: /manual forgery lab/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/manual forgery lab/i)).not.toBeInTheDocument()
  })

  it('navigates to Forgery Detection page when clicking sidebar link', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    const nav = screen.getByRole('navigation', { name: /main/i })
    const link = within(nav).getByRole('link', { name: /forgery detection/i })
    await user.click(link)

    // Heading of Forgery Detection page
    expect(await screen.findByRole('heading', { level: 1, name: /forgery detection/i })).toBeInTheDocument()
    expect(screen.getByText(/Drag & drop the image to analyse/i)).toBeInTheDocument()
  })

  it('navigates to Watermark Studio page when clicking sidebar link', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    const nav = screen.getByRole('navigation', { name: /main/i })
    const link = within(nav).getByRole('link', { name: /watermark studio/i })
    await user.click(link)

    expect(await screen.findByRole('heading', { level: 1, name: /watermark studio/i })).toBeInTheDocument()
    expect(screen.getByText(/Drag & drop the image to watermark/i)).toBeInTheDocument()
  })

  it('navigates from Dashboard cards to primary feature pages', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    // Dashboard card for detect
    const detectCard = screen.getByRole('link', { name: /detect forgery/i })
    expect(detectCard).toBeInTheDocument()
    await user.click(detectCard)
    expect(await screen.findByRole('heading', { level: 1, name: /forgery detection/i })).toBeInTheDocument()
  })

  it('redirects removed /forgery-lab and /attack-lab routes cleanly to Dashboard', () => {
    render(
      <MemoryRouter initialEntries={['/forgery-lab']}>
        <App />
      </MemoryRouter>,
    )

    // Falls back to Dashboard
    expect(screen.getByRole('heading', { level: 1, name: /imageguard/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /detect forgery/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /watermark image/i })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /manual forgery lab/i })).not.toBeInTheDocument()
  })
})
