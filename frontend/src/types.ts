export const SOURCE_KINDS = [
  'independent_answer',
  'assisted_answer',
  'classroom_note',
  'copied_work',
  'unknown',
] as const

export type SourceKind = (typeof SOURCE_KINDS)[number]

export type ApiErrorPayload = {
  schema_version: 'swb.api.v1'
  error: { code: string; message: string }
}

export type SessionResponse = {
  schema_version: 'swb.api.v1'
  user: { username: string }
  households: Array<{ id: string; name: string; role: string }>
  csrf_token: string
}

export type Learner = {
  id: string
  display_name: string
  grade: string | null
  profile_url: string
  report_url: string
}

export type LearnersResponse = {
  schema_version: 'swb.api.v1'
  items: Learner[]
}

export type EvidenceSource = {
  image_id: string
  region_id: string
  region_revision_id: string
  purpose: string
  label: string
  page_url: string | null
  preview_url: string | null
  region_style: string
  missing: boolean
}

export type AssessmentDimension = {
  dimension: string
  judgment: string
  basis: string
  dimension_label: string
  judgment_label: string
  basis_label: string
  rationale: string
  unknown_reason: string
  sources: EvidenceSource[]
}

export type Assessment = {
  assessment_id: string
  assessment_revision_id: string
  attempt_revision_id: string
  review_state: string
  current: boolean
  review_state_label: string
  published: boolean
  reviewer_id: string | null
  dimensions: AssessmentDimension[]
}

export type Attempt = {
  attempt_id: string
  attempt_revision_id: string
  attempt_kind: string
  attempt_kind_label?: string
  source_kind: SourceKind
  source_kind_label?: string
  independence: string
  independence_label?: string
  prompt_status: string
  prompt_status_label?: string
  prompts: string[]
  actual_date_state: string
  actual_date: string | null
  legibility: string
  legibility_label?: string
  answer_text: string
  state: string
  state_label?: string
  question_id: string
  question_revision_id: string
  question_text: string
  independent_success: boolean
  sources: EvidenceSource[]
  assessments: Assessment[]
  attempt_url: string
  question_url: string | null
  previous_attempt_id: string | null
}

export type AttemptResponse = {
  schema_version: 'swb.api.v1'
  scope: {
    household_id: string
    learner_id: string
    date_from: string | null
    date_to: string | null
    source_kind: SourceKind | null
    metric_version: 'evidence.v1'
  }
  items: Attempt[]
  total: number
  page: number
  page_size: number
}

export type OverviewResponse = {
  schema_version: 'swb.api.v1'
  scope: AttemptResponse['scope']
  metrics: {
    attempt_count: number
    question_count: number
    source_counts: Partial<Record<SourceKind, number>>
    unknown_date_count: number
    independent_success_count: number
    independent_success_rate: number | null
    rate_state: string
    repeated_error_count: number
    insufficient_evidence_count: number
  }
  findings: {
    observed_correct_methods: Array<{
      attempt_id: string
      attempt_revision_id: string
      assessment_revision_id: string
      question_id: string
      question_revision_id: string
      dimension: string
      dimension_label: string
      sources: EvidenceSource[]
    }>
    insufficient_evidence: Array<{
      attempt_id: string
      assessment_revision_id: string | null
      dimension: string | null
      dimension_label: string | null
      judgment: string
      basis: string
      judgment_label: string
      basis_label: string
      reason: string
      sources: EvidenceSource[]
    }>
    repeated_errors: Array<{
      question_id: string
      dimension: string
      dimension_label: string
      occurrence_count: number
      evidence: Array<{
        attempt_id: string
        attempt_revision_id: string
        assessment_revision_id: string
        question_revision_id: string
        judgment: string
        basis: string
        judgment_label: string
        basis_label: string
        sources: EvidenceSource[]
      }>
    }>
    known_actual_date_intervals: Array<{
      question_id: string
      from_attempt_id: string
      to_attempt_id: string
      from_actual_date: string
      to_actual_date: string
      days: number
    }>
  }
  links: {
    profile_url: string | null
    report_url: string | null
    schedule_url: string | null
  }
}

export type Filters = {
  dateFrom: string
  dateTo: string
  sourceKind: SourceKind | ''
}

export type AboutResponse = {
  schema_version: 'swb.api.v1'
  version: string
  release_state: string
  source_revision: string
  build_date: string | null
  changelog: Array<{ version: string; date: string; changes: string[] }>
  help_url: string
}

export type MaterialRow = {
  id: string
  title: string
  page_count: number
  created_at: string
  material_url: string
  prepare_url: string
}

export type MaterialListResponse = {
  schema_version: 'swb.api.v1'
  items: MaterialRow[]
  total: number
  page?: number
  page_size?: number
  has_next?: boolean
  query?: string
}

