import type { MaterialPage, SkillImport, SkillImportRecord } from '../../types'

export class ProposalError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ProposalError'
  }
}

class StrictJsonReader {
  private offset = 0

  constructor(private readonly text: string) {}

  parse(): unknown {
    this.skipWhitespace()
    const value = this.readValue(0)
    this.skipWhitespace()
    if (this.offset !== this.text.length) this.fail('导入文件末尾包含多余内容。')
    return value
  }

  private skipWhitespace() {
    while (/\s/.test(this.text[this.offset] || '')) this.offset += 1
  }

  private fail(message: string): never {
    throw new ProposalError(`${message}（接近第 ${this.offset + 1} 个字符）`)
  }

  private readString(): string {
    const start = this.offset
    if (this.text[this.offset] !== '"') this.fail('导入文件中的文字格式不正确。')
    this.offset += 1
    while (this.offset < this.text.length) {
      const char = this.text[this.offset]
      if (char === '"') {
        this.offset += 1
        try {
          return JSON.parse(this.text.slice(start, this.offset)) as string
        } catch {
          this.fail('导入文件中的文字转义不正确。')
        }
      }
      if (char === '\\') {
        this.offset += 2
      } else {
        if (char.charCodeAt(0) < 0x20) this.fail('导入文件中的文字包含不可见字符。')
        this.offset += 1
      }
    }
    this.fail('导入文件中的文字没有结束。')
  }

  private readValue(depth: number): unknown {
    if (depth > 100) this.fail('导入内容层级过深，无法读取。')
    this.skipWhitespace()
    const char = this.text[this.offset]
    if (char === '"') return this.readString()
    if (char === '{') return this.readObject(depth + 1)
    if (char === '[') return this.readArray(depth + 1)
    if (char === 't' && this.text.startsWith('true', this.offset)) {
      this.offset += 4
      return true
    }
    if (char === 'f' && this.text.startsWith('false', this.offset)) {
      this.offset += 5
      return false
    }
    if (char === 'n' && this.text.startsWith('null', this.offset)) {
      this.offset += 4
      return null
    }
    const number = this.text.slice(this.offset).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/)?.[0]
    if (number) {
      this.offset += number.length
      const parsed = Number(number)
      if (!Number.isFinite(parsed)) this.fail('导入内容中的数字超出可用范围。')
      return parsed
    }
    this.fail('导入文件内容格式不正确。')
  }

  private readObject(depth: number): Record<string, unknown> {
    this.offset += 1
    this.skipWhitespace()
    const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>
    const keys = new Set<string>()
    if (this.text[this.offset] === '}') {
      this.offset += 1
      return result
    }
    while (this.offset < this.text.length) {
      this.skipWhitespace()
      const key = this.readString()
      if (keys.has(key)) this.fail('导入文件中有重复信息，无法安全读取。')
      keys.add(key)
      this.skipWhitespace()
      if (this.text[this.offset] !== ':') this.fail('导入文件中的内容分隔不正确。')
      this.offset += 1
      result[key] = this.readValue(depth)
      this.skipWhitespace()
      if (this.text[this.offset] === '}') {
        this.offset += 1
        return result
      }
      if (this.text[this.offset] !== ',') this.fail('导入文件中的内容分隔不正确。')
      this.offset += 1
    }
    this.fail('导入文件中的一组内容没有结束。')
  }

  private readArray(depth: number): unknown[] {
    this.offset += 1
    this.skipWhitespace()
    const result: unknown[] = []
    if (this.text[this.offset] === ']') {
      this.offset += 1
      return result
    }
    while (this.offset < this.text.length) {
      result.push(this.readValue(depth))
      this.skipWhitespace()
      if (this.text[this.offset] === ']') {
        this.offset += 1
        return result
      }
      if (this.text[this.offset] !== ',') this.fail('导入文件中的内容分隔不正确。')
      this.offset += 1
    }
    this.fail('导入文件中的内容列表没有结束。')
  }
}

type Obj = Record<string, unknown>

