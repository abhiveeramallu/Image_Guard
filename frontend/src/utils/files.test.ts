import { describe, expect, it } from 'vitest'
import { formatBytes, validateImageFile } from './files'
import { sanitizeBaseName } from './names'
import { png } from '../test/helpers'

describe('validateImageFile', () => {
  it('accepts PNG and JPEG', () => {
    expect(validateImageFile(png())).toBeNull()
    expect(validateImageFile(new File([new Uint8Array(10)], 'a.jpeg', { type: 'image/jpeg' }))).toBeNull()
  })
  it('rejects unsupported types', () => {
    expect(validateImageFile(new File([new Uint8Array(10)], 'a.gif', { type: 'image/gif' }))).toMatch(/JPEG or PNG/)
    expect(validateImageFile(new File([new Uint8Array(10)], 'a.pdf', { type: 'application/pdf' }))).toMatch(/Unsupported/)
  })
  it('rejects empty and oversized files', () => {
    expect(validateImageFile(png('a.png', 0))).toMatch(/empty/)
    expect(validateImageFile(png('a.png', 11 * 1024 * 1024))).toMatch(/limit/)
  })
})

describe('helpers', () => {
  it('formats sizes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.00 MB')
  })
  it('sanitizes download names', () => {
    expect(sanitizeBaseName('../my photo (1).PNG')).toBe('my_photo_1')
    expect(sanitizeBaseName('.png')).toBe('image')
  })
})