export type ProgressMaterial = {
  id: string | number
  title: string
  page_count: number
  pages_complete: number
  pages_unread: number
  pages_need_retake: number
  questions_confirmed: number
  questions_pending: number
  material_url: string
}

export type ProgressResponse = {
  schema_version: 'swb.api.v1'
  scope: {
    household_id: string
    metric_version: 'progress.v1'
    as_of: string
  }
  counts: {
    material_count: number
    page_count: number
    pages_complete: number
    pages_unread: number
    pages_need_retake: number
    questions_confirmed: number
    questions_pending: number
    open_workflows: number
    completed_workflows: number
  }
  materials: ProgressMaterial[]
  total: number
}

export type LearnerProgressGroup = {
  id: string | number
  kind: 'knowledge' | 'method' | 'question_type'
  label: string
  question_count: number
  attempt_count: number
  independent_success_count: number
  unknown_evidence_count: number
  source_counts: Partial<Record<SourceKind, number>>
  node_url: string | null
}

export type LearnerProgressResponse = {
  schema_version: 'swb.api.v1'
  scope: {
    household_id: string
    learner_id: string
    metric_version: 'progress.v1'
    as_of: string
  }
  groups: LearnerProgressGroup[]
}

export type ScheduleState = 'planned' | 'rescheduled' | 'completed' | 'cancelled'
export type ScheduleAction = 'rescheduled' | 'completed' | 'cancelled'

export type ScheduleHistoryEntry = {
  revision_no: number
  action: 'planned' | ScheduleAction
  due_date: string
  reason: string
  attempt_revision_id: string | number | null
  actual_date: string | null
  recorded_at: string
}

export type ScheduleAttemptChoice = {
  revision_id: string | number
  label: string
  actual_date: string | null
  source_kind: SourceKind
}

export type ReviewSchedule = {
  id: string | number
  question_id: string | number
  question_text: string
  goal: string
  prompt_plan: string
  due_date: string
  state: ScheduleState
  overdue: boolean
  target_stale: boolean
  context: unknown
  detail_url: string | null
  history: ScheduleHistoryEntry[]
  attempt_choices: ScheduleAttemptChoice[]
}

export type SchedulesResponse = {
  schema_version: 'swb.api.v1'
  scope: {
    household_id: string
    learner_id: string
  }
  counts: {
    pending: number
    overdue: number
    completed: number
    cancelled: number
  }
  items: ReviewSchedule[]
}

export type ScheduleOptionsResponse = {
  schema_version: 'swb.api.v1'
  questions: Array<{ revision_id: string | number; label: string }>
  context: unknown
}

export type CreateScheduleInput = {
  question_revision_id: string | number
  due_date: string
  goal: string
  prompt_plan: string
  reason: string
  expected: unknown
  request_key: string
}

export type ScheduleActionInput = {
  action: ScheduleAction
  expected: unknown
  reason: string
  request_key: string
  due_date?: string
  goal?: string
  prompt_plan?: string
  attempt_revision_id?: string | number
}

export type ContentSource = {
  page_id: string
  bbox: [number, number, number, number]
}

export type FormulaAst = Record<string, unknown>

export type ContentAnswer = {
  body: string
  formulas: FormulaAst[]
  basis: string
  confirmed: boolean
}

export type MaterialContentQuestion = {
  id: string
  revision_id: string
  number: string
  printed_text: string
  working_text: string
  sources: ContentSource[]
  confirmed: boolean
  answer: ContentAnswer | null
  edit_context: unknown
  question_url: string | null
}

export type MaterialContentNode = {
  id: string
  kind: 'knowledge' | 'method' | 'question_type'
  label: string
  node_url: string | null
}

export type MaterialContentResponse = {
  schema_version: 'swb.api.v1'
  context: { source_stamp: string }
  questions: MaterialContentQuestion[]
  nodes: MaterialContentNode[]
}

export type ContentNodeInput = {
  kind: MaterialContentNode['kind']
  data: Record<string, string>
}

export type SaveContentInput = {
  expected: MaterialContentResponse['context']
  request_key: string
  reason: string
  checked: true
  question_id?: string
  printed_text: string
  original_number: string
  sources: ContentSource[]
  answer?: { body: string; formulas: FormulaAst[]; basis: string }
  nodes?: ContentNodeInput[]
}

export type SaveContentDraftInput = {
  expected: MaterialContentResponse['context']
  request_key: string
  reason: string
  question_id?: string
  printed_text: string
  original_number: string
  sources: ContentSource[]
}

export type SaveErratumInput = {
  expected: MaterialContentResponse['context']
  question_id: string
  corrected_text: string
  basis: string
  checked: true
  reason: string
  request_key: string
}

