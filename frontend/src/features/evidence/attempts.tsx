import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Attempt, AttemptResponse, Assessment } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, SOURCE_LABELS, SourceEvidence, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table'

function AttemptDetails({ attempt }: { attempt: Attempt }) {
  const actualDate = attempt.actual_date_state === 'known' && attempt.actual_date
    ? attempt.actual_date
    : '实际作答日期未知'
  return (
    <div className='grid gap-5 p-4 sm:p-5 lg:grid-cols-2'>
      <section className='space-y-3'>
        <h3 className='font-semibold'>作答内容与来源</h3>
        <dl className='grid gap-3 text-sm sm:grid-cols-2'>
          <div><dt className='text-muted-foreground'>题目版本</dt><dd className='mt-1'>{attempt.question_text || '题干未记录'}</dd></div>
          <div><dt className='text-muted-foreground'>实际作答日期</dt><dd className='mt-1'>{actualDate}</dd></div>
          <div><dt className='text-muted-foreground'>独立性</dt><dd className='mt-1'>{attempt.independence_label || attempt.independence || '未记录'}</dd></div>
          <div><dt className='text-muted-foreground'>提示情况</dt><dd className='mt-1'>{attempt.prompt_status_label || attempt.prompt_status || '未知 / 未测'}</dd></div>
          <div><dt className='text-muted-foreground'>笔迹可读性</dt><dd className='mt-1'>{attempt.legibility_label || attempt.legibility || '未知 / 未测'}</dd></div>
          <div><dt className='text-muted-foreground'>记录状态</dt><dd className='mt-1'>{attempt.state_label || attempt.state}</dd></div>
        </dl>
        <div className='rounded-lg bg-muted/40 p-3'>
          <p className='mb-1 text-xs font-medium text-muted-foreground'>作答内容</p>
          <p className='whitespace-pre-wrap text-sm leading-6'>{attempt.answer_text || '作答内容未记录。'}</p>
        </div>
        {attempt.prompts.length ? (
          <div>
            <p className='mb-1 text-xs font-medium text-muted-foreground'>提示记录</p>
            <ul className='list-disc space-y-1 pl-5 text-sm'>{attempt.prompts.map((prompt, index) => <li key={`${index}-${prompt}`}>{prompt}</li>)}</ul>
          </div>
        ) : null}
        <SourceEvidence sources={attempt.sources} />
        <div className='flex flex-wrap gap-x-4 gap-y-2 pt-1 text-sm'>
          <ApiLink href={attempt.attempt_url}>查看这次作答及完整历史</ApiLink>
          <ApiLink href={attempt.question_url}>查看题目</ApiLink>
        </div>
      </section>
      <section className='space-y-3'>
        <div>
          <h3 className='font-semibold'>评价历史</h3>
          <p className='mt-1 text-xs leading-5 text-muted-foreground'>每份评价按后端返回的修订独立展示；未知和未测状态会保留。</p>
        </div>
        {attempt.assessments.length === 0 ? (
          <p className='rounded-lg border border-dashed p-4 text-sm text-muted-foreground'>尚无评价记录，不能据此推断掌握状态。</p>
        ) : (
          <div className='space-y-3'>
            {attempt.assessments.map((assessment) => <AssessmentHistory key={assessment.assessment_revision_id} assessment={assessment} />)}
          </div>
        )}
      </section>
    </div>
  )
}

