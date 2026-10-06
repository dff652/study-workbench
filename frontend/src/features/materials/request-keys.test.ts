import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeRequestKey, requestKeyFor, type RequestKeyState } from './request-keys'

describe('request identifiers on HTTP', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses secure random bytes when randomUUID is unavailable', () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => { bytes.fill(255); return bytes })
    vi.stubGlobal('crypto', { getRandomValues })
    expect(makeRequestKey()).toBe('ffffffff-ffff-4fff-bfff-ffffffffffff')
    expect(getRandomValues).toHaveBeenCalledOnce()
  })

  it('keeps the same key for retry, and changes it when the request changes', () => {
    let counter = 0
    vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => { bytes.fill(++counter); return bytes } })
    const ref = { current: null as RequestKeyState }
    const first = requestKeyFor(ref, 'first')
    expect(requestKeyFor(ref, 'first')).toBe(first)
    expect(requestKeyFor(ref, 'changed')).not.toBe(first)
  })

  it('rejects browsers without either secure random API', () => {
    vi.stubGlobal('crypto', {})
    expect(makeRequestKey).toThrow('无法生成安全的请求标识')
  })
})
