import { BookOpenCheck } from 'lucide-react'
import { SOURCE_KINDS, type Assessment, type Attempt, type LearnerProgressGroup, type LearnerProgressResponse } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, SOURCE_LABELS, SourceEvidence, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'

const KIND_LABELS = {
  knowledge: '知识点',
  method: '方法',
  question_type: '题型',
} as const

const INDEPENDENCE_LABELS: Record<string, string> = {
  confirmed_independent: '人工确认独立',
  not_independent: '确认非独立',
  unknown: '独立性未知',
}
const PROMPT_LABELS: Record<string, string> = {
  none_confirmed: '人工确认无提示',
  given: '有提示',
  unknown: '提示情况未知',
}
const ATTEMPT_KIND_LABELS: Record<string, string> = { first: '首次', correction: '订正', retry: '重做', retest: '复测' }

export function LearnerProgress({ remote, onRetry }: { remote: Remote<LearnerProgressResponse>; onRetry: () => void }) {
  if (remote.status === 'loading') return <LoadingState label='正在读取学习者的知识、方法和题型进度…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={onRetry} />

  const { groups, scope } = remote.data
  const knowledgeIndex = `/knowledge/?household_id=${encodeURIComponent(scope.household_id)}&mode=learn#question-index`
  return (
    <section className='space-y-4' aria-labelledby='learner-progress-title'>
      <div>
        <h2 id='learner-progress-title' className='text-lg font-semibold'>知识、方法与题型进度</h2>
        <p className='mt-1 text-xs text-muted-foreground'>截至 {scope.as_of || '日期未提供'}；按当前已确认关联与有效作答计数，不代表掌握程度。</p>
      </div>
      {groups.length === 0 ? (
        <div className='space-y-3'>
          <EmptyState title='还没有已确认的学习关联' detail='先确认题目与知识点、方法或题型的关系，再从关联记录查看真实作答；不会从空数据推断学习表现。' icon={BookOpenCheck} />
          <div className='flex justify-center'><ApiLink href={knowledgeIndex}>前往知识与题库检查题目关联</ApiLink></div>
        </div>
      ) : (
        <div className='grid items-start gap-3 xl:grid-cols-2'>
          {groups.map((group) => <LearnerProgressGroupCard key={`${group.kind}:${group.id}`} group={group} knowledgeIndex={knowledgeIndex} />)}
        </div>
      )}
    </section>
  )
}

