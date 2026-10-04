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
    if (this.offset !== this.text.length) this.fail('JSON 末尾包含多余内容。')
    return value
  }

  private skipWhitespace() {
    while (/\s/.test(this.text[this.offset] || '')) this.offset += 1
  }

  private fail(message: string): never {
    throw new ProposalError(`${message}（位置 ${this.offset + 1}）`)
  }

  private readString(): string {
    const start = this.offset
    if (this.text[this.offset] !== '"') this.fail('JSON 字符串格式无效。')
    this.offset += 1
    while (this.offset < this.text.length) {
      const char = this.text[this.offset]
      if (char === '"') {
        this.offset += 1
        try {
          return JSON.parse(this.text.slice(start, this.offset)) as string
        } catch {
          this.fail('JSON 字符串转义无效。')
        }
      }
      if (char === '\\') {
        this.offset += 2
      } else {
        if (char.charCodeAt(0) < 0x20) this.fail('JSON 字符串包含控制字符。')
        this.offset += 1
      }
    }
    this.fail('JSON 字符串未闭合。')
  }

  private readValue(depth: number): unknown {
    if (depth > 100) this.fail('JSON 嵌套层数过多。')
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
      if (!Number.isFinite(parsed)) this.fail('JSON 数字超出可用范围。')
      return parsed
    }
    this.fail('JSON 值格式无效。')
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
      if (keys.has(key)) this.fail(`JSON 对象包含重复字段“${key}”。`)
      keys.add(key)
      this.skipWhitespace()
      if (this.text[this.offset] !== ':') this.fail('JSON 对象缺少冒号。')
      this.offset += 1
      result[key] = this.readValue(depth)
      this.skipWhitespace()
      if (this.text[this.offset] === '}') {
        this.offset += 1
        return result
      }
      if (this.text[this.offset] !== ',') this.fail('JSON 对象字段之间缺少逗号。')
      this.offset += 1
    }
    this.fail('JSON 对象未闭合。')
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
      if (this.text[this.offset] !== ',') this.fail('JSON 数组元素之间缺少逗号。')
      this.offset += 1
    }
    this.fail('JSON 数组未闭合。')
  }
}

type Obj = Record<string, unknown>

