import { getJson, postJson } from '../../api'
import type { KnowledgeChecks, KnowledgeContent, KnowledgeOutput, KnowledgeRevision, KnowledgeWorkspaceResponse } from './types'

function base(materialId: string) { return `/api/v1/materials/${encodeURIComponent(materialId)}/knowledge-explanations/` }
export const knowledgeApi = {
  workspace: (id: string, signal: AbortSignal) => getJson<KnowledgeWorkspaceResponse>(base(id), signal),
  save: (id: string, input: { content: KnowledgeContent; expected_version: number; request_key: string; reason: string }, csrf: string) => postJson<KnowledgeWorkspaceResponse>(base(id) + 'draft/', input, csrf),
  action: (id: string, input: { action: 'confirm' | 'generate'; expected_version: number; request_key: string; reason: string }, csrf: string) => postJson<KnowledgeWorkspaceResponse>(base(id) + 'actions/', input, csrf),
  history: (id: string, before: number, signal: AbortSignal) => getJson<Pick<KnowledgeWorkspaceResponse, 'history' | 'nodes' | 'history_next_before'>>(base(id) + `history/?before=${before}`, signal),
  outputs: (id: string, before: string, signal: AbortSignal) => getJson<Pick<KnowledgeWorkspaceResponse, 'outputs' | 'output_next_before'>>(base(id) + `outputs/?before=${encodeURIComponent(before)}`, signal),
  revision: (id: number, signal: AbortSignal) => getJson<{ revision: KnowledgeRevision }>(`/api/v1/solutions/revisions/${id}/`, signal),
  output: (id: string, signal: AbortSignal) => getJson<{ output: KnowledgeOutput }>(`/api/v1/solutions/outputs/${encodeURIComponent(id)}/`, signal),
  outputAction: (id: string, input: { action: 'cancel' | 'retry' | 'check'; expected_version: number; request_key: string; reason: string; checks?: KnowledgeChecks }, csrf: string) => postJson<KnowledgeWorkspaceResponse>(`/api/v1/solutions/outputs/${encodeURIComponent(id)}/actions/`, input, csrf),
}
