import { useEffect, useState, type CSSProperties } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Attempt, AttemptResponse, Assessment, EvidenceSource } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, sameOriginHref, SOURCE_LABELS, SourceEvidence, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table'

const ATTEMPT_KIND_LABELS: Record<string, string> = { first: '首次', correction: '订正', retry: '重做', retest: '复测' }
const INDEPENDENCE_LABELS: Record<string, string> = { confirmed_independent: '人工确认独立', not_independent: '确认非独立', unknown: '未知／未确认' }
const PROMPT_LABELS: Record<string, string> = { none_confirmed: '人工确认无提示', given: '有提示', unknown: '提示情况未知' }
const LEGIBILITY_LABELS: Record<string, string> = { readable: '清楚可辨', partial: '部分可辨', illegible: '看不清', blank: '空白', missing: '缺少证据', unknown: '未知' }
const ATTEMPT_STATE_LABELS: Record<string, string> = { active: '有效', withdrawn: '已撤回' }
const REVIEW_STATE_LABELS: Record<string, string> = { draft: '待审核', accepted: '已接受', rejected: '已退回', stale: '依赖已变化', withdrawn: '已撤回' }
const SOURCE_PURPOSE_LABELS: Record<string, string> = {
  question: '题目', handwriting: '笔迹', formula: '公式', diagram: '图示', definition: '定义', other: '其他',
}

function AttemptDetails({ attempt }: { attempt: Attempt }) {
  const actualDate = attempt.actual_date_state === 'known' && attempt.actual_date
    ? attempt.actual_date
    : '实际作答日期未知'
  return (
    <div className='grid gap-5 px-4 py-4 sm:px-5 2xl:grid-cols-2'>
      <section aria-labelledby='selected-attempt-heading' className='min-w-0 space-y-3'>
        <div>
          <h3 id='selected-attempt-heading' className='font-semibold'>本次作答与原图</h3>
          <p className='mt-1 text-sm leading-6'>{attempt.question_text || '题干未记录'}</p>
        </div>
        <dl className='grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2'>
          <div><dt className='text-muted-foreground'>实际作答日期</dt><dd className='mt-1'>{actualDate}</dd></div>
          <div><dt className='text-muted-foreground'>作答类型</dt><dd className='mt-1'>{displayLabel(attempt.attempt_kind_label, attempt.attempt_kind, ATTEMPT_KIND_LABELS)}</dd></div>
          <div><dt className='text-muted-foreground'>独立性</dt><dd className='mt-1'>{displayLabel(attempt.independence_label, attempt.independence, INDEPENDENCE_LABELS)}</dd></div>
          <div><dt className='text-muted-foreground'>提示情况</dt><dd className='mt-1'>{displayLabel(attempt.prompt_status_label, attempt.prompt_status, PROMPT_LABELS)}</dd></div>
          <div><dt className='text-muted-foreground'>笔迹可读性</dt><dd className='mt-1'>{displayLabel(attempt.legibility_label, attempt.legibility, LEGIBILITY_LABELS)}</dd></div>
          <div><dt className='text-muted-foreground'>记录状态</dt><dd className='mt-1'>{displayLabel(attempt.state_label, attempt.state, ATTEMPT_STATE_LABELS)}</dd></div>
        </dl>
        <div className='border-l-2 pl-3'>
          <p className='text-xs font-medium text-muted-foreground'>作答内容</p>
          <p className='mt-1 whitespace-pre-wrap text-sm leading-6'>{attempt.answer_text || '作答内容未记录。'}</p>
        </div>
        {attempt.prompts.length ? (
          <div>
            <p className='mb-1 text-xs font-medium text-muted-foreground'>提示记录</p>
            <ul className='list-disc space-y-1 pl-5 text-sm'>{attempt.prompts.map((prompt, index) => <li key={`${index}-${prompt}`}>{prompt}</li>)}</ul>
          </div>
        ) : null}
        <AttemptSources sources={attempt.sources} />
        <div className='flex flex-wrap gap-x-4 gap-y-2 pt-1 text-sm'>
          <ApiLink href={attempt.attempt_url}>查看这次作答及完整历史</ApiLink>
          <ApiLink href={attempt.question_url}>查看题目</ApiLink>
        </div>
      </section>

      <section aria-labelledby='selected-assessments-heading' className='min-w-0 space-y-3'>
        <div>
          <h3 id='selected-assessments-heading' className='font-semibold'>这次作答的评价历史</h3>
          <p className='mt-1 text-xs leading-5 text-muted-foreground'>每份评价按保存的修订分别展示；未知和未测状态会保留。</p>
        </div>
        {attempt.assessments.length === 0 ? (
          <p className='border-l-2 border-dashed pl-3 text-sm text-muted-foreground'>尚无评价记录，不能据此推断掌握状态。</p>
        ) : (
          <div className='divide-y'>
            {attempt.assessments.map((assessment) => <AssessmentHistory key={assessment.assessment_revision_id} assessment={assessment} />)}
          </div>
        )}
      </section>
    </div>
  )
}

