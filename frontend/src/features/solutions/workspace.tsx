import type { ReactNode } from 'react'
import { getSolutionHistory, getSolutionOutput, getSolutionOutputs, getSolutionRevision, getSolutions, saveSolution, solutionAction, solutionOutputAction } from '../../api'
import type { AnySolutionContent, SolutionFigure, SolutionOutput, SolutionQuestion, SolutionWorkspaceResponse, StructuredSolutionQuestion } from '../../types'
import { sameOriginHref } from '../../components/shared'
import { CompanionWorkspace } from '../companion/workspace'
import type { CompanionConfig, CompanionWorkspaceProps } from '../companion/types'
import { SolutionEditor } from './editor'
import { SUBJECTS } from '../materials/subjects'
import { contentHasMinimumForGeneration, isAnySolutionContent, solutionText, toStructuredSolutionContent } from './model'

const config: CompanionConfig<AnySolutionContent, SolutionOutput, SolutionWorkspaceResponse> = {
  mode: 'solution', title: '逐题讲解', defaultReason: '整理逐题解析',
  introduction: '按步骤整理讲义解法。解析文档与学习者真实作答分别记录，生成答案不会认定已经掌握。',
  generationHint: '生成需要每题至少有一个小问和原图来源，并选择输出格式；确认与生成请求仍会检查题目、知识和方法是否属于当前已发布版本。',
  empty: { schema_version: 'swb.solution.v3', school_subject: 'unknown', title: '', lectures: [], questions: [], outputs: { per_question: [], per_lecture: [], combined: [] } },
  normalize: toStructuredSolutionContent, isContent: isAnySolutionContent,
  hasItems: (content) => content.questions.length > 0, canGenerate: contentHasMinimumForGeneration,
  checkNames: [['content', '内容与来源'], ['math', '数学正确性'], ['pdf_visual', 'PDF 页面版式'], ['word_pc', 'Windows Word 实机'], ['word_macos', 'macOS Word 实机']],
  api: { workspace: getSolutions, save: saveSolution, action: solutionAction, revision: getSolutionRevision,
    history: getSolutionHistory, outputs: getSolutionOutputs, output: getSolutionOutput, outputAction: solutionOutputAction },
  editor: ({ content, writable, ...props }) => <SolutionEditor content={toStructuredSolutionContent(content)} canWrite={writable} {...props} />,
  compare: ContentCompare,
}

export function SolutionWorkspace(props: CompanionWorkspaceProps) {
  return <CompanionWorkspace {...props} config={config} />
}

type CompareWorkspace = Pick<SolutionWorkspaceResponse, 'pages' | 'nodes' | 'assets' | 'questions'>

function ContentCompare({ left, leftTitle, right, rightTitle, workspace }: { left: AnySolutionContent; leftTitle: string; right: AnySolutionContent; rightTitle: string; workspace: CompareWorkspace }) {
  const rightById = new Map(right.questions.map((question) => [question.id, question]))
  const leftById = new Map(left.questions.map((question) => [question.id, question]))
  const questionIds = Array.from(new Set([...left.questions.map((question) => question.id), ...right.questions.map((question) => question.id)]))
  return <div className='space-y-3'>
    <div className='grid gap-3 md:grid-cols-2'><ReviewColumn title={leftTitle} content={left} /><ReviewColumn title={rightTitle} content={right} /></div>
    {questionIds.map((id) => {
      const old = leftById.get(id)
      const current = rightById.get(id)
      return <section key={id} className='rounded-md border p-3'>
        <h4 className='font-semibold'>{old?.number || current?.number || '未编号题目'}{old?.title || current?.title ? ` · ${old?.title || current?.title}` : ''}</h4>
        <div className='mt-2 grid gap-3 md:grid-cols-2'><QuestionReview title={leftTitle} question={old} content={left} workspace={workspace} /><QuestionReview title={rightTitle} question={current} content={right} workspace={workspace} /></div>
      </section>
    })}
  </div>
}

