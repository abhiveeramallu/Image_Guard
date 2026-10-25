import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ImageDropzone from './ImageDropzone'
import { png } from '../test/helpers'

describe('ImageDropzone', () => {
  it('passes the chosen file to the handler', async () => {
    const onFile = vi.fn()
    render(<ImageDropzone onFile={onFile} />)
    const f = png()
    await userEvent.upload(screen.getByTestId('file-input'), f)
    expect(onFile).toHaveBeenCalledWith(f)
  })
  it('accepts a dropped file', () => {
    const onFile = vi.fn()
    const { container } = render(<ImageDropzone onFile={onFile} />)
    const f = png()
    fireEvent.drop(container.firstChild!.firstChild!, { dataTransfer: { files: [f] } })
    expect(onFile).toHaveBeenCalledWith(f)
  })
  it('shows an error message', () => {
    render(<ImageDropzone onFile={() => {}} error="Unsupported file type." />)
    expect(screen.getByRole('alert')).toHaveTextContent('Unsupported file type.')
  })
})
