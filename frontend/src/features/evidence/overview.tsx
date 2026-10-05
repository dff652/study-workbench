import { SOURCE_KINDS, type OverviewResponse } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, SOURCE_LABELS, SourceEvidence, type Remote } from '../../components/shared'

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
    <div className='space-y-5'>
      <section aria-labelledby='evidence-summary-heading' className='space-y-3'>
        <h3 id='evidence-summary-heading' className='font-semibold'>当前筛选结果</h3>
        <dl className='grid grid-cols-2 gap-x-5 gap-y-3 border-y py-3 sm:grid-cols-4'>
          <div>
            <dt className='text-xs text-muted-foreground'>作答记录</dt>
            <dd className='mt-1 text-xl font-semibold tabular-nums'>{formatCount(metrics.attempt_count)}</dd>
          </div>
          <div>
            <dt className='text-xs text-muted-foreground'>涉及题目</dt>
            <dd className='mt-1 text-xl font-semibold tabular-nums'>{formatCount(metrics.question_count)}</dd>
          </div>
          <div>
            <dt className='text-xs text-muted-foreground'>已核对的独立成功</dt>
            <dd className='mt-1 text-xl font-semibold tabular-nums'>{formatCount(metrics.independent_success_count)}</dd>
          </div>
          <div>
            <dt className='text-xs text-muted-foreground'>实际日期未知</dt>
            <dd className='mt-1 text-xl font-semibold tabular-nums'>{formatCount(metrics.unknown_date_count)}</dd>
          </div>
        </dl>
        <p className='text-sm leading-6 text-muted-foreground'>
          {metrics.independent_success_rate === null
            ? '目前只展示已经核对的记录数量。'
            : `独立成功比例：${String(metrics.independent_success_rate)}。`}没有记录的部分仍保留未知。
        </p>
      </section>

      <section aria-labelledby='evidence-sources-heading' className='space-y-3'>
        <div>
          <h3 id='evidence-sources-heading' className='font-semibold'>作答来源</h3>
          <p className='mt-1 text-sm text-muted-foreground'>按当前筛选条件汇总已记录的作答。</p>
        </div>
        <ul className='grid gap-x-6 gap-y-2 sm:grid-cols-2 xl:grid-cols-3'>
          {SOURCE_KINDS.map((kind) => (
            <li key={kind} className='flex items-center justify-between gap-3 border-b py-2 text-sm'>
              <span className='font-medium'>{SOURCE_LABELS[kind]}</span>
              <span className='tabular-nums text-muted-foreground'>
                {metrics.source_counts[kind] === undefined ? '未提供' : formatCount(metrics.source_counts[kind])}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby='evidence-links-heading' className='flex flex-wrap items-center gap-x-5 gap-y-2 border-y py-3 text-sm'>
        <h3 id='evidence-links-heading' className='font-semibold'>继续查看</h3>
        <ApiLink href={links.profile_url}>学习档案</ApiLink>
        <ApiLink href={links.report_url}>证据报告</ApiLink>
        <ApiLink href={links.schedule_url}>复习计划</ApiLink>
      </section>

      {metrics.attempt_count === 0 ? (
        <EmptyState title='还没有作答记录' detail='这里会显示真实的作答证据。没有记录时不会生成学习表现或掌握结论。' />
      ) : (
        <div className='grid gap-x-8 gap-y-5 xl:grid-cols-2'>
          <section aria-labelledby='evidence-correct-heading' className='space-y-3'>
            <div>
              <h3 id='evidence-correct-heading' className='font-semibold'>已观察到的正确方法与过程</h3>
              <p className='mt-1 text-sm text-muted-foreground'>来自已经核对的作答。</p>
            </div>
            {findings.observed_correct_methods.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有已观察到的正确方法记录。</p>
            ) : (
              <ul className='divide-y'>
                {findings.observed_correct_methods.map((finding, index) => (
                  <li key={`${finding.assessment_revision_id}-${index}`} className='py-3 first:pt-0'>
                    <p className='text-sm font-medium'>{finding.dimension_label}</p>
                    <div className='mt-2'><SourceEvidence sources={finding.sources} /></div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby='evidence-unconfirmed-heading' className='space-y-3'>
            <div>
              <h3 id='evidence-unconfirmed-heading' className='font-semibold'>尚未充分核实</h3>
              <p className='mt-1 text-sm text-muted-foreground'>未记录、未知或缺少直接证据的项目保留为待核实。</p>
            </div>
            {findings.insufficient_evidence.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有待核实项目。</p>
            ) : (
              <ul className='divide-y'>
                {findings.insufficient_evidence.map((finding, index) => (
                  <li key={`${finding.attempt_id}-${finding.assessment_revision_id ?? 'unknown'}-${index}`} className='py-3 first:pt-0'>
                    <p className='text-sm font-medium'>{finding.dimension_label || '整体证据'}</p>
                    <p className='mt-1 text-xs text-muted-foreground'>{finding.judgment_label} · {finding.basis_label}</p>
                    <p className='mt-2 text-sm leading-6'>{finding.reason || '依据未记录。'}</p>
                    <div className='mt-2'><SourceEvidence sources={finding.sources} /></div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby='evidence-repeated-heading' className='space-y-3'>
            <div>
              <h3 id='evidence-repeated-heading' className='font-semibold'>重复错误观察</h3>
              <p className='mt-1 text-sm text-muted-foreground'>仅列出有多次可追溯观察的错误组。</p>
            </div>
            {findings.repeated_errors.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有重复错误组。</p>
            ) : (
              <ul className='divide-y'>
                {findings.repeated_errors.map((finding, index) => (
                  <li key={`${finding.question_id}-${finding.dimension}-${index}`} className='flex items-center justify-between gap-3 py-2 text-sm'>
                    <span className='font-medium'>{finding.dimension_label}</span>
                    <span className='text-muted-foreground'>{formatCount(finding.occurrence_count)} 次观察</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby='evidence-intervals-heading' className='space-y-3'>
            <div>
              <h3 id='evidence-intervals-heading' className='font-semibold'>已知作答日期间隔</h3>
              <p className='mt-1 text-sm text-muted-foreground'>只使用确认的实际作答日期。</p>
            </div>
            {findings.known_actual_date_intervals.length === 0 ? (
              <p className='text-sm text-muted-foreground'>目前没有可展示的已知日期间隔。</p>
            ) : (
              <ul className='divide-y'>
                {findings.known_actual_date_intervals.map((interval, index) => (
                  <li key={`${interval.from_actual_date}-${interval.to_actual_date}-${index}`} className='flex flex-wrap items-center justify-between gap-2 py-2 text-sm'>
                    <span>{interval.from_actual_date} 至 {interval.to_actual_date}</span>
                    <span className='text-muted-foreground'>{formatCount(interval.days)} 天</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
