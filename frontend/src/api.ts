import type {
  AboutResponse,
  AttemptResponse,
  CancelPreparationInput,
  ConfirmPreparationInput,
  CreateScheduleInput,
  Filters,
  LearnerProgressResponse,
  LearnersResponse,
  MaterialContentResponse,
  MaterialDetailResponse,
  MaterialListResponse,
  OverviewResponse,
  PageReadingResponse,
  ProgressResponse,
  ScheduleActionInput,
  ScheduleOptionsResponse,
  SchedulesResponse,
  SaveContentInput,
  SaveContentDraftInput,
  SaveErratumInput,
  SavePageReadingInput,
  QueuePreparationInput,
  SkillImport,
  SessionResponse,
  WorkflowDetailResponse,
  WorkflowJob,
  WorkflowPreparationResponse,
} from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError('服务返回了无法读取的响应，请重试。', response.status, 'invalid_json')
  }

  if (!response.ok) {
    const errorBody = body as { error?: { code?: string; message?: string } }
    throw new ApiError(
      errorBody.error?.message || '请求未完成，请重试。',
      response.status,
      errorBody.error?.code || 'request_failed',
    )
  }

  if (
    typeof body !== 'object' ||
    body === null ||
    !('schema_version' in body) ||
    body.schema_version !== 'swb.api.v1'
  ) {
    throw new ApiError('服务响应版本不匹配，请重试。', response.status, 'schema_mismatch')
  }

  return body as T
}

export async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: 'GET',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json' },
    signal,
  })
  return parseJsonResponse<T>(response)
}

export async function postJson<T>(
  path: string,
  body: Record<string, unknown>,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify(body),
    signal,
  })
  return parseJsonResponse<T>(response)
}

export async function postMultipart<T>(
  path: string,
  body: FormData,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken },
    body,
    signal,
  })
  return parseJsonResponse<T>(response)
}

function withQuery(path: string, values: Record<string, string | number | null>) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== '') query.set(key, String(value))
  }
  return `${path}?${query.toString()}`
}

function filterQuery(filters: Filters) {
  return {
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
    ...(filters.sourceKind ? { source_kind: filters.sourceKind } : {}),
  }
}

