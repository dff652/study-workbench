export type RequestKeyState = { signature: string; key: string } | null

export function makeRequestKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  throw new Error('当前浏览器无法生成安全的请求标识。')
}

export function requestKeyFor(
  ref: { current: RequestKeyState },
  signature: string,
) {
  if (!ref.current || ref.current.signature !== signature) {
    ref.current = { signature, key: makeRequestKey() }
  }
  return ref.current.key
}