export type PageReadingRecord = {
  reading: string
  coverage: string
  partitions: Array<{ kind: 'theory' | 'question' | 'diagram' | 'handwriting' | 'unknown'; bbox: [number, number, number, number] }>
  pending_items: string[]
  basis: string
  revision_no: number
  recorded_at: string
}

export type PageReadingResponse = {
  schema_version: 'swb.api.v1'
  context: unknown
  current: PageReadingRecord | null
  history: PageReadingRecord[]
}

export type SavePageReadingInput = {
  expected: unknown
  request_key: string
  reading: 'unread' | 'read' | 'needs_retake'
  coverage: 'partial' | 'complete'
  partitions: PageReadingRecord['partitions']
  pending_items: string[]
  basis: string
}

export type MaterialPage = {
  id: string
  position: number
  sha256: string
  width: number
  height: number
  page_url: string
  preview_url: string
}

export type ReadinessQuestion = {
  question_id: string
  revision_id: string
  number: string
  text: string
  confirmed: boolean
  answer_ready: boolean
}

export type Readiness = {
  ready: boolean
  gaps: string[]
  content_gaps: string[]
  questions: ReadinessQuestion[]
}

export type WorkflowContext = { version: number; source_stamp: string }

export type WorkflowJob = {
  id: string
  material_id: string
  state: 'needs_review' | 'ready' | 'queued' | 'running' | 'output_check' | 'complete' | 'failed' | 'cancelled'
  context: WorkflowContext
  created_at: string
  updated_at: string
  error_code: string | null
  record_count: number
  result: {
    learner_id: string | null
    mapping?: Record<string, unknown>
    packet_id?: string
  }
}

export type SkillImportSource = { id: string; page_id: string; sha256: string }

export type SkillImportRecord = {
  id: string
  kind: 'question' | 'knowledge' | 'method' | 'question_type' | 'answer' | 'link' | 'observation' | 'diagram'
  data: Record<string, unknown>
}

export type SkillImport = {
  schema_version: 'swb.skill-import.v1' | 'swb.skill-import.v2'
  assets?: Record<string, { sha256: string; media_type: string; base64: string }>
  sources: SkillImportSource[]
  records: SkillImportRecord[]
  packet?: unknown
  ledger?: unknown
  catalog?: unknown
  tool_inputs?: Record<string, unknown>
}

export type MaterialDetailResponse = {
  schema_version: 'swb.api.v1'
  material: MaterialRow
  pages: MaterialPage[]
  readiness: Readiness
  jobs: WorkflowJob[]
}

export type WorkflowLinks = {
  material_url: string
  prepare_url: string
  ai_url: string
  preview_url?: string
  download_url?: string
}

export type WorkflowEvent = {
  version: number
  action: string
  details: Record<string, unknown>
  created_at: string
}

export type WorkflowDetailResponse = {
  schema_version: 'swb.api.v1'
  job: WorkflowJob
  records: SkillImportRecord[]
  sources: SkillImportSource[]
  assets?: Record<string, { media_type: 'image/png'; preview_url: string }>
  readiness: Readiness
  links: WorkflowLinks
  events: WorkflowEvent[]
}

export type PreparationNode = {
  kind: 'knowledge' | 'method' | 'question_type'
  data: Record<string, string>
}

export type PreparationProposal = {
  printed_text: string | null
  missing_fields: string[]
  nodes: PreparationNode[]
  answer: { body: string; formulas: FormulaAst[]; basis: string } | null
}

export type PreparationStage = {
  id: string
  state: 'queued' | 'running' | 'awaiting_review' | 'failed' | 'cancelled' | 'stale' | 'applied'
  question_id: string
  sources: ContentSource[]
  proposal: PreparationProposal | null
  can_confirm: boolean
  expected: unknown
  error_code: string | null
  record_count: number
  created_at: string
}

export type WorkflowPreparationResponse = {
  schema_version: 'swb.api.v1'
  job: WorkflowJob
  config: {
    enabled: boolean
    outbound_scope: string | null
    max_requests: number
    max_seconds: number
    budget_usd: string | null
  }
  stages: PreparationStage[]
  limits: { used_requests: number; max_requests: number; max_seconds: number }
}

export type QueuePreparationInput = {
  expected: WorkflowContext
  request_key: string
  sources: ContentSource[]
  question_id?: string
  reason: string
}

export type ConfirmPreparationInput = {
  expected: unknown
  request_key: string
  reason: string
  checked: true
  printed_text: string
  original_number: string
  sources: ContentSource[]
  answer?: { body: string; formulas: FormulaAst[]; basis: string }
  nodes?: PreparationNode[]
}