function AssessmentHistory({ assessment }: { assessment: Assessment }) {
  return (
    <article className='rounded-lg border bg-background p-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-sm font-semibold'>{assessment.review_state_label || assessment.review_state}</span>
        {assessment.current ? <Badge variant='secondary'>当前</Badge> : null}
        {assessment.published ? <Badge variant='outline'>已发布</Badge> : null}
      </div>
      {assessment.dimensions.length === 0 ? (
        <p className='mt-3 text-sm text-muted-foreground'>评价维度未记录。</p>
      ) : (
        <ul className='mt-3 divide-y'>
          {assessment.dimensions.map((dimension) => {
            const unknown = dimension.judgment === 'unknown' || dimension.basis === 'undetermined'
            return (
              <li key={dimension.dimension} className='py-3 first:pt-0 last:pb-0'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='text-sm font-medium'>{dimension.dimension_label}</span>
                  {unknown ? <Badge variant='outline' className='border-amber-300 text-amber-900'>未知 / 未测</Badge> : null}
                  <span className='text-xs text-muted-foreground'>{dimension.judgment_label} · {dimension.basis_label}</span>
                </div>
                {dimension.rationale ? <p className='mt-1 text-sm leading-5'>{dimension.rationale}</p> : null}
                {dimension.unknown_reason ? <p className='mt-1 text-sm leading-5 text-amber-900'>未确定原因：{dimension.unknown_reason}</p> : null}
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
  if (remote.status === 'loading') return <LoadingState label='正在读取作答记录…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={onRetry} />

  const { items, total, page_size: pageSize } = remote.data
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  if (items.length === 0) {
    return <EmptyState title='还没有符合条件的记录' detail='尝试调整日期或来源筛选。没有记录时不生成学习表现或掌握结论。' />
  }

  return (
    <Card className='overflow-hidden py-0'>
      <div className='flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4'>
        <div>
          <h2 className='font-semibold'>作答记录</h2>
          <p className='mt-1 text-xs text-muted-foreground'>每次真实作答单独保留；展开记录可查看来源和评价版本。</p>
        </div>
        <Badge variant='outline'>{formatCount(total)} 条记录</Badge>
      </div>
      <Table>
        <TableHeader>
          <TableRow className='hover:bg-transparent'>
            <TableHead>作答与题目</TableHead>
            <TableHead>来源</TableHead>
            <TableHead>实际日期</TableHead>
            <TableHead>评价</TableHead>
            <TableHead className='text-right'>详情</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((attempt) => (
            <AttemptRow key={attempt.attempt_id} attempt={attempt} />
          ))}
        </TableBody>
      </Table>
      <div className='flex flex-wrap items-center justify-between gap-3 border-t px-5 py-4'>
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
    </Card>
  )
}

function AttemptRow({ attempt }: { attempt: Attempt }) {
  const [expanded, setExpanded] = useState(false)
  const unknownDate = attempt.actual_date_state !== 'known' || !attempt.actual_date
  const sourceLabel = SOURCE_LABELS[attempt.source_kind] || attempt.source_kind_label || '来源未知'
  const ratingLabel = attempt.assessments.length === 0
    ? '未评价'
    : attempt.independent_success
      ? '有独立成功证据'
      : '暂无独立成功证据'

  return (
    <>
      <TableRow>
        <TableCell className='max-w-md py-4'>
          <p className='line-clamp-2 font-medium'>{attempt.question_text || '题干未记录'}</p>
          <p className='mt-1 text-xs text-muted-foreground'>{attempt.attempt_kind_label || attempt.attempt_kind}</p>
        </TableCell>
        <TableCell><Badge variant={attempt.source_kind === 'unknown' ? 'outline' : 'secondary'}>{sourceLabel}</Badge></TableCell>
        <TableCell>
          <span className={unknownDate ? 'text-amber-800' : 'text-foreground'}>{unknownDate ? '日期未知' : attempt.actual_date}</span>
        </TableCell>
        <TableCell><span className='text-sm'>{ratingLabel}</span></TableCell>
        <TableCell className='text-right'>
          <Button type='button' variant='ghost' size='sm' aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
            {expanded ? '收起' : '查看详情'}
          </Button>
        </TableCell>
      </TableRow>
      {expanded ? (
        <TableRow className='bg-muted/20 hover:bg-muted/20'>
          <TableCell colSpan={5} className='p-0'>
            <AttemptDetails attempt={attempt} />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}
