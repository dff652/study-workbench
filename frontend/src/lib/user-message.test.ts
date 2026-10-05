import { afterEach, describe, expect, it, vi } from 'vitest'
import { getJson, ApiError } from '../api'
import { userMessage } from './user-message'

describe('user-facing errors', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps actionable business reasons and unknown evidence visible', () => {
    expect(userMessage('题干尚未核定，请先核对原图。')).toBe('题干尚未核定，请先核对原图。')
    expect(userMessage('来源不明，不能认定独立掌握。')).toBe('来源不明，不能认定独立掌握。')
  })

  it('does not expose protocol, hashes or object content from a rejected API request', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json({ schema_version: 'swb.api.v1', error: { code: 'invalid_input', message: 'schema_version must be swb.skill-import.v1: {"payload":"private"}' } }, { status: 400 }))))
    const error = await getJson('/api/v1/materials/', new AbortController().signal).catch((reason: unknown) => reason)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 400, code: 'invalid_input', message: '请求未完成，请核对输入后重试。' })
    expect(userMessage('原图 SHA-256: ' + 'a'.repeat(64))).toBe('操作未完成，请核对输入后重试。')
  })

  it('turns network failures into a retry instruction', () => {
    expect(userMessage('Failed to fetch')).toBe('连接暂时不可用，请检查网络后重试。')
    expect(userMessage('Cannot read properties of null')).toBe('操作未完成，请核对输入后重试。')
    expect(userMessage('已拒绝 question_revision_id 参数')).toBe('操作未完成，请核对输入后重试。')
  })
})