function LearnerProgressGroupCard({ group, knowledgeIndex }: { group: LearnerProgressGroup; knowledgeIndex: string }) {
  return (
    <Card className='gap-0 py-0 shadow-sm'>
      <CardHeader className='border-b py-3'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div className='min-w-0'>
            <Badge variant='outline'>{KIND_LABELS[group.kind] || '未确定类型'}</Badge>
            <CardTitle className='mt-1 text-base'>{group.label || '未命名条目'}</CardTitle>
          </div>
          <ApiLink href={group.node_url}>查看关联条目</ApiLink>
        </div>
        <CardDescription>仅汇总已确认关联的题目和有效作答；跨题目版本按真实作答事件计数，多份评价不重复计为作答。</CardDescription>
      </CardHeader>
      <CardContent className='space-y-4 px-5 py-4'>
        <dl className='grid grid-cols-2 gap-x-5 gap-y-3 sm:grid-cols-4'>
          <Metric label='关联题目' value={group.question_count} unit='道' />
          <Metric label='有效作答' value={group.attempt_count} unit='次' />
          <Metric label='独立成功记录' value={group.independent_success_count} unit='次' />
          <Metric label='未知或待核实' value={group.unknown_evidence_count} unit='次' />
        </dl>

        {group.question_count === 0 ? (
          <div className='rounded-md border border-dashed px-3 py-3 text-sm'>
            <p className='font-medium'>当前没有关联的已确认题目</p>
            <p className='mt-1 text-muted-foreground'>此条目的作答计数为零；请先检查知识与题库中的题目关联。</p>
            <div className='mt-2'><ApiLink href={knowledgeIndex}>前往检查题目关联</ApiLink></div>
          </div>
        ) : group.attempt_count === 0 ? (
          <p className='rounded-md bg-muted/40 px-3 py-2 text-sm text-muted-foreground'>已有 {formatCount(group.question_count)} 道关联题目，尚无有效作答记录；当前是未测，不是表现结论。</p>
        ) : null}

        <section aria-label={`${group.label}作答来源计数`}>
          <h3 className='mb-2 text-xs font-semibold text-muted-foreground'>作答来源（次）</h3>
          <ul className='grid gap-x-5 gap-y-1 sm:grid-cols-2 lg:grid-cols-3'>
            {SOURCE_KINDS.map((kind) => (
              <li key={kind} className='flex items-center justify-between gap-3 border-b py-1.5 text-sm'>
                <span>{SOURCE_LABELS[kind]}</span>
                <span className='tabular-nums text-muted-foreground'>{group.source_counts[kind] === undefined ? '未提供' : formatCount(group.source_counts[kind])}</span>
              </li>
            ))}
          </ul>
        </section>

        {group.recent_attempts?.length ? (
          <section className='border-t pt-3'>
            <h3 className='mb-2 text-sm font-semibold'>最近真实作答</h3>
            <ol className='divide-y'>
              {group.recent_attempts.map((attempt) => <LearnerAttempt key={attempt.attempt_id} attempt={attempt} />)}
            </ol>
          </section>
        ) : group.attempt_count > 0 ? (
          <p className='border-t pt-3 text-sm text-muted-foreground'>统计到 {formatCount(group.attempt_count)} 次有效作答；当前接口没有提供可展开的事件摘要。</p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function Metric({ label, value, unit }: { label: string; value: number; unit: string }) {
  return (
    <div>
      <dt className='text-xs text-muted-foreground'>{label}</dt>
      <dd className='mt-1 font-semibold tabular-nums'>{formatCount(value)} <span className='text-xs font-normal text-muted-foreground'>{unit}</span></dd>
    </div>
  )
}

function LearnerAttempt({ attempt }: { attempt: Attempt }) {
  const dateLabel = attempt.actual_date_state === 'known' && attempt.actual_date
    ? attempt.actual_date
    : '实际作答日期未知'
  const sourceLabel = attempt.source_kind_label || SOURCE_LABELS[attempt.source_kind] || '来源未确定'
  const kindLabel = attempt.attempt_kind_label || ATTEMPT_KIND_LABELS[attempt.attempt_kind] || '作答类型未确定'
  const independenceLabel = attempt.independence_label || INDEPENDENCE_LABELS[attempt.independence] || '独立性未确定'
  const promptLabel = attempt.prompt_status_label || PROMPT_LABELS[attempt.prompt_status] || '提示情况未确定'
  const assessments = attempt.assessments.filter(isCurrentAcceptedAssessment)

  return (
    <li className='py-2 first:pt-0'>
      <details>
        <summary className='flex cursor-pointer list-none flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-sm text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'>
          <span className='min-w-0 font-medium'>{attempt.question_text || '题目未记录'} <span className='font-normal text-muted-foreground'>· {dateLabel}</span></span>
          <span className='text-xs text-muted-foreground'>{sourceLabel} · {kindLabel} · 展开证据</span>
        </summary>
        <div className='mt-3 space-y-2 rounded-md bg-muted/30 p-3 text-sm'>
          <div className='flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground'>
            <span>{independenceLabel}</span>
            <span>{promptLabel}</span>
            {attempt.prompts.length ? <span>记录的提示：{attempt.prompts.join('、')}</span> : null}
          </div>
          {assessments.length > 0 ? assessments.map((assessment) => <AssessmentEvidence key={assessment.assessment_revision_id} assessment={assessment} />) : (
            <p className='text-muted-foreground'>当前没有已接受并发布的评价；此处不推断结果。</p>
          )}
          <div>
            <h4 className='mb-1 text-xs font-semibold text-muted-foreground'>原图来源</h4>
            <SourceEvidence sources={attempt.sources} />
          </div>
          <div className='flex flex-wrap gap-x-4 gap-y-1'>
            <ApiLink href={attempt.attempt_url}>查看本次作答</ApiLink>
            <ApiLink href={attempt.question_url}>查看题目</ApiLink>
          </div>
        </div>
      </details>
    </li>
  )
}

function isCurrentAcceptedAssessment(assessment: Assessment) {
  return assessment.current && assessment.published && assessment.review_state === 'accepted'
}

function AssessmentEvidence({ assessment }: { assessment: Assessment }) {
  return (
    <section className='space-y-2 border-t pt-2'>
      <h4 className='text-xs font-semibold'>已接受评价</h4>
      {assessment.dimensions.length ? assessment.dimensions.map((dimension) => (
        <div key={dimension.dimension} className='rounded-sm border bg-background px-2 py-2'>
          <p className='font-medium'>{dimension.dimension_label || '评价项目未命名'}</p>
          <p className='mt-1 text-xs text-muted-foreground'>{dimension.judgment_label || '判断未提供'} · {dimension.basis_label || '依据未提供'}</p>
          {dimension.rationale ? <p className='mt-1 whitespace-pre-wrap text-sm'>{dimension.rationale}</p> : null}
          {dimension.unknown_reason ? <p className='mt-1 text-sm text-amber-900'>未确定原因：{dimension.unknown_reason}</p> : null}
          <div className='mt-2'><SourceEvidence sources={dimension.sources} /></div>
        </div>
      )) : <p className='text-sm text-muted-foreground'>评价没有记录维度。</p>}
    </section>
  )
}
