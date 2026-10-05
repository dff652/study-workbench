import type { ReactNode } from 'react'
import type { SolutionOutput, SolutionWorkspaceResponse } from '../../types'

export type RevisionSummary = { id: number; version: number; author: string; reason: string; created_at: string; confirmed: boolean; gaps?: Array<{ question_id?: string; knowledge_id?: string; message: string }> }
export type CompanionOutput = Omit<SolutionOutput, 'checks' | 'documents'> & {
  checks: Record<string, { status: 'pass' | 'fail' | 'not_tested'; notes: string }>
  documents: Array<Omit<SolutionOutput['documents'][number], 'organization'> & { organization: string }>
}
export type CompanionResponse<C, O extends CompanionOutput> = Pick<SolutionWorkspaceResponse,
  'writable' | 'source_stamp' | 'pages' | 'nodes' | 'assets' | 'history_next_before' | 'output_next_before'> & {
  material: { id: string; title: string; household_id?: string }
  revision: (RevisionSummary & { content: C }) | null
  saved_revision?: RevisionSummary & { content: C }
  saved_source_stamp?: string
  command_result?: { revision_id: number; output_id?: string; confirmation_id?: number }
  initial_content: C
  history: RevisionSummary[]
  outputs: O[]
}
export type CompanionWorkspaceProps = {
  materialId: string; householdId: string; csrfToken: string; canWrite: boolean
  onUnauthorized: () => void; onBack: () => void; onUnsavedChange?: (unsaved: boolean) => void
  initialPanel?: 'editor' | 'outputs'; initialTab?: string; onTabChange?: (value: string) => void
  onScopeLoaded?: (scope: { household_id: string; learner_id: string }, requestedScreen: string) => void
}
export type CompanionConfig<C, O extends CompanionOutput, W extends CompanionResponse<C, O>> = {
  mode: 'solution' | 'knowledge'; title: string; defaultReason: string; introduction: string; generationHint: string
  empty: C; normalize: (content: C) => C; isContent: (value: unknown) => value is C
  hasItems: (content: C) => boolean; canGenerate: (content: C) => boolean
  outputSummary: (content: C) => { label: string; detail: string }
  checkNames: Array<[keyof O['checks'] & string, string]>
  api: {
    workspace: (id: string, signal: AbortSignal) => Promise<W>
    save: (id: string, input: { content: C; expected_version: number; request_key: string; reason: string }, csrf: string) => Promise<W>
    action: (id: string, input: { action: 'confirm' | 'generate'; expected_version: number; request_key: string; reason: string }, csrf: string) => Promise<W>
    revision: (id: number, signal: AbortSignal) => Promise<{ revision: NonNullable<W['revision']> }>
    history: (id: string, before: number, signal: AbortSignal) => Promise<Pick<W, 'history' | 'nodes' | 'history_next_before'>>
    outputs: (id: string, before: string, signal: AbortSignal) => Promise<Pick<W, 'outputs' | 'output_next_before'>>
    output: (id: string, signal: AbortSignal) => Promise<{ output: O }>
    outputAction: (id: string, input: { action: 'cancel' | 'retry' | 'check'; expected_version: number; request_key: string; reason: string; checks?: O['checks'] }, csrf: string) => Promise<W>
  }
  editor: (props: { focusItem?: { id: string }; content: C; workspace: W; materialId: string; csrfToken: string; writable: boolean
    onChange: (content: C) => void; onAssetsChanged: (assets: W['assets']) => void
    onBusyChange: (busy: boolean) => void; onUnauthorized: () => void }) => ReactNode
  compare: (props: { left: C; leftTitle: string; right: C; rightTitle: string; workspace: W }) => ReactNode
}
