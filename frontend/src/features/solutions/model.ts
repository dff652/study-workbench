import { makeRequestKey } from '../materials/request-keys'
import type { SolutionContent, SolutionPart, SolutionQuestion } from '../../types'

export function newSolutionId(prefix: string) {
  return `${prefix}-${makeRequestKey().replaceAll('-', '')}`
}

export function newSolutionQuestion(lectureId: string): SolutionQuestion {
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
    pitfalls: [],
    formulas: [],
    figures: [],
    links: [],
    corrections: [],
    unknowns: [],
  }
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

export function contentHasMinimumForGeneration(content: SolutionContent) {
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
