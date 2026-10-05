import { makeRequestKey } from '../materials/request-keys'
import type {
  AnySolutionContent,
  SolutionPart,
  SolutionQuestion,
  SolutionStep,
  SolutionSource,
  SolutionFigure,
  StructuredSolutionContent,
  StructuredSolutionQuestion,
} from '../../types'

export function newSolutionId(prefix: string) {
  return `${prefix}-${makeRequestKey().replaceAll('-', '')}`
}

export function newSolutionQuestion(lectureId: string): StructuredSolutionQuestion {
  return {
    id: newSolutionId('question'),
    question_revision_id: null,
    lecture_id: lectureId,
    number: '',
    title: '',
    statement: { text: null, status: 'unknown' },
    sources: [],
    parts: [],
    thinking: '',
    lecture_method: '',
    alternative_method: '',
    steps: [],
    alternative_steps: [],
    pitfalls: [],
    formulas: [],
    figures: [],
    links: [],
    corrections: [],
    unknowns: [],
  }
}

export function newSolutionStep(): SolutionStep {
  return { id: newSolutionId('step'), text: '', formula: null, figure: null, new_page: false }
}

export function toStructuredSolutionContent(content: AnySolutionContent): StructuredSolutionContent {
  if (content.schema_version !== 'swb.solution.v1') return { ...content, schema_version: 'swb.solution.v3', school_subject: content.school_subject || 'unknown' }
  return {
    ...content,
    schema_version: 'swb.solution.v3',
    school_subject: 'unknown',
    questions: content.questions.map((question) => ({
      ...question,
      steps: question.steps.map((text) => ({ id: newSolutionId('step'), text, formula: null, figure: null, new_page: false })),
      alternative_steps: [],
    })),
  }
}

export function isAnySolutionContent(value: unknown): value is AnySolutionContent {
  if (!isRecord(value) || !['swb.solution.v1', 'swb.solution.v2', 'swb.solution.v3'].includes(String(value.schema_version))) return false
  if (value.schema_version === 'swb.solution.v3' && typeof value.school_subject !== 'string') return false
  if (typeof value.title !== 'string' || !Array.isArray(value.lectures) || !value.lectures.every(isLecture)) return false
  if (!Array.isArray(value.questions) || !value.questions.every((question) => isSolutionQuestion(question, value.schema_version !== 'swb.solution.v1'))) return false
  const outputs = value.outputs
  if (!isRecord(outputs)) return false
  return ['per_question', 'per_lecture', 'combined'].every((key) => isFormatList(outputs[key]))
}

function isSolutionQuestion(value: unknown, structured: boolean): value is SolutionQuestion | StructuredSolutionQuestion {
  if (!isRecord(value) || typeof value.id !== 'string' || !isNullableString(value.question_revision_id)
    || typeof value.lecture_id !== 'string' || typeof value.number !== 'string' || typeof value.title !== 'string') return false
  if (!isRecord(value.statement) || !isNullableString(value.statement.text)
    || !['complete', 'partial', 'unknown'].includes(String(value.statement.status))) return false
  if (!Array.isArray(value.sources) || !value.sources.every(isSource) || !Array.isArray(value.parts) || !value.parts.every(isPart)) return false
  if (typeof value.thinking !== 'string' || typeof value.lecture_method !== 'string' || typeof value.alternative_method !== 'string') return false
  if (structured) {
    if (!Array.isArray(value.steps) || !value.steps.every(isSolutionStep)
      || !Array.isArray(value.alternative_steps) || !value.alternative_steps.every(isSolutionStep)) return false
  } else if (!isStringList(value.steps)) return false
  if (!isStringList(value.pitfalls) || !isStringList(value.formulas)) return false
  if (!Array.isArray(value.figures) || !value.figures.every(isFigure) || !Array.isArray(value.links) || !value.links.every(isLink)) return false
  if (!Array.isArray(value.corrections) || !value.corrections.every(isCorrection) || !isStringList(value.unknowns)) return false
  return true
}

function isLecture(value: unknown) {
  return isRecord(value) && typeof value.id === 'string' && typeof value.title === 'string'
}

function isSource(value: unknown): value is SolutionSource {
  if (!isRecord(value) || typeof value.page_id !== 'string') return false
  return value.region === null || (Array.isArray(value.region) && value.region.length === 4 && value.region.every(isNumber))
}

function isPart(value: unknown): value is SolutionPart {
  return isRecord(value) && typeof value.id === 'string' && isNullableString(value.parent_id) && typeof value.label === 'string'
    && isNullableString(value.statement) && isNullableString(value.answer) && isNullableString(value.unit)
}

function isSolutionStep(value: unknown): value is SolutionStep {
  return isRecord(value) && typeof value.id === 'string' && typeof value.text === 'string'
    && isNullableString(value.formula) && (value.figure === null || isFigure(value.figure)) && typeof value.new_page === 'boolean'
}

function isFigure(value: unknown): value is SolutionFigure {
  return isRecord(value) && typeof value.asset_id === 'string'
    && ['question', 'method', 'answer'].includes(String(value.role))
    && typeof value.caption === 'string' && isNumber(value.width_mm)
}

function isLink(value: unknown) {
  return isRecord(value) && typeof value.revision_id === 'string'
    && ['knowledge', 'primary_method', 'secondary_method', 'question_type'].includes(String(value.relation))
}

function isCorrection(value: unknown) {
  return isRecord(value) && ['printing_error', 'naming', 'draft_correction'].includes(String(value.kind))
    && typeof value.original === 'string' && typeof value.replacement === 'string' && typeof value.basis === 'string'
}

function isFormatList(value: unknown) {
  return Array.isArray(value) && value.every((format) => format === 'pdf' || format === 'docx')
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function newSolutionPart(parentId: string | null = null): SolutionPart {
  return {
    id: newSolutionId('part'),
    parent_id: parentId,
    label: '',
    statement: null,
    answer: null,
    unit: null,
  }
}

export function contentHasMinimumForGeneration(content: AnySolutionContent) {
  return content.questions.length > 0
    && content.questions.every((question) => question.parts.length > 0 && question.sources.length > 0)
    && Object.values(content.outputs).some((formats) => formats.length > 0)
}

export function outputIsProcessing(state: string) {
  return state === 'queued' || state === 'running'
}

export function solutionText(value: string | null | undefined) {
  return value?.trim() || '未知'
}
