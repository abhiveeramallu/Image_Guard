import { useCallback, useEffect, useState } from 'react'
import { readImageDimensions, validateImageFile } from '../utils/files'

export interface LoadedImage { file: File; url: string; width: number; height: number }

/** Holds one selected image: validates it, creates a preview URL, and revokes the URL on replace/unmount. */
export function useImageFile() {
  const [image, setImage] = useState<LoadedImage | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => () => { if (image) URL.revokeObjectURL(image.url) }, [image])

  const select = useCallback(async (file: File) => {
    const problem = validateImageFile(file)
    if (problem) { setError(problem); return false }
    const url = URL.createObjectURL(file)
    try {
      const { width, height } = await readImageDimensions(url)
      setImage({ file, url, width, height })
      setError(null)
      return true
    } catch {
      URL.revokeObjectURL(url)
      setError('This file could not be read as an image. It may be corrupted.')
      return false
    }
  }, [])

  const clear = useCallback(() => { setImage(null); setError(null) }, [])
  return { image, error, select, clear, setError }
}