function isObject(value: unknown): value is Obj {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function onlyKeys(value: Obj, keys: string[], where: string) {
  const extra = Object.keys(value).find((key) => !keys.includes(key))
  if (extra) throw new ProposalError(`${where}包含未支持字段“${extra}”。`)
}

function requiredString(value: Obj, key: string, where: string) {
  if (typeof value[key] !== 'string' || value[key].trim() === '') {
    throw new ProposalError(`${where}缺少有效的“${key}”。`)
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
    throw new ProposalError(`第 ${recordId} 项缺少原图区域来源。`)
  }
  for (const [index, reference] of data.sources.entries()) {
    const where = `第 ${recordId} 项的第 ${index + 1} 个来源`
    if (!isObject(reference)) throw new ProposalError(`${where}格式无效。`)
    onlyKeys(reference, ['source_id', 'bbox'], where)
    const sourceId = requiredString(reference, 'source_id', where)
    const source = sources.find((item) => item.id === sourceId)
    if (!source) throw new ProposalError(`${where}未映射到交换包中的来源。`)
    const page = pages.find((item) => item.id === source.page_id)
    if (!page || page.sha256 !== source.sha256) {
      throw new ProposalError(`${where}未精确匹配当前资料中的原图页及 SHA-256；请在旧资料页指定来源。`)
    }
    if (!Array.isArray(reference.bbox) || reference.bbox.length !== 4 || !reference.bbox.every(Number.isInteger)) {
      throw new ProposalError(`${where}区域必须是原图上的四个整数坐标。`)
    }
    const [left, top, right, bottom] = reference.bbox as number[]
    if (left < 0 || top < 0 || right <= left || bottom <= top || right > page.width || bottom > page.height) {
      throw new ProposalError(`${where}区域超出原图尺寸。`)
    }
  }
}

export function parseProposal(text: string, pages: MaterialPage[]): SkillImport {
  if (new TextEncoder().encode(text).byteLength > 1024 * 1024) {
    throw new ProposalError('交换 JSON 超过 1 MiB，请先缩小内容。')
  }

  let value: unknown
  try {
    value = new StrictJsonReader(text).parse()
  } catch (error) {
    if (error instanceof ProposalError) throw error
    throw new ProposalError('JSON 格式无效，请检查文件内容。')
  }
  if (!isObject(value)) throw new ProposalError('交换包根节点必须是 JSON 对象。')
  onlyKeys(value, ['schema_version', 'sources', 'records', 'packet', 'ledger', 'catalog', 'tool_inputs', 'assets'], '交换包')
  if (!['swb.skill-import.v1', 'swb.skill-import.v2'].includes(String(value.schema_version))) throw new ProposalError('交换包版本必须是 swb.skill-import.v1 或 v2。')
  if (value.schema_version === 'swb.skill-import.v2') {
    if (!isObject(value.assets) || Object.keys(value.assets).length > 32) throw new ProposalError('v2 必须提供最多 32 个 assets。')
    for (const [key, asset] of Object.entries(value.assets)) {
      if (!isObject(asset)) throw new ProposalError('图示资产格式无效。')
      onlyKeys(asset, ['sha256', 'media_type', 'base64'], '图示资产')
      if (!/^[0-9a-f]{64}$/.test(requiredString(asset, 'sha256', '图示资产')) ||
        !['image/png', 'image/svg+xml', 'application/pdf'].includes(requiredString(asset, 'media_type', '图示资产')) ||
        typeof asset.base64 !== 'string' || !key || key.startsWith('/') || key.includes('..') || key.includes('\\') || key.includes(':')) {
        throw new ProposalError('图示资产路径、哈希或类型无效。')
      }
    }
  } else if ('assets' in value) throw new ProposalError('图示资产须使用明确的 v2 契约。')
  if ('tool_inputs' in value && !isObject(value.tool_inputs)) throw new ProposalError('工具输入记录必须是 JSON 对象。')
  if (!Array.isArray(value.sources) || value.sources.length < 1 || value.sources.length > 100) {
    throw new ProposalError('交换包必须包含 1 至 100 个原图来源。')
  }
  if (!Array.isArray(value.records) || value.records.length > 300) {
    throw new ProposalError('交换包的记录数必须在 0 至 300 项之间。')
  }

  const sourceIds = new Set<string>()
  const sources = value.sources.map((entry, index) => {
    const where = `来源 ${index + 1}`
    if (!isObject(entry)) throw new ProposalError(`${where}格式无效。`)
    onlyKeys(entry, ['id', 'page_id', 'sha256'], where)
    const id = requiredString(entry, 'id', where)
    const page_id = requiredString(entry, 'page_id', where)
    const sha256 = requiredString(entry, 'sha256', where)
    if (sourceIds.has(id)) throw new ProposalError(`${where}的局部标识重复。`)
    sourceIds.add(id)
    const page = pages.find((item) => item.id === page_id)
    if (!page || page.sha256 !== sha256) {
      throw new ProposalError(`${where}未精确匹配当前资料中的原图页及 SHA-256；不会按哈希自动选页。`)
    }
    return { id, page_id, sha256 }
  })

  const recordIds = new Set<string>()
  const records = value.records.map((entry, index) => {
    const where = `记录 ${index + 1}`
    if (!isObject(entry)) throw new ProposalError(`${where}格式无效。`)
    onlyKeys(entry, ['id', 'kind', 'data'], where)
    const id = requiredString(entry, 'id', where)
    if (recordIds.has(id)) throw new ProposalError(`${where}的局部标识重复。`)
    recordIds.add(id)
    if (typeof entry.kind !== 'string' || !Object.hasOwn(RECORD_FIELDS, entry.kind)) {
      throw new ProposalError(`${where}类型未受支持。`)
    }
    if (!isObject(entry.data)) throw new ProposalError(`${where}内容必须是 JSON 对象。`)
    const kind = entry.kind as SkillImportRecord['kind']
    if (kind === 'diagram' && value.schema_version !== 'swb.skill-import.v2') throw new ProposalError('图示记录须使用 v2。')
    const fields = RECORD_FIELDS[kind]
    onlyKeys(entry.data, [...fields.required, ...fields.optional], where)
    for (const field of fields.required) {
      if (!(field in entry.data)) throw new ProposalError(`${where}缺少必需字段“${field}”。`)
    }
    for (const field of [...fields.required, ...fields.optional]) {
      if (kind === 'diagram' && ['source', 'conditions', 'width_points', 'min_label_points', 'independent_safe'].includes(field)) continue
      if (field === 'printed_text' && entry.data[field] === null) continue
      if (field !== 'sources' && field !== 'image_print_confirmed' && field !== 'formulas'
        && field in entry.data && typeof entry.data[field] !== 'string') {
        throw new ProposalError(`${where}字段“${field}”必须是文本。`)
      }
    }
    if ('image_print_confirmed' in entry.data && typeof entry.data.image_print_confirmed !== 'boolean') {
      throw new ProposalError(`${where}字段“image_print_confirmed”必须是布尔值。`)
    }
    if ('formulas' in entry.data && !Array.isArray(entry.data.formulas)) {
      throw new ProposalError(`${where}字段“formulas”必须是数组。`)
    }
    if ('sources' in entry.data) validateSources(entry.data, String(index + 1), sources, pages)
    if (kind === 'diagram') {
      if (!isObject(entry.data.source) || !Array.isArray(entry.data.conditions) || entry.data.conditions.length < 1 ||
        entry.data.conditions.some((c) => typeof c !== 'string' || !c.trim()) || typeof entry.data.independent_safe !== 'boolean' ||
        typeof entry.data.width_points !== 'number' || entry.data.width_points < 1 || entry.data.width_points > 490 ||
        typeof entry.data.min_label_points !== 'number' || entry.data.min_label_points < 9 || entry.data.min_label_points > 40 ||
        !['question', 'answer'].includes(String(entry.data.placement))) throw new ProposalError('教学图来源、尺寸、构造条件或提示状态无效。')
      validateSources({ sources: [entry.data.source] }, String(index + 1), sources, pages)
      if (entry.data.placement === 'question' && entry.data.independent_safe !== true) throw new ProposalError('题面图须核对无提示。')
      const assets = value.assets as Obj
      if (!Object.hasOwn(assets, String(entry.data.png_asset)) || !Object.hasOwn(assets, String(entry.data.vector_asset))) throw new ProposalError('图示配对资产缺失。')
    }
    return { id, kind, data: entry.data }
  })

  const recordsById = new Map(records.map((record) => [record.id, record]))
  for (const [index, record] of records.entries()) {
    const data = record.data
    if (record.kind === 'answer' || record.kind === 'link' || record.kind === 'diagram') {
      const questionId = requiredString(data, 'question', `记录 ${index + 1}`)
      if (recordsById.get(questionId)?.kind !== 'question') {
        throw new ProposalError(`记录 ${index + 1} 必须关联交换包中的题目。`)
      }
      if (record.kind === 'diagram') {
        const refs = recordsById.get(questionId)?.data.sources
        const source = data.source as Obj
        if (!Array.isArray(refs) || !refs.some((ref) => isObject(ref) && ref.source_id === source.source_id &&
          Array.isArray(ref.bbox) && Array.isArray(source.bbox) && ref.bbox.length === 4 &&
          ref.bbox.every((n, i) => n === (source.bbox as unknown[])[i]))) {
          throw new ProposalError(`记录 ${index + 1} 的教学图须来自本题原图区域。`)
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
        throw new ProposalError(`记录 ${index + 1} 的关系目标或 role 不符合契约。`)
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
    text = `关系：${roleLabels[String(data.role)] || String(data.role)}`
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
  const additional = record.kind === 'diagram' ? [] : Object.entries(data).filter(([key]) => !['printed_text', 'original_number', 'definition', 'name', 'conditions', 'steps', 'notes', 'structural_features', 'body', 'basis', 'question', 'node', 'role', 'sources'].includes(key))
  const extraText = additional.map(([key, value]) => `${key}：${typeof value === 'string' ? value : JSON.stringify(value)}`).join('\n')
  return { index, kindLabel, title, text: extraText ? `${text}\n${extraText}` : text, sources: sourcePages }
}

function recordLabel(record: SkillImportRecord, index: number) {
  if (record.kind === 'question') return `题目 ${String(record.data.original_number || index)}`
  const names: Record<SkillImportRecord['kind'], string> = {
    question: '题目', knowledge: '知识条目', method: '方法', question_type: '题型', answer: '答案', link: '关联', observation: '观察', diagram: '教学图示',
  }
  return names[record.kind]
}
