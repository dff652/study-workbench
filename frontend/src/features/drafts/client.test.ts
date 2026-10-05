import { afterEach, describe, expect, it, vi } from 'vitest'
import { savePrivateDraft } from './client'

describe('private draft response validation', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('does not classify a 409 without a draft as a recoverable conflict', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ schema_version: 'swb.api.v1', error: { code: 'draft_conflict' } }, { status: 409 })))
    await expect(savePrivateDraft('draft-a', 'home-a', {
      expected_version: 0,
      base_stamp: 'base',
      payload: { value: 'kept' },
      request_key: 'request-a',
    }, 'csrf')).rejects.toMatchObject({ code: 'missing_draft' })
  })

  it('rejects other 409 errors even when a draft field is present', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ schema_version: 'swb.api.v1', error: { code: 'request_key_conflict' }, draft: null }, { status: 409 })))
    await expect(savePrivateDraft('draft-a', 'home-a', {
      expected_version: 0, base_stamp: 'base', payload: { value: 'kept' }, request_key: 'request-a',
    }, 'csrf')).rejects.toMatchObject({ code: 'request_key_conflict' })
  })

  it('returns the current row only for a draft conflict', async () => {
    const draft = { key: 'draft-a', version: 2, base_stamp: 'base', payload: { value: 'other window' }, updated_at: '2026-10-05T00:00:00Z' }
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ schema_version: 'swb.api.v1', error: { code: 'draft_conflict' }, draft }, { status: 409 })))
    await expect(savePrivateDraft('draft-a', 'home-a', {
      expected_version: 1, base_stamp: 'base', payload: { value: 'kept' }, request_key: 'request-a',
    }, 'csrf')).resolves.toEqual({ kind: 'conflict', draft })
  })
})