function AttemptSources({ sources }: { sources: EvidenceSource[] }) {
  if (sources.length === 0) return <p className='text-sm text-muted-foreground'>原图来源未记录。</p>

  return (
    <div className='space-y-3'>
      <h4 className='text-sm font-medium'>来源照片</h4>
      <div className='grid gap-3 sm:grid-cols-2'>
        {sources.map((source) => {
          const preview = sameOriginHref(source.preview_url)
          const page = sameOriginHref(source.page_url)
          const region = parseRegionStyle(source.region_style)
          return (
            <figure key={`${source.region_revision_id}-${source.purpose}`} className='min-w-0'>
              {source.missing || !preview ? (
                <p className='flex min-h-24 items-center justify-center rounded-md border border-dashed px-3 text-center text-sm text-muted-foreground'>原图暂不可用</p>
              ) : (
                <a href={page || preview} aria-label={`查看原图：${source.label || '来源照片'}`} className='block max-w-full overflow-hidden rounded-md border bg-muted/20 text-center'>
                  <span className='relative inline-block max-w-full align-top'>
                    <img src={preview} alt={`${source.label || '来源照片'}，原图`} loading='lazy' className='block h-auto max-h-96 max-w-full w-auto' />
                    {region ? <span aria-hidden='true' className='pointer-events-none absolute border-2 border-amber-600' style={region} /> : null}
                  </span>
                </a>
              )}
              <figcaption className='mt-1 flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-xs text-muted-foreground'>
                <span>{source.label || '来源照片'} · {SOURCE_PURPOSE_LABELS[source.purpose] || '用途未知'}</span>
                {page ? <ApiLink href={source.page_url}>查看来源页</ApiLink> : null}
              </figcaption>
            </figure>
          )
        })}
      </div>
    </div>
  )
}

function parseRegionStyle(value: string): CSSProperties | undefined {
  const readPercent = (name: string) => new RegExp(`(?:^|;)\\s*${name}:\\s*(\\d+(?:\\.\\d+)?%)`).exec(value)?.[1]
  const left = readPercent('left')
  const top = readPercent('top')
  const width = readPercent('width')
  const height = readPercent('height')
  return left && top && width && height ? { left, top, width, height } : undefined
}

function AssessmentHistory({ assessment }: { assessment: Assessment }) {
  return (
    <article className='py-3 first:pt-0'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-sm font-semibold'>{displayLabel(assessment.review_state_label, assessment.review_state, REVIEW_STATE_LABELS)}</span>
        {assessment.current ? <Badge variant='secondary'>当前版本</Badge> : null}
        {assessment.published ? <Badge variant='outline'>已发布</Badge> : null}
      </div>
      {assessment.dimensions.length === 0 ? (
        <p className='mt-2 text-sm text-muted-foreground'>评价维度未记录。</p>
      ) : (
        <ul className='mt-2 divide-y'>
          {assessment.dimensions.map((dimension) => {
            const unknown = dimension.judgment === 'unknown' || dimension.basis === 'undetermined'
            return (
              <li key={dimension.dimension} className='py-2 first:pt-0'>
                <div className='flex flex-wrap items-baseline gap-x-2 gap-y-1'>
                  <span className='text-sm font-medium'>{dimension.dimension_label || '评价项目未命名'}</span>
                  {unknown ? <Badge variant='outline' className='border-amber-300 text-amber-900'>未知 / 未测</Badge> : null}
                  <span className='text-xs text-muted-foreground'>{dimension.judgment_label} · {dimension.basis_label}</span>
                </div>
                {dimension.rationale ? <p className='mt-1 whitespace-pre-wrap text-sm leading-5'>{dimension.rationale}</p> : null}
                {dimension.unknown_reason ? <p className='mt-1 whitespace-pre-wrap text-sm leading-5 text-amber-900'>未确定原因：{dimension.unknown_reason}</p> : null}
                <div className='mt-2'><SourceEvidence sources={dimension.sources} /></div>
              </li>
            )
          })}
        </ul>
      )}
    </article>
  )
}

