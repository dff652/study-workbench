const INTERNAL_DETAIL = /\b(?:swb\.[a-z0-9.-]+|schema_version|request_key|expected_version|source_stamp|base_stamp|payload|traceback|sha-?256|uuid|json)\b|\b[a-z][a-z0-9]*_[a-z0-9_]+\b|\b[0-9a-f]{64}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\{\s*"[^"\n]+"\s*:/i

export function userMessage(message: unknown, fallback = '操作未完成，请核对输入后重试。') {
  if (typeof message !== 'string' || !message.trim()) return fallback
  if (/failed to fetch|networkerror|load failed/i.test(message)) return '连接暂时不可用，请检查网络后重试。'
  return INTERNAL_DETAIL.test(message) || !/[\u4e00-\u9fff]/.test(message) ? fallback : message
}