export const api = {
  session: (signal: AbortSignal) => getJson<SessionResponse>('/api/v1/session/', signal),
  about: (signal: AbortSignal) => getJson<AboutResponse>('/api/v1/about/', signal),
  learners: (householdId: string, signal: AbortSignal) =>
    getJson<LearnersResponse>(
      withQuery('/api/v1/learners/', { household: householdId }),
      signal,
    ),
  overview: (
    learnerId: string,
    householdId: string,
    filters: Filters,
    signal: AbortSignal,
  ) =>
    getJson<OverviewResponse>(
      withQuery(`/api/v1/learners/${encodeURIComponent(learnerId)}/overview/`, {
        household: householdId,
        ...filterQuery(filters),
      }),
      signal,
    ),
  attempts: (
    learnerId: string,
    householdId: string,
    filters: Filters,
    page: number,
    signal: AbortSignal,
  ) =>
    getJson<AttemptResponse>(
      withQuery(`/api/v1/learners/${encodeURIComponent(learnerId)}/attempts/`, {
        household: householdId,
        ...filterQuery(filters),
        page,
        page_size: 20,
      }),
      signal,
    ),
  materials: (householdId: string, signal: AbortSignal, options: { q?: string; page?: number; pageSize?: number } = {}) =>
    getJson<MaterialListResponse>(
      withQuery('/api/v1/materials/', { household: householdId, q: options.q || '', page: options.page || 1, page_size: options.pageSize || 20 }),
      signal,
    ),
  progress: (householdId: string, signal: AbortSignal) =>
    getJson<ProgressResponse>(
      withQuery('/api/v1/progress/', { household: householdId }),
      signal,
    ),
  learnerProgress: (learnerId: string, householdId: string, signal: AbortSignal) =>
    getJson<LearnerProgressResponse>(
      withQuery(`/api/v1/learners/${encodeURIComponent(learnerId)}/progress/`, { household: householdId }),
      signal,
    ),
  schedules: (learnerId: string, householdId: string, signal: AbortSignal) =>
    getJson<SchedulesResponse>(
      withQuery(`/api/v1/learners/${encodeURIComponent(learnerId)}/schedules/`, { household: householdId }),
      signal,
    ),
  scheduleOptions: (learnerId: string, householdId: string, signal: AbortSignal) =>
    getJson<ScheduleOptionsResponse>(
      withQuery(`/api/v1/learners/${encodeURIComponent(learnerId)}/schedules/options/`, { household: householdId }),
      signal,
    ),
  createSchedule: (
    learnerId: string,
    householdId: string,
    input: CreateScheduleInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; schedule_id: string | number }>(
    withQuery(`/api/v1/learners/${encodeURIComponent(learnerId)}/schedules/`, { household: householdId }),
    input,
    csrf,
    signal,
  ),
  scheduleAction: (
    scheduleId: string | number,
    input: ScheduleActionInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; schedule_id: string | number }>(
    `/api/v1/schedules/${encodeURIComponent(String(scheduleId))}/actions/`,
    input,
    csrf,
    signal,
  ),
  materialContent: (materialId: string, signal: AbortSignal) =>
    getJson<MaterialContentResponse>(`/api/v1/materials/${encodeURIComponent(materialId)}/content/`, signal),
  saveMaterialContent: (
    materialId: string,
    input: SaveContentInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; question_id: string; revision_id: string }>(
    `/api/v1/materials/${encodeURIComponent(materialId)}/content/`, input, csrf, signal,
  ),
  saveMaterialContentDraft: (
    materialId: string,
    input: SaveContentDraftInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; question_id: string; revision_id: string }>(
    `/api/v1/materials/${encodeURIComponent(materialId)}/content/draft/`, input, csrf, signal,
  ),
  saveErratum: (
    materialId: string,
    input: SaveErratumInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; question_id: string; revision_id: string; erratum_revision_id: string }>(
    `/api/v1/materials/${encodeURIComponent(materialId)}/erratum/`, input, csrf, signal,
  ),
  pageReading: (pageId: string, signal: AbortSignal) =>
    getJson<PageReadingResponse>(`/api/v1/pages/${encodeURIComponent(pageId)}/reading/`, signal),
  savePageReading: (
    pageId: string,
    input: SavePageReadingInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<Record<string, unknown>>(
    `/api/v1/pages/${encodeURIComponent(pageId)}/reading/`, input, csrf, signal,
  ),
  createMaterial: (input: { household_id: string; title: string; request_key: string }, csrf: string, signal?: AbortSignal) =>
    postJson<{ schema_version: 'swb.api.v1'; material: MaterialListResponse['items'][number] }>(
      '/api/v1/materials/create/', input, csrf, signal,
    ),
  material: (materialId: string, signal: AbortSignal) =>
    getJson<MaterialDetailResponse>(`/api/v1/materials/${encodeURIComponent(materialId)}/`, signal),
  uploadPage: (materialId: string, file: File, requestKey: string, csrf: string, signal?: AbortSignal) => {
    const form = new FormData()
    form.append('file', file)
    form.append('request_key', requestKey)
    return postMultipart<{ schema_version: 'swb.api.v1'; page_id: string; duplicate: boolean }>(
      `/api/v1/materials/${encodeURIComponent(materialId)}/upload/`, form, csrf, signal,
    )
  },
  createWorkflow: (
    materialId: string,
    input: { request_key: string; learner_id?: string; proposal?: SkillImport; evidence_scope?: 'material_questions' | 'selected_learner_history' },
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; job: WorkflowJob }>(
    `/api/v1/materials/${encodeURIComponent(materialId)}/workflows/`, input, csrf, signal,
  ),
  workflow: (jobId: string, signal: AbortSignal) =>
    getJson<WorkflowDetailResponse>(`/api/v1/workflows/${encodeURIComponent(jobId)}/`, signal),
  workflowAction: (
    jobId: string,
    input: {
      action: string
      expected: { version: number; source_stamp: string }
      request_key: string
      reason?: string
      checks?: { pdf: boolean; docx: boolean; purposes: boolean }
    },
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; job: WorkflowJob }>(
    `/api/v1/workflows/${encodeURIComponent(jobId)}/actions/`, input, csrf, signal,
  ),
  workflowPreparation: (jobId: string, signal: AbortSignal) =>
    getJson<WorkflowPreparationResponse>(`/api/v1/workflows/${encodeURIComponent(jobId)}/preparation/`, signal),
  queueWorkflowPreparation: (
    jobId: string,
    input: QueuePreparationInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; job: WorkflowJob; stage_id: string }>(
    `/api/v1/workflows/${encodeURIComponent(jobId)}/preparation/`, input, csrf, signal,
  ),
  confirmWorkflowPreparation: (
    jobId: string,
    stageId: string,
    input: ConfirmPreparationInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; job: WorkflowJob; question_id: string; revision_id: string }>(
    `/api/v1/workflows/${encodeURIComponent(jobId)}/preparation/${encodeURIComponent(stageId)}/confirm/`, input, csrf, signal,
  ),
  cancelWorkflowPreparation: (
    jobId: string,
    stageId: string,
    input: CancelPreparationInput,
    csrf: string,
    signal?: AbortSignal,
  ) => postJson<{ schema_version: 'swb.api.v1'; job: WorkflowJob }>(
    `/api/v1/workflows/${encodeURIComponent(jobId)}/preparation/${encodeURIComponent(stageId)}/cancel/`, input, csrf, signal,
  ),
}

export function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : '连接暂时不可用，请重试。'
}