function isObject(value: unknown): value is Obj {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function onlyKeys(value: Obj, keys: string[], where: string) {
  const extra = Object.keys(value).find((key) => !keys.includes(key))
  if (extra) throw new ProposalError(`${where}包含无法识别的信息，未能安全导入；请使用兼容的资料导出文件。`)
}

const FIELD_LABELS: Record<string, string> = {
  id: '内容标记', kind: '内容类型', data: '内容信息', schema_version: '文件版本',
  page_id: '资料页', sha256: '原图版本', source_id: '原图来源', bbox: '原图范围',
  sources: '原图来源', source: '原图来源', printed_text: '印刷题面', original_number: '原题号',
  display_markup: '展示格式', image_print_confirmed: '题面插图核对状态', definition: '知识定义',
  conditions: '适用条件', common_errors: '常见错误', name: '名称', steps: '步骤', notes: '说明',
  structural_features: '结构特征', question: '关联题目', node: '关联条目', role: '关系类型',
  body: '答案内容', basis: '依据', formulas: '公式', legibility: '辨认情况', placement: '放置位置',
  png_asset: '教学图文件', vector_asset: '可缩放图文件', alt: '图示说明', width_points: '图示宽度',
  min_label_points: '图示字号', independent_safe: '题面提示核对结果', assets: '图示内容', tool_inputs: '补充内容',
}

function fieldLabel(key: string) {
  return FIELD_LABELS[key] || '必要信息'
}

function requiredString(value: Obj, key: string, where: string) {
  if (typeof value[key] !== 'string' || value[key].trim() === '') {
    throw new ProposalError(`${where}缺少有效的${fieldLabel(key)}。`)
  }
  return value[key] as string
}

const RECORD_FIELDS: Record<SkillImportRecord['kind'], { required: string[]; optional: string[] }> = {
  question: { required: ['printed_text', 'original_number', 'sources'], optional: ['display_markup', 'image_print_confirmed'] },
  knowledge: { required: ['definition', 'sources'], optional: ['conditions', 'common_errors', 'display_markup'] },
  method: { required: ['name', 'sources'], optional: ['conditions', 'steps', 'notes'] },
  question_type: { required: ['name', 'sources'], optional: ['structural_features', 'conditions'] },
  answer: { required: ['question', 'body', 'basis'], optional: ['formulas'] },
  link: { required: ['question', 'node', 'role'], optional: [] },
  observation: { required: ['sources'], optional: ['legibility', 'notes'] },
  diagram: { required: ['question', 'placement', 'png_asset', 'vector_asset', 'source', 'alt', 'conditions', 'width_points', 'min_label_points', 'independent_safe', 'basis'], optional: [] },
}

function validateSources(
  data: Obj,
  recordId: string,
  sources: SkillImport['sources'],
  pages: MaterialPage[],
) {
  if (!Array.isArray(data.sources) || data.sources.length === 0) {
    throw new ProposalError(`第 ${recordId} 项缺少原图来源区域。`)
  }
  for (const [index, reference] of data.sources.entries()) {
    const where = `第 ${recordId} 项的第 ${index + 1} 个来源`
    if (!isObject(reference)) throw new ProposalError(`${where}信息不完整。`)
    onlyKeys(reference, ['source_id', 'bbox'], where)
    const sourceId = requiredString(reference, 'source_id', where)
    const source = sources.find((item) => item.id === sourceId)
    if (!source) throw new ProposalError(`${where}没有对应的原图来源。`)
    const page = pages.find((item) => item.id === source.page_id)
    if (!page || page.sha256 !== source.sha256) {
      throw new ProposalError(`${where}与当前资料中的原图页不一致；请重新选择正确的来源页。`)
    }
    if (!Array.isArray(reference.bbox) || reference.bbox.length !== 4 || !reference.bbox.every(Number.isInteger)) {
      throw new ProposalError(`${where}无法定位到有效的原图区域。`)
    }
    const [left, top, right, bottom] = reference.bbox as number[]
    if (left < 0 || top < 0 || right <= left || bottom <= top || right > page.width || bottom > page.height) {
      throw new ProposalError(`${where}超出原图范围，请重新核对。`)
    }
  }
}

export function parseProposal(text: string, pages: MaterialPage[]): SkillImport {
  if (new TextEncoder().encode(text).byteLength > 1024 * 1024) {
    throw new ProposalError('导入文件超过 1 MiB，请精简文件后重试。')
  }

  let value: unknown
  try {
    value = new StrictJsonReader(text).parse()
  } catch (error) {
    if (error instanceof ProposalError) throw error
    throw new ProposalError('导入文件格式无法读取，请检查文件后重试。')
  }
  if (!isObject(value)) throw new ProposalError('无法识别此导入文件的内容。')
  onlyKeys(value, ['schema_version', 'sources', 'records', 'packet', 'ledger', 'catalog', 'tool_inputs', 'assets'], '交换包')
  if (!['swb.skill-import.v1', 'swb.skill-import.v2'].includes(String(value.schema_version))) throw new ProposalError('导入文件版本无法识别，请使用兼容的资料导出文件。')
  if (value.schema_version === 'swb.skill-import.v2') {
    if (!isObject(value.assets) || Object.keys(value.assets).length > 32) throw new ProposalError('图示内容缺少配套文件或数量过多。')
    for (const [key, asset] of Object.entries(value.assets)) {
      if (!isObject(asset)) throw new ProposalError('图示文件信息不完整。')
      onlyKeys(asset, ['sha256', 'media_type', 'base64'], '图示文件')
      if (!/^[0-9a-f]{64}$/.test(requiredString(asset, 'sha256', '图示资产')) ||
        !['image/png', 'image/svg+xml', 'application/pdf'].includes(requiredString(asset, 'media_type', '图示资产')) ||
        typeof asset.base64 !== 'string' || !key || key.startsWith('/') || key.includes('..') || key.includes('\\') || key.includes(':')) {
        throw new ProposalError('图示文件不完整或格式不受支持。')
      }
    }
  } else if ('assets' in value) throw new ProposalError('此文件包含不受支持的图示内容；请使用兼容的资料导出文件。')
  if ('tool_inputs' in value && !isObject(value.tool_inputs)) throw new ProposalError('补充内容格式不正确。')
  if (!Array.isArray(value.sources) || value.sources.length < 1 || value.sources.length > 100) {
    throw new ProposalError('导入文件需包含 1 至 100 个原图来源。')
  }
  if (!Array.isArray(value.records) || value.records.length > 300) {
    throw new ProposalError('导入内容需在 0 至 300 项之间。')
  }

  const sourceIds = new Set<string>()
  const sources = value.sources.map((entry, index) => {
    const where = `来源 ${index + 1}`
    if (!isObject(entry)) throw new ProposalError(`${where}信息不完整。`)
    onlyKeys(entry, ['id', 'page_id', 'sha256'], where)
    const id = requiredString(entry, 'id', where)
    const page_id = requiredString(entry, 'page_id', where)
    const sha256 = requiredString(entry, 'sha256', where)
    if (sourceIds.has(id)) throw new ProposalError(`${where}重复。`)
    sourceIds.add(id)
    const page = pages.find((item) => item.id === page_id)
    if (!page || page.sha256 !== sha256) {
      throw new ProposalError(`${where}与当前资料的原图页不一致；请检查资料来源后重新选择。`)
    }
    return { id, page_id, sha256 }
  })

  const recordIds = new Set<string>()
  const records = value.records.map((entry, index) => {
    const where = `记录 ${index + 1}`
    if (!isObject(entry)) throw new ProposalError(`${where}信息不完整。`)
    onlyKeys(entry, ['id', 'kind', 'data'], where)
    const id = requiredString(entry, 'id', where)
    if (recordIds.has(id)) throw new ProposalError(`${where}重复。`)
    recordIds.add(id)
    if (typeof entry.kind !== 'string' || !Object.hasOwn(RECORD_FIELDS, entry.kind)) {
      throw new ProposalError(`${where}的内容类型暂不支持。`)
    }
    if (!isObject(entry.data)) throw new ProposalError(`${where}内容不完整。`)
    const kind = entry.kind as SkillImportRecord['kind']
    if (kind === 'diagram' && value.schema_version !== 'swb.skill-import.v2') throw new ProposalError('教学图内容需要使用兼容的导入文件。')
    const fields = RECORD_FIELDS[kind]
    onlyKeys(entry.data, [...fields.required, ...fields.optional], where)
    for (const field of fields.required) {
      if (!(field in entry.data)) throw new ProposalError(`${where}缺少${fieldLabel(field)}。`)
    }
    for (const field of [...fields.required, ...fields.optional]) {
      if (kind === 'diagram' && ['source', 'conditions', 'width_points', 'min_label_points', 'independent_safe'].includes(field)) continue
      if (field === 'printed_text' && entry.data[field] === null) continue
      if (field !== 'sources' && field !== 'image_print_confirmed' && field !== 'formulas'
        && field in entry.data && typeof entry.data[field] !== 'string') {
        throw new ProposalError(`${where}的${fieldLabel(field)}应为文字内容。`)
      }
    }
    if ('image_print_confirmed' in entry.data && typeof entry.data.image_print_confirmed !== 'boolean') {
      throw new ProposalError(`${where}的题面插图核对状态不正确。`)
    }
    if ('formulas' in entry.data && !Array.isArray(entry.data.formulas)) {
      throw new ProposalError(`${where}的公式内容格式不正确。`)
    }
    if ('sources' in entry.data) validateSources(entry.data, String(index + 1), sources, pages)
    if (kind === 'diagram') {
      if (!isObject(entry.data.source) || !Array.isArray(entry.data.conditions) || entry.data.conditions.length < 1 ||
        entry.data.conditions.some((c) => typeof c !== 'string' || !c.trim()) || typeof entry.data.independent_safe !== 'boolean' ||
        typeof entry.data.width_points !== 'number' || entry.data.width_points < 1 || entry.data.width_points > 490 ||
        typeof entry.data.min_label_points !== 'number' || entry.data.min_label_points < 9 || entry.data.min_label_points > 40 ||
        !['question', 'answer'].includes(String(entry.data.placement))) throw new ProposalError('教学图的来源、尺寸、构造条件或提示状态不完整。')
      validateSources({ sources: [entry.data.source] }, String(index + 1), sources, pages)
      if (entry.data.placement === 'question' && entry.data.independent_safe !== true) throw new ProposalError('题面教学图尚未确认不含提示。')
      const assets = value.assets as Obj
      if (!Object.hasOwn(assets, String(entry.data.png_asset)) || !Object.hasOwn(assets, String(entry.data.vector_asset))) throw new ProposalError('教学图缺少配套文件。')
    }
    return { id, kind, data: entry.data }
  })

  const recordsById = new Map(records.map((record) => [record.id, record]))
  for (const [index, record] of records.entries()) {
    const data = record.data
    if (record.kind === 'answer' || record.kind === 'link' || record.kind === 'diagram') {
      const questionId = requiredString(data, 'question', `记录 ${index + 1}`)
      if (recordsById.get(questionId)?.kind !== 'question') {
        throw new ProposalError(`第 ${index + 1} 项必须关联此文件中的题目。`)
      }
      if (record.kind === 'diagram') {
        const refs = recordsById.get(questionId)?.data.sources
        const source = data.source as Obj
        if (!Array.isArray(refs) || !refs.some((ref) => isObject(ref) && ref.source_id === source.source_id &&
          Array.isArray(ref.bbox) && Array.isArray(source.bbox) && ref.bbox.length === 4 &&
          ref.bbox.every((n, i) => n === (source.bbox as unknown[])[i]))) {
          throw new ProposalError(`第 ${index + 1} 项教学图须来自所关联题目的原图区域。`)
        }
      }
    }
    if (record.kind === 'link') {
      const nodeId = requiredString(data, 'node', `记录 ${index + 1}`)
      const nodeKind = recordsById.get(nodeId)?.kind
      const allowedRoles: Record<string, string[]> = {
        knowledge: ['applies'],
        method: ['primary', 'auxiliary'],
        question_type: ['belongs'],
      }
      if (!nodeKind || !allowedRoles[nodeKind]?.includes(String(data.role))) {
        throw new ProposalError(`第 ${index + 1} 项关联内容或关系类型不符合要求。`)
      }
    }
  }

  return value as SkillImport
}

export type PreviewSource = { pagePosition: number; bbox: [number, number, number, number] }

export function proposalPreview(record: SkillImportRecord, records: SkillImportRecord[], proposal: SkillImport, pages: MaterialPage[]) {
  const data = record.data
  const labelById = new Map(records.map((item, index) => [item.id, recordLabel(item, index + 1)]))
  const index = records.indexOf(record) + 1
  let kindLabel = '原图笔迹观察'
  let title = '观察记录'
  let text = typeof data.notes === 'string' ? data.notes : '原图观察内容待核对。'
  if (record.kind === 'question') {
    kindLabel = '题目'
    title = `题目 ${String(data.original_number)}`
    text = data.printed_text === null ? '题干看不清或待补充，保留未知。' : String(data.printed_text)
  } else if (record.kind === 'knowledge') {
    kindLabel = '知识条目'
    title = '知识条目'
    text = String(data.definition)
  } else if (record.kind === 'method') {
    kindLabel = '方法'
    title = String(data.name)
    text = [data.conditions, data.steps, data.notes].filter((part) => typeof part === 'string' && part).join('\n') || '方法说明未记录。'
  } else if (record.kind === 'question_type') {
    kindLabel = '题型'
    title = String(data.name)
    text = [data.structural_features, data.conditions].filter((part) => typeof part === 'string' && part).join('\n') || '题型特征未记录。'
  } else if (record.kind === 'answer') {
    kindLabel = '家长答案'
    title = `对应${labelById.get(String(data.question)) || '题目'}`
    text = `${String(data.body)}\n依据：${String(data.basis)}`
  } else if (record.kind === 'link') {
    kindLabel = '双向关联'
    title = `${labelById.get(String(data.question)) || '题目'} · ${labelById.get(String(data.node)) || '知识节点'}`
    const roleLabels: Record<string, string> = {
      applies: '适用知识',
      primary: '主要方法',
      auxiliary: '辅助方法',
      belongs: '所属题型',
    }
    text = `关系：${roleLabels[String(data.role)] || '关联类型待核对'}`
  } else if (record.kind === 'diagram') {
    kindLabel = '教学图示'
    title = `${data.placement === 'question' ? '无提示题面图' : '家长解析图'} · ${labelById.get(String(data.question)) || '题目'}`
    text = `${String(data.alt)}\n构造：${(data.conditions as string[]).join('；')}\n依据：${String(data.basis)}`
  }
  const sourceMap = new Map(proposal.sources.map((source) => [source.id, source]))
  const sourcePages = (record.kind === 'diagram' ? [data.source] : Array.isArray(data.sources) ? data.sources : []).flatMap((reference) => {
    if (!isObject(reference) || !Array.isArray(reference.bbox)) return []
    const source = sourceMap.get(String(reference.source_id))
    const page = source ? pages.find((item) => item.id === source.page_id) : undefined
    if (!page) return []
    return [{ pagePosition: page.position, bbox: reference.bbox as [number, number, number, number] }]
  })
  const shownFields = ['printed_text', 'original_number', 'definition', 'name', 'conditions', 'steps', 'notes', 'structural_features', 'body', 'basis', 'question', 'node', 'role', 'sources']
  const hasAdditionalContent = record.kind !== 'diagram' && Object.keys(data).some((key) => !shownFields.includes(key))
  return { index, kindLabel, title, text, sources: sourcePages, hasAdditionalContent }
}

function recordLabel(record: SkillImportRecord, index: number) {
  if (record.kind === 'question') return `题目 ${String(record.data.original_number || index)}`
  const names: Record<SkillImportRecord['kind'], string> = {
    question: '题目', knowledge: '知识条目', method: '方法', question_type: '题型', answer: '答案', link: '关联', observation: '观察', diagram: '教学图示',
  }
  return names[record.kind]
}
