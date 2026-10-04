import { describe, expect, it } from 'vitest'
import { parseProposal, ProposalError } from './exchange'
import type { MaterialPage } from '../../types'

const pages: MaterialPage[] = [{
  id: 'page-1', position: 1, sha256: 'a'.repeat(64), width: 1600, height: 1200,
  page_url: '/materials/page-1/', preview_url: '/materials/page-1/preview/',
}]

function completePackage() {
  const region = [{ source_id: 'scan', bbox: [1, 2, 100, 120] }]
  return {
    schema_version: 'swb.skill-import.v1',
    sources: [{ id: 'scan', page_id: 'page-1', sha256: 'a'.repeat(64) }],
    records: [
      { id: 'q1', kind: 'question', data: { printed_text: '题干', original_number: '1', sources: region } },
      { id: 'k1', kind: 'knowledge', data: { definition: '知识', sources: region } },
      { id: 'm1', kind: 'method', data: { name: '方法', sources: region } },
      { id: 't1', kind: 'question_type', data: { name: '题型', sources: region } },
      { id: 'a1', kind: 'answer', data: { question: 'q1', body: '答案', basis: '依据' } },
      { id: 'l1', kind: 'link', data: { question: 'q1', node: 'm1', role: 'primary' } },
      { id: 'o1', kind: 'observation', data: { sources: region, notes: '笔迹不明' } },
    ],
    tool_inputs: { sources: ['scan'], preparation: 'local-only' },
  }
}

describe('skill exchange preview parser', () => {
  it('retains unknown text and v2 diagram sources regardless of JSON key order', () => {
    const value = completePackage()
    const unknown = JSON.parse(JSON.stringify(value))
    unknown.records[0].data.printed_text = null
    expect(parseProposal(JSON.stringify(unknown), pages).records[0].data.printed_text).toBeNull()
    const v2 = { ...value, schema_version: 'swb.skill-import.v2', assets: {
      'figure.png': { sha256: 'a'.repeat(64), media_type: 'image/png', base64: 'aGVsbG8=' },
      'figure.svg': { sha256: 'b'.repeat(64), media_type: 'image/svg+xml', base64: 'aGVsbG8=' },
    }, records: [...value.records, { id: 'd', kind: 'diagram', data: {
      question: 'q1', placement: 'question', png_asset: 'figure.png', vector_asset: 'figure.svg',
      source: { bbox: [1, 2, 100, 120], source_id: 'scan' }, alt: '三角形', conditions: ['AB=AC'],
      width_points: 250, min_label_points: 12, independent_safe: true, basis: '构造核对',
    } }] }
    expect(parseProposal(JSON.stringify(v2), pages).records.at(-1)?.kind).toBe('diagram')
    const changed = JSON.parse(JSON.stringify(v2))
    changed.records.at(-1).data.source.bbox = [1, 2, 110, 120]
    expect(() => parseProposal(JSON.stringify(changed), pages)).toThrow(/本题原图区域/)
  })
  it('accepts and retains all record kinds and optional tool input metadata', () => {
    const parsed = parseProposal(JSON.stringify(completePackage()), pages)
    expect(parsed.records.map((record) => record.kind)).toEqual([
      'question', 'knowledge', 'method', 'question_type', 'answer', 'link', 'observation',
    ])
    expect(parsed.tool_inputs).toEqual({ sources: ['scan'], preparation: 'local-only' })
  })

  it('rejects duplicate keys, unknown fields and mismatched page digests', () => {
    expect(() => parseProposal('{"schema_version":"swb.skill-import.v1","schema_version":"swb.skill-import.v1"}', pages)).toThrow(ProposalError)
    expect(() => parseProposal(JSON.stringify({ ...completePackage(), extra: true }), pages)).toThrow(/未支持字段/)
    const mismatch = completePackage()
    mismatch.sources[0].sha256 = 'b'.repeat(64)
    expect(() => parseProposal(JSON.stringify(mismatch), pages)).toThrow(/SHA-256/)
  })
})
