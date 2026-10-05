import { newSolutionId, newSolutionStep } from '../solutions/model'
import type { KnowledgeContent, KnowledgeItem, RuleProfile, Section } from './types'

export const PROFILES: Record<RuleProfile, string> = { mathematics: '数学证明', science: '科学观察', language: '语言分析', humanities: '人文证据' }
export const SECTIONS: Record<Section, string> = { thinking: '先想什么', construction: '方法／构造及目的', derivation: '完整推导／依据', conclusion: '结论', pitfall: '易错点／适用限制', other: '其他讲解／证明' }
export const KINDS = { definition: '定义', theorem: '数学定理', empirical_rule: '观察／经验结论', interpretation: '文本解释', strategy: '方法' }
export const PROFILE_KINDS: Record<RuleProfile, Array<KnowledgeItem['kind']>> = {
  mathematics: ['definition', 'theorem', 'strategy'], science: ['definition', 'empirical_rule', 'strategy'],
  language: ['definition', 'interpretation', 'strategy'], humanities: ['definition', 'interpretation', 'strategy'],
}
export function newKnowledgeItem(lectureId: string, order: number): KnowledgeItem {
  return { id: newSolutionId('knowledge'), knowledge_revision_id: null, lecture_id: lectureId, order, title: '',
    kind: 'definition', origin: 'source', sources: [], original: '', statement: '', definitions: '', conditions: [],
    dependencies: [], steps: (Object.keys(SECTIONS) as Section[]).filter((section) => section !== 'other').map((section) => ({ ...newSolutionStep(), section })),
    corrections: [], unknowns: [] }
}
export function isKnowledgeContent(value: unknown): value is KnowledgeContent {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const content = value as Partial<KnowledgeContent>
  return content.schema_version === 'swb.knowledge.v1' && typeof content.title === 'string' && typeof content.school_subject === 'string'
    && typeof content.learner_level === 'string' && Array.isArray(content.lectures) && content.lectures.every((lecture) => lecture && typeof lecture.id === 'string' && typeof lecture.title === 'string' && Object.hasOwn(PROFILES, lecture.rule_profile))
    && Array.isArray(content.knowledge) && content.knowledge.every((item) => item && typeof item.id === 'string' && typeof item.title === 'string'
      && typeof item.statement === 'string' && typeof item.original === 'string' && typeof item.definitions === 'string'
      && (item.knowledge_revision_id === null || typeof item.knowledge_revision_id === 'string')
      && typeof item.lecture_id === 'string' && Number.isInteger(item.order) && Object.hasOwn(KINDS, item.kind)
      && ['source', 'foundation', 'supplement'].includes(item.origin) && Array.isArray(item.sources)
      && item.sources.every((ref) => ref && typeof ref.page_id === 'string' && (ref.printed_page === null || typeof ref.printed_page === 'string')
        && (ref.region === null || Array.isArray(ref.region) && ref.region.length === 4 && ref.region.every(Number.isInteger)))
      && [item.conditions, item.dependencies, item.unknowns].every((notes) => Array.isArray(notes) && notes.every((note) => typeof note === 'string'))
      && Array.isArray(item.steps) && item.steps.every((step) => step && typeof step.id === 'string' && Object.hasOwn(SECTIONS, step.section)
        && typeof step.text === 'string' && (step.formula === null || typeof step.formula === 'string') && typeof step.new_page === 'boolean'
        && (step.figure === null || step.figure && typeof step.figure.asset_id === 'string' && typeof step.figure.caption === 'string' && typeof step.figure.width_mm === 'number' && ['question', 'method', 'answer'].includes(step.figure.role)))
      && Array.isArray(item.corrections) && item.corrections.every((correction) => correction && ['printing_error', 'naming', 'draft_correction'].includes(correction.kind)
        && typeof correction.original === 'string' && typeof correction.replacement === 'string' && typeof correction.basis === 'string'))
    && !!content.outputs && ['inventory', 'per_knowledge', 'per_lecture', 'combined'].every((key) => {
      const formats = content.outputs?.[key as keyof KnowledgeContent['outputs']]
      return Array.isArray(formats) && formats.every((format) => format === 'pdf' || format === 'docx')
    })
}
