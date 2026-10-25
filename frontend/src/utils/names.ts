export function sanitizeBaseName(filename: string): string {
  const stem = filename.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '')
  return stem.slice(0, 60) || 'image'
}
