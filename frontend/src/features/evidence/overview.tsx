import { ArrowDownRight, BookOpenCheck, CalendarDays, CircleHelp, ClipboardList, Layers3, ShieldCheck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { SOURCE_KINDS, type OverviewResponse } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, SOURCE_LABELS, SourceEvidence, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone,
}: {
  label: string
  value: string | number
  detail: string
  icon: LucideIcon
  tone: string
}) {
  return (
    <Card className='gap-0 py-0 shadow-sm'>
      <CardContent className='flex items-start justify-between gap-3 px-5 py-5'>
        <div className='min-w-0'>
          <p className='text-sm font-medium text-muted-foreground'>{label}</p>
          <p className='mt-2 text-3xl font-semibold tracking-tight'>{value}</p>
          <p className='mt-1 text-xs text-muted-foreground'>{detail}</p>
        </div>
        <span className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${tone}`}>
          <Icon className='size-5' aria-hidden='true' />
        </span>
      </CardContent>
    </Card>
  )
}

export function Overview({
  remote,
  onRetry,
}: {
  remote: Remote<OverviewResponse>
  onRetry: () => void
}) {
  if (remote.status === 'loading') return <LoadingState label='正在整理学习证据…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={onRetry} />

  const { metrics, findings, links } = remote.data
  return (
    <div className='space-y-6'>
      <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
        <MetricCard label='作答记录' value={formatCount(metrics.attempt_count)} detail='按真实作答事件计次' icon={ClipboardList} tone='bg-sky-100 text-sky-800' />
        <MetricCard label='涉及题目' value={formatCount(metrics.question_count)} detail='同一道题只计一次' icon={BookOpenCheck} tone='bg-indigo-100 text-indigo-800' />
        <MetricCard label='独立成功证据' value={formatCount(metrics.independent_success_count)} detail='沿用现有成功判定规则' icon={ShieldCheck} tone='bg-emerald-100 text-emerald-800' />
        <MetricCard label='日期未记录' value={formatCount(metrics.unknown_date_count)} detail='不使用录入时间替代实际日期' icon={CalendarDays} tone='bg-amber-100 text-amber-900' />
      </div>

      <div className='grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(18rem,1fr)]'>
        <Card>
          <CardHeader className='border-b pb-4'>
            <CardTitle className='text-base'>作答来源</CardTitle>
            <CardDescription>按当前筛选条件汇总已记录的作答</CardDescription>
          </CardHeader>
          <CardContent className='grid gap-3 pt-5 sm:grid-cols-2'>
            {SOURCE_KINDS.map((kind) => (
              <div key={kind} className='flex items-center justify-between gap-3 rounded-lg border bg-muted/20 px-4 py-3'>
                <span className='flex min-w-0 items-center gap-2 text-sm font-medium'>
                  <span className={`size-2 rounded-full ${kind === 'unknown' ? 'bg-amber-500' : 'bg-primary/70'}`} />
                  {SOURCE_LABELS[kind]}
                </span>
                <span className='text-sm tabular-nums text-muted-foreground'>
                  {metrics.source_counts[kind] === undefined ? '未提供' : formatCount(metrics.source_counts[kind])}
                </span>
              </div>
            ))}
            <p className='sm:col-span-2 text-xs leading-5 text-muted-foreground'>
              {metrics.independent_success_rate === null
                ? '暂不显示独立成功比例；目前没有经过确认的统计定义。'
                : `独立成功比例：${String(metrics.independent_success_rate)}。`}只显示已有记录提供的结果，不进行推算。
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='border-b pb-4'>
            <CardTitle className='text-base'>学习证据入口</CardTitle>
            <CardDescription>打开现有档案、证据报告或复习计划</CardDescription>
          </CardHeader>
          <CardContent className='flex flex-col items-start gap-3 pt-5 text-sm'>
            <ApiLink href={links.profile_url}>学习档案</ApiLink>
            <ApiLink href={links.report_url}>证据报告</ApiLink>
            <ApiLink href={links.schedule_url}>复习计划</ApiLink>
          </CardContent>
        </Card>
      </div>

      {metrics.attempt_count === 0 ? (
        <EmptyState title='还没有作答记录' detail='这里会显示真实的作答证据。没有记录时不会生成学习表现或掌握结论。' />
      ) : null}

      {metrics.attempt_count > 0 ? (
        <>
      <div className='grid gap-5 xl:grid-cols-2'>
        <Card>
          <CardHeader className='border-b pb-4'>
            <CardTitle className='flex items-center gap-2 text-base'>
              <BookOpenCheck className='size-4 text-emerald-700' aria-hidden='true' />
              已观察到的正确方法与过程
            </CardTitle>
            <CardDescription>来自已接受并发布评价的可追溯方法观察</CardDescription>
          </CardHeader>
          <CardContent className='pt-5'>
            {findings.observed_correct_methods.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有已观察到的正确方法记录。</p>
            ) : (
              <ul className='space-y-4'>
                {findings.observed_correct_methods.slice(0, 6).map((finding, index) => (
                  <li key={`${finding.assessment_revision_id}-${index}`} className='border-b pb-4 last:border-0 last:pb-0'>
                    <p className='text-sm font-medium'>{finding.dimension_label}</p>
                    <div className='mt-2'><SourceEvidence sources={finding.sources} /></div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='border-b pb-4'>
            <CardTitle className='flex items-center gap-2 text-base'>
              <CircleHelp className='size-4 text-amber-700' aria-hidden='true' />
              尚未充分核实
            </CardTitle>
            <CardDescription>未记录、未知或缺少直接证据的项目保留为待核实</CardDescription>
          </CardHeader>
          <CardContent className='pt-5'>
            {findings.insufficient_evidence.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有待核实项目。</p>
            ) : (
              <ul className='space-y-4'>
                {findings.insufficient_evidence.slice(0, 6).map((finding, index) => (
                  <li key={`${finding.attempt_id}-${finding.assessment_revision_id ?? 'unknown'}-${index}`} className='border-b pb-4 last:border-0 last:pb-0'>
                    <div className='flex flex-wrap items-center gap-2'>
                      <Badge variant='outline'>{finding.dimension_label || '整体证据'}</Badge>
                      <span className='text-xs text-muted-foreground'>{finding.judgment_label} · {finding.basis_label}</span>
                    </div>
                    <p className='mt-2 text-sm leading-6'>{finding.reason || '依据未记录。'}</p>
                    <div className='mt-2'><SourceEvidence sources={finding.sources} /></div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <div className='grid gap-5 xl:grid-cols-2'>
        <Card>
          <CardHeader className='border-b pb-4'>
            <CardTitle className='flex items-center gap-2 text-base'>
              <Layers3 className='size-4 text-rose-700' aria-hidden='true' />
              重复错误观察
            </CardTitle>
            <CardDescription>仅列出有多次可追溯观察的错误组</CardDescription>
          </CardHeader>
          <CardContent className='pt-5'>
            {findings.repeated_errors.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有重复错误组。</p>
            ) : (
              <ul className='space-y-3'>
                {findings.repeated_errors.slice(0, 6).map((finding, index) => (
                  <li key={`${finding.dimension}-${index}`} className='flex items-center justify-between gap-3 rounded-lg border px-4 py-3'>
                    <span className='text-sm font-medium'>{finding.dimension_label}</span>
                    <Badge variant='outline'>{formatCount(finding.occurrence_count)} 次观察</Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='border-b pb-4'>
            <CardTitle className='flex items-center gap-2 text-base'>
              <CalendarDays className='size-4 text-sky-700' aria-hidden='true' />
              已知作答日期间隔
            </CardTitle>
            <CardDescription>只使用确认的实际作答日期</CardDescription>
          </CardHeader>
          <CardContent className='pt-5'>
            {findings.known_actual_date_intervals.length === 0 ? (
              <p className='text-sm text-muted-foreground'>目前没有可展示的已知日期间隔。</p>
            ) : (
              <ul className='space-y-3'>
                {findings.known_actual_date_intervals.slice(0, 6).map((interval, index) => (
                  <li key={`${interval.from_actual_date}-${interval.to_actual_date}-${index}`} className='flex flex-wrap items-center justify-between gap-2 rounded-lg border px-4 py-3 text-sm'>
                    <span>{interval.from_actual_date} <ArrowDownRight className='inline size-3.5' aria-hidden='true' /> {interval.to_actual_date}</span>
                    <span className='text-muted-foreground'>{formatCount(interval.days)} 天</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
        </>
      ) : null}
    </div>
  )
}
