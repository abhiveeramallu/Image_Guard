import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => cleanup())

let n = 0
URL.createObjectURL = vi.fn(() => `blob:mock/${++n}`)
URL.revokeObjectURL = vi.fn()