export function Attempts({
  remote,
  page,
  onRetry,
  onPageChange,
}: {
  remote: Remote<AttemptResponse>
  page: number
  onRetry: () => void
  onPageChange: (nextPage: number) => void
}) {
  const [selectedAttemptId, setSelectedAttemptId] = useState<string | null>(null)
  const items = remote.status === 'loaded' ? remote.data.items : []

  useEffect(() => {
    setSelectedAttemptId((current) => items.some((attempt) => attempt.attempt_id === current)
      ? current
      : items[0]?.attempt_id || null)
  }, [items])

  if (remote.status === 'loading') return <LoadingState label='正在读取作答记录…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={onRetry} />

  const { total, page_size: pageSize } = remote.data
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  if (items.length === 0) {
    return <EmptyState title='还没有符合条件的记录' detail='尝试调整日期或来源筛选。没有记录时不生成学习表现或掌握结论。' />
  }
  const selectedAttempt = items.find((attempt) => attempt.attempt_id === selectedAttemptId) || items[0]

  return (
    <div className='grid items-start gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(22rem,0.95fr)]'>
      <section aria-labelledby='attempt-list-heading' className='min-w-0 space-y-3'>
        <div className='flex flex-wrap items-baseline justify-between gap-2'>
          <div>
            <h2 id='attempt-list-heading' className='font-semibold'>每次作答分别记录</h2>
            <p className='mt-1 text-xs text-muted-foreground'>选择作答，核对原图与评价。</p>
          </div>
          <Badge variant='outline'>{formatCount(total)} 条记录</Badge>
        </div>
        <div className='max-w-full overflow-x-auto xl:max-h-[70vh] xl:overflow-auto xl:overscroll-contain'>
          <Table>
            <TableHeader>
              <TableRow className='hover:bg-transparent'>
                <TableHead>题目与作答</TableHead>
                <TableHead>来源与日期</TableHead>
                <TableHead>这次的评价</TableHead>
                <TableHead className='text-right'>详情</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((attempt) => (
                <AttemptRow key={attempt.attempt_id} attempt={attempt} selected={selectedAttempt.attempt_id === attempt.attempt_id} onSelect={() => setSelectedAttemptId(attempt.attempt_id)} />
              ))}
            </TableBody>
          </Table>
        </div>
        <div className='flex flex-wrap items-center justify-between gap-3 border-t pt-3'>
          <p className='text-sm text-muted-foreground'>第 {page} / {pageCount} 页</p>
          <div className='flex gap-2'>
            <Button type='button' variant='outline' size='sm' disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
              <ChevronLeft className='size-4' aria-hidden='true' />上一页
            </Button>
            <Button type='button' variant='outline' size='sm' disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>
              下一页<ChevronRight className='size-4' aria-hidden='true' />
            </Button>
          </div>
        </div>
      </section>
      <section aria-label='所选作答详情' className='min-w-0 rounded-md border'>
        <AttemptDetails attempt={selectedAttempt} />
      </section>
    </div>
  )
}

function AttemptRow({ attempt, selected, onSelect }: { attempt: Attempt; selected: boolean; onSelect: () => void }) {
  const unknownDate = attempt.actual_date_state !== 'known' || !attempt.actual_date
  const sourceLabel = SOURCE_LABELS[attempt.source_kind] || attempt.source_kind_label || '来源未核实'
  const ratingLabel = attempt.assessments.length === 0
    ? '尚无评价'
    : attempt.independent_success
      ? '有独立成功证据'
      : '这次未确认独立成功'

  return (
    <TableRow aria-selected={selected} className={selected ? 'bg-muted/40' : undefined}>
      <TableCell className='max-w-md py-1'>
        <p className='whitespace-pre-wrap break-words font-medium'>{attempt.question_text || '题干未记录'}</p>
        <p className='mt-1 text-xs text-muted-foreground'>{displayLabel(attempt.attempt_kind_label, attempt.attempt_kind, ATTEMPT_KIND_LABELS)}</p>
      </TableCell>
      <TableCell className='py-1'>
        <span>{sourceLabel}</span>
        <span className='mt-1 block text-xs text-muted-foreground'>{unknownDate ? '日期未知' : attempt.actual_date}</span>
      </TableCell>
      <TableCell className='py-1'><span className='text-sm'>{ratingLabel}</span></TableCell>
      <TableCell className='py-1 text-right'>
        <div className='flex items-center justify-end gap-2'>
          {selected ? <Badge variant='secondary'>已选中</Badge> : null}
          <Button type='button' variant='ghost' size='sm' aria-pressed={selected} onClick={onSelect}>查看详情</Button>
        </div>
      </TableCell>
    </TableRow>
  )
}

function displayLabel(label: string | undefined, value: string, knownLabels: Record<string, string>) {
  if (label?.trim()) return label
  return knownLabels[value] || '未确定状态'
}
