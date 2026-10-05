export function documentOutputSummary(outputs: Record<string, string[]>, labels: Record<string, string>) {
  const formats = [...new Set(Object.values(outputs).flat())].map((format) => format === 'docx' ? 'Word' : format.toUpperCase())
  const detail = Object.entries(outputs).filter(([, selected]) => selected.length).map(([key, selected]) =>
    `${labels[key] || key}：${selected.map((format) => format === 'docx' ? 'Word' : format.toUpperCase()).join(' / ')}`).join('；')
  return { label: formats.length ? `生成 ${formats.join(' / ')}` : '先选择输出格式', detail: detail || '尚未选择输出范围与格式。' }
}
