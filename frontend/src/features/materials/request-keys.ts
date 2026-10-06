export type RequestKeyState = { signature: string; key: string } | null

export function makeRequestKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = crypto.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
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
