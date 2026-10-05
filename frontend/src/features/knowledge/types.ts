import type { SolutionAsset, SolutionOutput, SolutionQuestion, SolutionStep, SolutionWorkspaceResponse } from '../../types'

export type RuleProfile = 'mathematics' | 'science' | 'language' | 'humanities'
export type Section = 'thinking' | 'construction' | 'derivation' | 'conclusion' | 'pitfall' | 'other'
export type KnowledgeItem = {
  id: string; knowledge_revision_id: string | null; lecture_id: string; order: number; title: string
  kind: 'definition' | 'theorem' | 'empirical_rule' | 'interpretation' | 'strategy'
  origin: 'source' | 'foundation' | 'supplement'
  sources: Array<{ page_id: string; region: [number, number, number, number] | null; printed_page: string | null }>
  original: string; statement: string; definitions: string; conditions: string[]; dependencies: string[]
  steps: Array<SolutionStep & { section: Section }>; corrections: SolutionQuestion['corrections']; unknowns: string[]
}
export type KnowledgeContent = {
  schema_version: 'swb.knowledge.v1'; title: string; school_subject: string; learner_level: string
  lectures: Array<{ id: string; title: string; rule_profile: RuleProfile }>; knowledge: KnowledgeItem[]
  outputs: Record<'inventory' | 'per_knowledge' | 'per_lecture' | 'combined', Array<'pdf' | 'docx'>>
}
export type KnowledgeRevision = {
  id: number; mode: 'knowledge'; version: number; created_at: string; author: string; reason: string
  confirmed: boolean; content: KnowledgeContent; gaps: Array<{ knowledge_id: string; message: string }>
}
export type KnowledgeChecks = Record<'content' | 'subject' | 'pdf_visual' | 'word_pc' | 'word_macos', { status: 'pass' | 'fail' | 'not_tested'; notes: string }>
export type KnowledgeOutput = Omit<SolutionOutput, 'checks' | 'documents'> & {
  mode: 'knowledge'; checks: KnowledgeChecks
  documents: Array<Omit<SolutionOutput['documents'][number], 'organization'> & {
    organization: 'inventory' | 'per_knowledge' | 'per_lecture' | 'combined'; knowledge_ids: string[]
  }>
}
export type KnowledgeWorkspaceResponse = Pick<SolutionWorkspaceResponse, 'schema_version' | 'writable' | 'source_stamp' | 'pages' | 'nodes' | 'assets' | 'history_next_before' | 'output_next_before'> & {
  mode: 'knowledge'; material: { id: string; title: string; household_id?: string; subject: string; version: number }
  revision: KnowledgeRevision | null; initial_content: KnowledgeContent
  saved_revision?: KnowledgeRevision; saved_source_stamp?: string
  command_result?: { revision_id: number; output_id?: string; confirmation_id?: number }
  history: Array<Omit<KnowledgeRevision, 'content' | 'gaps'>>; outputs: KnowledgeOutput[]
}
export type KnowledgeAssets = SolutionAsset[]
