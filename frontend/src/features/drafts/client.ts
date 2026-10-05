import { ApiError } from '../../api'

export type PrivateDraft<T> = { key: string; version: number; base_stamp: string; payload: T; updated_at: string }

export async function loadPrivateDraft<T>(key: string, householdId: string, signal?: AbortSignal) {
  const response = await fetch(draftUrl('drafts', key, householdId), { method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal })
  const body = await readEnvelope<unknown>(response)
  return draftFromEnvelope<T>(body, response.status)
}

export async function savePrivateDraft<T>(key: string, householdId: string, input: {
  expected_version: number
  base_stamp: string
  payload: T
  request_key: string
}, csrfToken: string): Promise<{ kind: 'saved'; draft: PrivateDraft<T> } | { kind: 'conflict'; draft: PrivateDraft<T> | null }> {
  const response = await fetch(draftUrl('draft-save', key, householdId), {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
    body: JSON.stringify(input),
  })
  if (response.status === 409) {
    const body = await readEnvelope<unknown>(response, true)
    const error = (body as { error?: { code?: string; message?: string } }).error
    if (error?.code !== 'draft_conflict') {
      throw new ApiError(error?.message || '草稿暂时无法保存，请保留当前输入。', response.status, error?.code || 'draft_failed')
    }
    return { kind: 'conflict', draft: draftFromEnvelope<T>(body, response.status) }
  }
  const body = await readEnvelope<unknown>(response)
  const draft = draftFromEnvelope<T>(body, response.status)
  if (!draft) throw new ApiError('草稿服务没有返回已保存内容，请保留当前输入。', response.status, 'missing_draft')
  return { kind: 'saved', draft }
}

function draftFromEnvelope<T>(body: unknown, status: number): PrivateDraft<T> | null {
  if (!body || typeof body !== 'object' || !Object.hasOwn(body, 'draft')) {
    throw new ApiError('草稿服务响应缺少草稿内容，请保留当前输入。', status, 'missing_draft')
  }
  const draft = (body as { draft: unknown }).draft
  if (draft === null) return null
  if (!draft || typeof draft !== 'object' || Array.isArray(draft)) {
    throw new ApiError('草稿服务返回了无法识别的内容，请保留当前输入。', status, 'invalid_draft')
  }
  const value = draft as Record<string, unknown>
  if (typeof value.key !== 'string' || !value.key
    || !Number.isSafeInteger(value.version) || (value.version as number) < 0
    || typeof value.base_stamp !== 'string' || typeof value.updated_at !== 'string'
    || !Object.hasOwn(value, 'payload')) {
    throw new ApiError('草稿服务返回了无法识别的内容，请保留当前输入。', status, 'invalid_draft')
  }
  return draft as PrivateDraft<T>
}

async function readEnvelope<T>(response: Response, allowConflict = false): Promise<T> {
  let body: unknown
  try { body = await response.json() } catch { throw new ApiError('草稿服务返回了无法读取的响应，请保留当前输入。', response.status, 'invalid_json') }
  if (!response.ok && !(allowConflict && response.status === 409)) {
    const error = (body && typeof body === 'object' ? body : {}) as { error?: { code?: string; message?: string } }
    throw new ApiError(error.error?.message || '草稿暂时无法保存，请保留当前输入。', response.status, error.error?.code || 'draft_failed')
  }
  if (!body || typeof body !== 'object' || !('schema_version' in body) || body.schema_version !== 'swb.api.v1') {
    throw new ApiError('草稿服务响应版本不匹配，请保留当前输入。', response.status, 'schema_mismatch')
  }
  return body as T
}

function draftUrl(endpoint: 'drafts' | 'draft-save', key: string, householdId: string) {
  const query = new URLSearchParams({ household: householdId })
  return `/api/v1/${endpoint}/${encodeURIComponent(key)}/?${query}`
}