export function getSolutions(materialId: string, signal: AbortSignal) {
  return getJson<import('./types').SolutionWorkspaceResponse>(`/api/v1/materials/${encodeURIComponent(materialId)}/solutions/`, signal)
}
export function saveSolution(materialId: string, input: import('./types').SaveSolutionInput, csrfToken: string) {
  return postJson<import('./types').SolutionWorkspaceResponse>(`/api/v1/materials/${encodeURIComponent(materialId)}/solutions/draft/`, input, csrfToken)
}
export function solutionAction(materialId: string, input: import('./types').SolutionActionInput, csrfToken: string) {
  return postJson<import('./types').SolutionWorkspaceResponse>(`/api/v1/materials/${encodeURIComponent(materialId)}/solutions/actions/`, input, csrfToken)
}
export function solutionOutputAction(outputId: string, input: import('./types').SolutionOutputActionInput, csrfToken: string) {
  return postJson<import('./types').SolutionWorkspaceResponse>(`/api/v1/solutions/outputs/${encodeURIComponent(outputId)}/actions/`, input, csrfToken)
}
export async function uploadSolutionAsset(materialId: string, data: FormData, csrfToken: string) {
  const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/solutions/assets/`, {
    method: 'POST', body: data, credentials: 'same-origin', headers: { 'X-CSRFToken': csrfToken, Accept: 'application/json' },
  })
  return parseJsonResponse<import('./types').SolutionWorkspaceResponse>(response)
}
export function deriveSolutionAsset(materialId: string, input: {
  kind: 'source_image' | 'source_crop'; source: import('./types').SolutionSource
  label: string; basis: string; request_key: string
}, csrfToken: string) {
  return postJson<import('./types').SolutionWorkspaceResponse>(`/api/v1/materials/${encodeURIComponent(materialId)}/solutions/source-assets/`, input, csrfToken)
}
export function getSolutionRevision(revisionId: number, signal: AbortSignal) {
  return getJson<{ schema_version: 'swb.api.v1'; revision: import('./types').SolutionRevision }>(`/api/v1/solutions/revisions/${revisionId}/`, signal)
}
export function getSolutionHistory(materialId: string, before: number, signal: AbortSignal) {
  return getJson<import('./types').SolutionHistoryResponse>(`/api/v1/materials/${encodeURIComponent(materialId)}/solutions/history/?before=${before}`, signal)
}
export function getSolutionOutputs(materialId: string, before: string, signal: AbortSignal) {
  return getJson<import('./types').SolutionOutputsResponse>(`/api/v1/materials/${encodeURIComponent(materialId)}/solutions/outputs/?before=${encodeURIComponent(before)}`, signal)
}
export function getSolutionOutput(outputId: string, signal: AbortSignal) {
  return getJson<{ schema_version: 'swb.api.v1'; output: import('./types').SolutionOutput }>(`/api/v1/solutions/outputs/${encodeURIComponent(outputId)}/`, signal)
}
export function previewSolutionFormula(expression: string, csrfToken: string, signal?: AbortSignal) {
  return postJson<{ schema_version: 'swb.api.v1'; formula: unknown }>('/api/v1/solutions/formula-preview/', { expression }, csrfToken, signal)
}
