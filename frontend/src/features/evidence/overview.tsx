import { SOURCE_KINDS, type Attempt, type Filters, type OverviewResponse } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, sameOriginHref, SOURCE_LABELS, SourceEvidence, type Remote } from '../../components/shared'
import { Button } from '../../components/ui/button'

type InsufficientFinding = OverviewResponse['findings']['insufficient_evidence'][number]
type CorrectFinding = OverviewResponse['findings']['observed_correct_methods'][number]

export function Overview({
  remote,
  learnerName,
  filters,
  onClearFilters,
  onRetry,
}: {
  remote: Remote<OverviewResponse>
  learnerName?: string
  filters?: Filters
  onClearFilters?: () => void
  onRetry: () => void
}) {
  if (remote.status === 'loading') return <LoadingState label='正在整理学习证据…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={onRetry} />

  const { metrics, findings, links } = remote.data
  const selectedFilters = filters || {
    dateFrom: remote.data.scope.date_from || '',
    dateTo: remote.data.scope.date_to || '',
    sourceKind: remote.data.scope.source_kind || '',
  }
  const hasFilters = hasActiveFilters(selectedFilters)
  const noHistory = remote.data.history_attempt_count !== undefined
    ? remote.data.history_attempt_count === 0
    : metrics.attempt_count === 0 && !hasFilters
  const recentAttempts = (remote.data.recent_attempts || []).slice(0, 5)
  const attemptsById = new Map([...(remote.data.finding_attempts || []), ...recentAttempts]
    .map((attempt) => [attempt.attempt_id, attempt]))
  const recordAttemptUrl = links.record_attempt_url || appendAttemptNewPath(links.profile_url)

  return (
    <div className='space-y-[var(--space-6)]'>
      <section aria-labelledby='evidence-summary-heading' className='space-y-3'>
        <div>
          <h3 id='evidence-summary-heading' className='text-[length:var(--type-section)] font-semibold'>当前范围摘要</h3>
          <p className='mt-1 text-sm text-muted-foreground'>
            {[learnerName || '当前学习者', formatDateScope(selectedFilters), selectedFilters.sourceKind ? SOURCE_LABELS[selectedFilters.sourceKind] : '全部来源'].join(' · ')}
          </p>
        </div>
        <dl className='grid max-w-4xl grid-cols-2 gap-x-5 gap-y-3 border-y py-3 sm:grid-cols-4'>
          <SummaryCount label='作答记录' value={metrics.attempt_count} unit='次' />
          <SummaryCount label='涉及题目' value={metrics.question_count} unit='道' />
          <SummaryCount label='已核对独立成功' value={metrics.independent_success_count} unit='次' />
          <SummaryCount label='实际日期未知（来源范围）' value={metrics.unknown_date_count} unit='次' />
        </dl>
        <details><summary className='cursor-pointer text-sm text-muted-foreground'>计数范围与证据规则</summary><p className='max-w-4xl text-xs leading-5 text-muted-foreground'>
          日期筛选只匹配已知的实际作答日期；未知日期计数只应用来源筛选、不应用日期上下限，且不会用录入时间代替。独立成功仅计入有效作答中经核对的独立来源、无提示、日期和字迹可核，并有已接受评价及来源证据支持答案与过程的记录；这不等于长期掌握。
        </p></details>
      </section>

      <details className='space-y-3'><summary className='cursor-pointer text-sm font-medium'>作答来源分布</summary><section aria-labelledby='evidence-sources-heading' className='space-y-3'>
        <div>
          <h3 id='evidence-sources-heading' className='text-[length:var(--type-section)] font-semibold'>作答来源</h3>
          <p className='mt-1 text-sm text-muted-foreground'>以下均为当前学习者与筛选范围内的作答次数。</p>
        </div>
        <ul className='grid max-w-4xl gap-x-6 gap-y-2 sm:grid-cols-2 xl:grid-cols-3'>
          {SOURCE_KINDS.map((kind) => (
            <li key={kind} className='flex items-center justify-between gap-3 border-b py-2 text-sm'>
              <span className='font-medium'>{SOURCE_LABELS[kind]}</span>
              <span className='tabular-nums text-muted-foreground'>
                {metrics.source_counts[kind] === undefined ? '未提供' : `${formatCount(metrics.source_counts[kind])} 次`}
              </span>
            </li>
          ))}
        </ul>
      </section></details>

      <section aria-labelledby='evidence-links-heading' className='flex flex-wrap items-center gap-x-5 gap-y-2 border-y py-3 text-sm'>
        <h3 id='evidence-links-heading' className='font-semibold'>继续查看</h3>
        <ApiLink href={links.profile_url}>学习档案</ApiLink>
        <ApiLink href={links.report_url}>证据报告</ApiLink>
        <ApiLink href={links.schedule_url}>复习计划</ApiLink>
      </section>

      {metrics.attempt_count === 0 ? (
        <section aria-label={noHistory ? '首次作答引导' : '筛选结果'} className='space-y-3'>
          {noHistory ? (
            <EmptyState title='还没有作答记录' detail='首次记录真实作答后，这里会显示可回看的证据。未记录的部分保持未知。' />
          ) : (
            <EmptyState title='当前筛选范围没有作答记录' detail='已有历史记录，但没有记录符合当前日期或来源条件。清除筛选后可查看完整历史。' />
          )}
          <div className='flex flex-wrap justify-center gap-3'>
            {hasFilters && onClearFilters ? (
              <Button type='button' variant='outline' onClick={onClearFilters}>查看全部作答记录</Button>
            ) : null}
            {noHistory ? <ApiLink href={recordAttemptUrl}>记录首次作答</ApiLink> : null}
          </div>
        </section>
      ) : (
        <div className='space-y-8'>
          {remote.data.recent_attempts !== undefined ? (
            <section aria-labelledby='evidence-recent-heading' className='space-y-3'>
              <div>
                <h3 id='evidence-recent-heading' className='text-[length:var(--type-section)] font-semibold'>近期作答记录</h3>
                <p className='mt-1 text-sm text-muted-foreground'>按实际作答日期由近到远排序，日期未知的记录列在最后。</p>
              </div>
              {recentAttempts.length === 0 ? (
                <p className='text-sm text-muted-foreground'>当前范围没有可展示的近期作答记录。</p>
              ) : (
                <ol className='max-w-5xl divide-y'>
                  {recentAttempts.map((attempt) => <RecentAttempt key={attempt.attempt_id} attempt={attempt} />)}
                </ol>
              )}
            </section>
          ) : null}

          <details><summary className='cursor-pointer font-medium'>家长关注 · 过程观察与待核实证据</summary>
          <section aria-labelledby='evidence-correct-heading' className='space-y-3'>
            <div>
              <h3 id='evidence-correct-heading' className='text-[length:var(--type-section)] font-semibold'>已观察到的正确方法与过程</h3>
              <p className='mt-1 text-sm text-muted-foreground'>同一次作答的观察归在一起，来源和评价修订可展开查看。</p>
            </div>
            {findings.observed_correct_methods.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有已观察到的正确方法记录。</p>
            ) : (
              <ul className='max-w-5xl divide-y'>
                {groupByAttempt(findings.observed_correct_methods).map((group) => (
                  <CorrectEvent key={group.attemptId} group={group} attempt={attemptsById.get(group.attemptId)} />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby='evidence-unconfirmed-heading' className='space-y-3'>
            <div>
              <h3 id='evidence-unconfirmed-heading' className='text-[length:var(--type-section)] font-semibold'>尚未充分核实</h3>
              <p className='mt-1 text-sm text-muted-foreground'>按每次作答分组；原有原因、评价修订和来源会保留在展开内容中。</p>
            </div>
            {findings.insufficient_evidence.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有待核实项目。</p>
            ) : (
              <ul className='max-w-5xl divide-y'>
                {groupByAttempt(findings.insufficient_evidence).map((group) => (
                  <InsufficientEvent key={group.attemptId} group={group} attempt={attemptsById.get(group.attemptId)} />
                ))}
              </ul>
            )}
          </section>

          </details>
          <details><summary className='cursor-pointer font-medium'>重复错误与日期间隔</summary><section aria-labelledby='evidence-repeated-heading' className='space-y-3'>
            <div>
              <h3 id='evidence-repeated-heading' className='text-[length:var(--type-section)] font-semibold'>重复错误观察</h3>
              <p className='mt-1 text-sm text-muted-foreground'>仅列出有多次可追溯观察的错误组；没有足够观察不代表表现良好。</p>
            </div>
            {findings.repeated_errors.length === 0 ? (
              <p className='text-sm text-muted-foreground'>当前筛选范围内没有达到重复观察条件的错误组。</p>
            ) : (
              <ul className='max-w-5xl divide-y'>
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
              <h3 id='evidence-intervals-heading' className='text-[length:var(--type-section)] font-semibold'>已知作答日期间隔</h3>
              <p className='mt-1 text-sm text-muted-foreground'>只使用确认的实际作答日期，不按记录创建时间推算。</p>
            </div>
            {findings.known_actual_date_intervals.length === 0 ? (
              <p className='text-sm text-muted-foreground'>目前没有可展示的已知日期间隔。</p>
            ) : (
              <ul className='max-w-5xl divide-y'>
                {findings.known_actual_date_intervals.map((interval, index) => (
                  <li key={`${interval.from_attempt_id}-${interval.to_attempt_id}-${index}`} className='flex flex-wrap items-center justify-between gap-2 py-2 text-sm'>
                    <span>{interval.from_actual_date} 至 {interval.to_actual_date}</span>
                    <span className='text-muted-foreground'>{formatCount(interval.days)} 天</span>
                  </li>
                ))}
              </ul>
            )}
          </section></details>
        </div>
      )}
    </div>
  )
}

function SummaryCount({ label, value, unit }: { label: string; value: number; unit: string }) {
  return (
    <div>
      <dt className='text-[length:var(--type-small)] text-muted-foreground'>{label}</dt>
      <dd className='mt-1 flex items-baseline gap-1 font-semibold tabular-nums' style={{ fontSize: 'var(--type-metric, 1.75rem)' }}>
        {formatCount(value)}<span className='text-xs font-normal text-muted-foreground'>{unit}</span>
      </dd>
    </div>
  )
}

function RecentAttempt({ attempt }: { attempt: Attempt }) {
  const date = actualDateLabel(attempt)
  const kind = attemptKindLabel(attempt)
  const source = attempt.source_kind_label || SOURCE_LABELS[attempt.source_kind] || '来源未知'
  return (
    <li className='flex flex-col gap-1 py-3 first:pt-0 sm:flex-row sm:items-start sm:justify-between sm:gap-4'>
      <div className='min-w-0'>
        <p className='text-sm font-medium'>{attempt.question_text || '题干未记录'}</p>
        <p className='mt-1 text-xs text-muted-foreground'>{kind} · {source} · {date}{attempt.ordering_basis_label ? ` · ${attempt.ordering_basis_label}` : ''}</p>
      </div>
      <ApiLink href={attempt.attempt_url}>查看本次作答</ApiLink>
    </li>
  )
}

function CorrectEvent({ group, attempt }: { group: EventGroup<CorrectFinding>; attempt?: Attempt }) {
  const revisions = groupByRevision(group.findings)
  const dimensions = [...new Set(group.findings.map((finding) => finding.dimension_label))]
  return (
    <li className='py-3 first:pt-0'>
      <EventHeading attempt={attempt} />
      <p className='mt-2 text-sm'>{dimensions.join('、') || '已观察到正确过程'}</p>
      <details className='mt-2 rounded-md border px-3 py-2'>
        <summary className='cursor-pointer text-sm font-medium'>查看 {formatCount(group.findings.length)} 项观察、评价修订与原图来源</summary>
        <div className='mt-3 divide-y'>
          {revisions.map((revision, index) => (
            <section key={revision.key} className='py-3 first:pt-0'>
              <h4 className='text-xs font-medium text-muted-foreground'>{revision.assessment_revision_id ? '已记录评价修订' : `评价修订未记录（独立项目 ${index + 1}）`}</h4>
              <ul className='mt-2 divide-y'>
                {revision.findings.map((finding, itemIndex) => (
                  <li key={`${finding.dimension}-${itemIndex}`} className='py-2'>
                    <p className='text-sm font-medium'>{finding.dimension_label}</p>
                    <div className='mt-2'><SourceEvidence sources={finding.sources} /></div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </details>
    </li>
  )
}

function InsufficientEvent({ group, attempt }: { group: EventGroup<InsufficientFinding>; attempt?: Attempt }) {
  const revisions = groupByRevision(group.findings)
  return (
    <li className='py-3 first:pt-0'>
      <EventHeading attempt={attempt} />
      <p className='mt-2 text-sm'>待核实项目 {formatCount(group.findings.length)} 项；展开可查看每条原因与依据。</p>
      <details className='mt-2 rounded-md border px-3 py-2'>
        <summary className='cursor-pointer text-sm font-medium'>查看 {formatCount(group.findings.length)} 项维度、评价修订和原图来源</summary>
        <div className='mt-3 divide-y'>
          {revisions.map((revision, index) => (
            <section key={revision.key} className='py-3 first:pt-0'>
              <h4 className='text-xs font-medium text-muted-foreground'>{revision.assessment_revision_id ? '已记录评价修订' : `评价修订未记录（独立项目 ${index + 1}）`}</h4>
              <ul className='mt-2 divide-y'>
                {revision.findings.map((finding, itemIndex) => (
                  <li key={`${finding.dimension || 'overall'}-${itemIndex}`} className='py-2'>
                    <p className='text-sm font-medium'>{finding.dimension_label || '整体证据'}</p>
                    <p className='mt-1 text-xs text-muted-foreground'>{finding.judgment_label} · {finding.basis_label}</p>
                    <p className='mt-2 whitespace-pre-wrap text-sm leading-6'>{finding.reason || '依据未记录。'}</p>
                    <div className='mt-2'><SourceEvidence sources={finding.sources} /></div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </details>
    </li>
  )
}

function EventHeading({ attempt }: { attempt?: Attempt }) {
  if (!attempt) {
    return <h4 className='text-sm font-semibold'>作答事件 · 日期和题目未随当前摘要提供</h4>
  }
  return (
    <div className='flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1'>
      <div className='min-w-0'>
        <h4 className='text-sm font-semibold'>{actualDateLabel(attempt)} · {attemptKindLabel(attempt)}</h4>
        <p className='mt-1 whitespace-pre-wrap text-sm'>{attempt.question_text || '题干未记录'}</p>
      </div>
      <ApiLink href={attempt.attempt_url}>查看本次作答</ApiLink>
    </div>
  )
}

type EventGroup<T extends { attempt_id: string }> = {
  attemptId: string
  findings: T[]
}

function groupByAttempt<T extends { attempt_id: string }>(findings: T[]): EventGroup<T>[] {
  const grouped = new Map<string, T[]>()
  findings.forEach((finding) => {
    const current = grouped.get(finding.attempt_id) || []
    current.push(finding)
    grouped.set(finding.attempt_id, current)
  })
  return [...grouped].map(([attemptId, items]) => ({ attemptId, findings: items }))
}

function groupByRevision<T extends { assessment_revision_id: string | null }>(findings: T[]) {
  const grouped = new Map<string, { assessment_revision_id: string | null; findings: T[] }>()
  findings.forEach((finding, index) => {
    // A missing revision id cannot prove that two rows came from one evaluation.
    const key = finding.assessment_revision_id || `unknown-${index}`
    const current = grouped.get(key) || { assessment_revision_id: finding.assessment_revision_id, findings: [] }
    current.findings.push(finding)
    grouped.set(key, current)
  })
  return [...grouped].map(([key, revision]) => ({ key, ...revision }))
}

function actualDateLabel(attempt: Attempt) {
  return attempt.actual_date_state === 'known' && attempt.actual_date
    ? attempt.actual_date
    : '实际作答日期未知'
}

function attemptKindLabel(attempt: Attempt) {
  if (attempt.attempt_kind_label) return attempt.attempt_kind_label
  const labels: Record<string, string> = { first: '首次作答', correction: '订正', retry: '重做', retest: '复测' }
  return labels[attempt.attempt_kind] || '作答类型未记录'
}

function hasActiveFilters(filters: Filters) {
  return Boolean(filters.dateFrom || filters.dateTo || filters.sourceKind)
}

function formatDateScope(filters: Filters) {
  if (filters.dateFrom && filters.dateTo) return `实际日期 ${filters.dateFrom} 至 ${filters.dateTo}`
  if (filters.dateFrom) return `实际日期自 ${filters.dateFrom} 起`
  if (filters.dateTo) return `实际日期截至 ${filters.dateTo}`
  return '全部实际日期'
}

function appendAttemptNewPath(profileUrl: string | null) {
  const safeProfile = sameOriginHref(profileUrl)
  if (!safeProfile) return null
  const splitAt = safeProfile.search(/[?#]/)
  const path = splitAt < 0 ? safeProfile : safeProfile.slice(0, splitAt)
  const suffix = splitAt < 0 ? '' : safeProfile.slice(splitAt)
  return `${path.replace(/\/+$/, '')}/attempt/new/${suffix}`
}
