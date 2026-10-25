export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png']
export const ACCEPT_ATTR = 'image/jpeg,image/png,.jpg,.jpeg,.png'

export function validateImageFile(file: File, maxBytes = MAX_UPLOAD_BYTES): string | null {
  const okType = ACCEPTED_TYPES.includes(file.type) || /\.(jpe?g|png)$/i.test(file.name)
  if (!okType) return 'Unsupported file type. Please choose a JPEG or PNG image.'
  if (file.size === 0) return 'This file is empty.'
  if (file.size > maxBytes) return `File is ${formatBytes(file.size)}; the limit is ${formatBytes(maxBytes)}.`
  return null
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

export function readImageDimensions(url: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight })
    img.onerror = () => reject(new Error('The browser could not decode this image.'))
    img.src = url
  })
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