export type CancelPreparationInput = {
  expected: unknown
  request_key: string
  reason: string
}

export type SolutionSource = { page_id: string; region: [number, number, number, number] | null }
export type SolutionPart = {
  id: string; parent_id: string | null; label: string
  statement: string | null; answer: string | null; unit: string | null
}
export type SolutionQuestion = {
  id: string; question_revision_id: string | null; lecture_id: string; number: string; title: string
  statement: { text: string | null; status: 'complete' | 'partial' | 'unknown' }
  sources: SolutionSource[]; parts: SolutionPart[]
  thinking: string; lecture_method: string; alternative_method: string
  steps: string[]; pitfalls: string[]; formulas: string[]
  figures: Array<{ asset_id: string; role: 'question' | 'method' | 'answer'; caption: string; width_mm: number }>
  links: Array<{ revision_id: string; relation: 'knowledge' | 'primary_method' | 'secondary_method' | 'question_type' }>
  corrections: Array<{ kind: 'printing_error' | 'naming' | 'draft_correction'; original: string; replacement: string; basis: string }>
  unknowns: string[]
}
export type SolutionContent = {
  schema_version: 'swb.solution.v1'; title: string
  lectures: Array<{ id: string; title: string }>; questions: SolutionQuestion[]
  outputs: Record<'per_question' | 'per_lecture' | 'combined', Array<'pdf' | 'docx'>>
}
export type SolutionFigure = SolutionQuestion['figures'][number]
export type SolutionStep = {
  id: string; text: string; formula: string | null
  figure: SolutionFigure | null; new_page: boolean
}
export type StructuredSolutionQuestion = Omit<SolutionQuestion, 'steps'> & {
  steps: SolutionStep[]; alternative_steps: SolutionStep[]
}
export type StructuredSolutionContent = Omit<SolutionContent, 'schema_version' | 'questions'> & {
  schema_version: 'swb.solution.v2'; questions: StructuredSolutionQuestion[]
}
export type AnySolutionContent = SolutionContent | StructuredSolutionContent
export type SolutionAsset = {
  id: string; kind: 'source_crop' | 'source_image' | 'auxiliary'; label: string; basis: string
  source: SolutionSource | null; width: number; height: number; url: string
}
export type SolutionRevision = {
  id: number; version: number; created_at: string; author: string; reason: string
  content: AnySolutionContent; confirmed: boolean; gaps: Array<{ question_id: string; message: string }>
}
export type SolutionOutput = {
  id: string; revision_id: number; revision_version: number; version: number
  state: 'queued' | 'running' | 'output_check' | 'complete' | 'failed' | 'cancelled'
  state_label: string; message: string; created_at: string
  documents: Array<{ id: string; title: string; organization: 'per_question' | 'per_lecture' | 'combined'; question_ids: string[]; page_count: number; pdf_url: string | null; docx_url: string | null; previews: string[] }>
  checks: Record<'content' | 'math' | 'pdf_visual' | 'word_pc' | 'word_macos', { status: 'pass' | 'fail' | 'not_tested'; notes: string }>
  zip_url: string | null
}
export type SolutionWorkspaceResponse = {
  schema_version: 'swb.api.v1'; material: { id: string; title: string }; writable: boolean
  revision: SolutionRevision | null; initial_content: AnySolutionContent
  source_stamp?: string
  history: Array<Omit<SolutionRevision, 'content' | 'gaps'>>; outputs: SolutionOutput[]
  history_next_before?: number | null; output_next_before?: string | null
  assets: SolutionAsset[]
  pages: Array<{ id: string; label: string; width: number; height: number; preview_url: string; detail_url: string }>
  questions: Array<{ revision_id: string; label: string; statement: string; sources: SolutionSource[]; detail_url: string }>
  nodes: Array<{ revision_id: string; kind: 'knowledge' | 'method' | 'question_type'; label: string; detail_url: string; selectable?: boolean }>
}
export type SolutionHistoryResponse = {
  schema_version: 'swb.api.v1'; history: SolutionWorkspaceResponse['history']
  nodes: SolutionWorkspaceResponse['nodes']; history_next_before: number | null
}
export type SolutionOutputsResponse = {
  schema_version: 'swb.api.v1'; outputs: SolutionOutput[]; output_next_before: string | null
}
export type SaveSolutionInput = { expected_version: number; request_key: string; content: AnySolutionContent; reason: string }
export type SolutionActionInput = {
  action: 'confirm' | 'generate'; expected_version: number; request_key: string; reason: string
}
export type SolutionOutputActionInput = {
  action: 'cancel' | 'retry' | 'check'; expected_version: number; request_key: string; reason: string
  checks?: SolutionOutput['checks']
}
