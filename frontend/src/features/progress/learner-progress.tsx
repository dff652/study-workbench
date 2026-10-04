import { BookOpenCheck, CircleHelp, ListChecks } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { SOURCE_KINDS, type LearnerProgressResponse } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, SOURCE_LABELS, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'

const KIND_LABELS = {
  knowledge: '知识点',
  method: '方法',
  question_type: '题型',
} as const

export function LearnerProgress({ remote, onRetry }: { remote: Remote<LearnerProgressResponse>; onRetry: () => void }) {
  if (remote.status === 'loading') return <LoadingState label='正在读取学习者的知识、方法和题型进度…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={onRetry} />

  const { groups, scope } = remote.data
  return (
    <section className='space-y-4' aria-labelledby='learner-progress-title'>
      <div>
        <h2 id='learner-progress-title' className='text-lg font-semibold'>知识、方法与题型进度</h2>
        <p className='mt-1 text-sm text-muted-foreground'>截至 {scope.as_of}；按当前已确认关联和真实有效作答汇总，不代表掌握程度。</p>
      </div>
      {groups.length === 0 ? (
        <EmptyState title='还没有已确认的学习关联' detail='确认题目与知识点、方法或题型的关系后，会在这里显示真实计数；没有作答时保留为未测。' icon={BookOpenCheck} />
      ) : (
        <div className='grid gap-4 xl:grid-cols-2'>
          {groups.map((group) => (
            <Card key={`${group.kind}:${group.id}`} className='gap-0 py-0 shadow-sm'>
              <CardHeader className='border-b py-4'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <div>
                    <Badge variant='outline'>{KIND_LABELS[group.kind] || '未确定状态'}</Badge>
                    <CardTitle className='mt-2 text-base'>{group.label || '未命名条目'}</CardTitle>
                  </div>
                  <ApiLink href={group.node_url}>查看关联条目</ApiLink>
                </div>
                <CardDescription>只汇总已确认关联的题目和作答；同一道题只计一次，多份评价不会重复计入作答。旧版本仍可从原记录查看。</CardDescription>
              </CardHeader>
              <CardContent className='space-y-4 px-5 py-4'>
                <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
                  <Count label='关联题目' value={group.question_count} icon={BookOpenCheck} />
                  <Count label='有效作答' value={group.attempt_count} icon={ListChecks} />
                  <Count label='独立成功证据' value={group.independent_success_count} icon={BookOpenCheck} />
                  <Count label='未知或待核实' value={group.unknown_evidence_count} icon={CircleHelp} />
                </div>
                {group.attempt_count === 0 ? <p className='rounded-md bg-muted/40 px-3 py-2 text-sm text-muted-foreground'>尚无作答记录，当前状态为未测。</p> : null}
                <div>
                  <h3 className='mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground'>作答来源计数</h3>
                  <ul className='grid gap-2 sm:grid-cols-2'>
                    {SOURCE_KINDS.map((kind) => (
                      <li key={kind} className='flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm'>
                        <span>{SOURCE_LABELS[kind]}</span>
                        <span className='tabular-nums text-muted-foreground'>{group.source_counts[kind] === undefined ? '未提供' : formatCount(group.source_counts[kind])}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  )
}

function Count({ label, value, icon: Icon }: { label: string; value: number; icon: LucideIcon }) {
  return (
    <div className='rounded-lg bg-muted/35 px-3 py-3'>
      <Icon className='mb-2 size-4 text-primary' aria-hidden='true' />
      <p className='text-lg font-semibold tabular-nums'>{formatCount(value)}</p>
      <p className='text-xs leading-5 text-muted-foreground'>{label}</p>
    </div>
  )
}