function ReviewColumn({ title, content }: { title: string; content: AnySolutionContent }) {
  return <dl className='grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-md border bg-muted/10 p-3 text-sm'>
    <dt className='font-medium'>{title}</dt><dd>{content.title || '空标题'}</dd>
    <dt className='text-muted-foreground'>讲次</dt><dd>{content.lectures.map((lecture) => lecture.title).join('、') || '无'}</dd>
    <dt className='text-muted-foreground'>题目</dt><dd>{content.questions.length} 道</dd>
    <dt className='text-muted-foreground'>学校学科</dt><dd>{content.schema_version === 'swb.solution.v3' ? SUBJECTS.find(([id]) => id === content.school_subject)?.[1] || '未分类' : '未分类'}</dd>
    <dt className='text-muted-foreground'>输出设置</dt><dd>{outputPreferenceSummary(content)}</dd>
  </dl>
}

function QuestionReview({ title, question, content, workspace }: { title: string; question: AnySolutionContent['questions'][number] | undefined; content: AnySolutionContent; workspace: CompareWorkspace }) {
  if (!question) return <div className='rounded-md bg-muted/20 p-3 text-sm text-muted-foreground'>{title}：此题不存在</div>
  const statusLabels: Record<AnySolutionContent['questions'][number]['statement']['status'], string> = { complete: '已核对完整', partial: '部分记录', unknown: '未知 / 待核对' }
  const relationLabels: Record<AnySolutionContent['questions'][number]['links'][number]['relation'], string> = { knowledge: '知识条目', primary_method: '主要方法', secondary_method: '辅助方法', question_type: '题型' }
  const roleLabels: Record<AnySolutionContent['questions'][number]['figures'][number]['role'], string> = { question: '题面图', method: '解法图', answer: '答案图' }
  const correctionLabels: Record<AnySolutionContent['questions'][number]['corrections'][number]['kind'], string> = { printing_error: '资料印刷错误', naming: '命名调整', draft_correction: '解析草稿订正' }
  const linkedQuestion = question.question_revision_id ? workspace.questions.find((item) => item.revision_id === question.question_revision_id) : undefined
  const linkedQuestionHref = linkedQuestion ? sameOriginHref(linkedQuestion.detail_url) : null
  const structuredQuestion = content.schema_version === 'swb.solution.v2' || content.schema_version === 'swb.solution.v3' ? question as StructuredSolutionQuestion : null
  const stepRows: Array<{ label: string; text: string; formula: string | null; figure: SolutionFigure | null; newPage: boolean }> = structuredQuestion
    ? [...structuredQuestion.steps.map((step, index) => ({ label: `第 ${index + 1} 步`, text: step.text, formula: step.formula, figure: step.figure, newPage: step.new_page })), ...structuredQuestion.alternative_steps.map((step, index) => ({ label: `其他解法第 ${index + 1} 步`, text: step.text, formula: step.formula, figure: step.figure, newPage: step.new_page }))]
    : (question as SolutionQuestion).steps.map((text, index) => ({ label: `第 ${index + 1} 步`, text, formula: null, figure: null, newPage: false }))
  const stepFigures = stepRows.flatMap((step) => step.figure ? [step.figure] : [])
  const figures = [...question.figures, ...stepFigures]
  const rows: Array<[string, ReactNode]> = [
    ['讲次', content.lectures.find((lecture) => lecture.id === question.lecture_id)?.title || '讲次'],
    ['关联题目', linkedQuestion ? linkedQuestionHref
      ? <a className='text-primary underline underline-offset-2' href={linkedQuestionHref}>{linkedQuestion.label}</a>
      : linkedQuestion.label
      : question.question_revision_id ? '历史题目' : '未关联'],
    ['题干', <span>{solutionText(question.statement.text)} · {statusLabels[question.statement.status] || '未知状态'}</span>],
    ['原图来源', question.sources.length ? <ul className='space-y-1'>{question.sources.map((source, index) => {
      const page = workspace.pages.find((item) => item.id === source.page_id)
      const pageHref = page ? sameOriginHref(page.detail_url) : null
      return <li key={index}>{pageHref ? <a className='text-primary underline underline-offset-2' href={pageHref}>{page?.label || '资料页'}</a> : page?.label || '资料页'} · {source.region ? `原图区域 ${source.region.join(', ')} px` : '整页来源，区域未知'}</li>
    })}</ul> : '无'],
    ['小问/答案', question.parts.map((part) => `${part.label || '小问'}：${solutionText(part.statement)} → ${solutionText(part.answer)}（单位 ${solutionText(part.unit)}）`).join('；') || '无'],
    ['思路与解法', [question.thinking, question.lecture_method, question.alternative_method].map(solutionText).join(' / ')],
    ['步骤', stepRows.length ? <ol className='space-y-2'>{stepRows.map((step, index) => <li key={index} className='rounded border bg-background p-2'>
      <p className='font-medium'>{step.label}{step.newPage ? ' · 从新页开始' : ''}</p>
      {step.text ? <p className='mt-1 whitespace-pre-wrap'>{step.text}</p> : null}
      {step.formula ? <p className='mt-1 font-mono text-xs'>{step.formula}</p> : null}
      {step.figure ? <p className='mt-1 text-xs text-muted-foreground'>图示：{step.figure.caption || '已关联图示素材'}</p> : null}
    </li>)}</ol> : '无'],
    ['易错点', question.pitfalls.join('；') || '无'],
    ['公式', question.formulas.join('；') || '无'],
    ['知识关联', question.links.length ? <ul className='space-y-1'>{question.links.map((link, index) => {
      const node = workspace.nodes.find((item) => item.revision_id === link.revision_id)
      const nodeHref = node ? sameOriginHref(node.detail_url) : null
      return <li key={index}>{relationLabels[link.relation] || '其他关联'}：{nodeHref ? <a className='text-primary underline underline-offset-2' href={nodeHref}>{node?.label || '历史条目'}</a> : node?.label || '历史条目'}</li>
    })}</ul> : '无'],
    ['图示', figures.length ? <ul className='space-y-2'>{figures.map((figure, index) => {
      const asset = workspace.assets.find((item) => item.id === figure.asset_id)
      const src = asset ? sameOriginHref(asset.url) : null
      const caption = figure.caption || asset?.label || '图示素材'
      return <li key={index} className='space-y-1'>{src ? <img src={src} alt={caption} className='max-h-40 max-w-full rounded border bg-white object-contain' loading='lazy' /> : null}<span>{roleLabels[figure.role] || '其他用途'}：{caption} · {figure.width_mm} mm</span></li>
    })}</ul> : '无'],
    ['订正依据', question.corrections.map((item) => `${correctionLabels[item.kind] || '订正'}：${item.original} → ${item.replacement}（${item.basis}）`).join('；') || '无'],
    ['待核实事项', question.unknowns.join('；') || '无'],
  ]
  return <dl className='grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 gap-y-2 rounded-md bg-muted/10 p-3 text-sm'>
    {rows.map(([label, value]) => <div key={label} className='contents'><dt className='font-medium'>{label}</dt><dd className='break-words whitespace-pre-wrap'>{value}</dd></div>)}
  </dl>
}

function outputPreferenceSummary(content: AnySolutionContent) {
  const labels: Record<keyof AnySolutionContent['outputs'], string> = { per_question: '逐题', per_lecture: '按讲次', combined: '合并' }
  return Object.entries(content.outputs).flatMap(([organization, formats]) => formats.map((format) => `${labels[organization as keyof AnySolutionContent['outputs']]} ${format.toUpperCase()}`)).join('、') || '无'
}
