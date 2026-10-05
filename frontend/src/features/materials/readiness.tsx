import { Check, CircleAlert, FileImage, FileText, ListChecks } from 'lucide-react'
import type { MaterialDetailResponse, WorkflowJob } from '../../types'
import { ApiLink } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { workflowStateLabel, localDateTime } from './workflow-labels'

export function MaterialReadiness({
  detail,
  onContinue,
}: {
  detail: MaterialDetailResponse
  onContinue?: () => void
}) {
  const { material, pages, readiness } = detail
  return (
    <div className='space-y-5'>
      <Card>
        <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b pb-4'>
          <div>
            <CardTitle className='flex items-center gap-2 text-base'><FileImage className='size-4 text-primary' aria-hidden='true' />原图资料页</CardTitle>
            <CardDescription className='mt-1'>原图保持原样。仅显示当前资料中的已保存页面。</CardDescription>
          </div>
          <div className='flex flex-wrap gap-3 text-sm'>
            {onContinue && pages.length ? <Button type='button' size='sm' onClick={onContinue}>继续核对题面</Button> : null}
            <ApiLink href={material.prepare_url}>生成五册资料</ApiLink>
            <details><summary className='cursor-pointer text-sm'>更多操作</summary><ApiLink href={material.material_url}>编辑题面与来源（兼容页）</ApiLink></details>
          </div>
        </CardHeader>
        <CardContent className='pt-5'>
          {pages.length === 0 ? (
            <div className='rounded-lg border border-dashed p-5 text-sm text-muted-foreground'>尚未上传原图。选择一张本机图片后可逐张上传，服务端保留原始文件。</div>
          ) : (
            <ul className='grid gap-3 sm:grid-cols-2 xl:grid-cols-3'>
              {pages.map((page) => (
                <li key={page.id} className='rounded-lg border bg-muted/10 p-4'>
                  <img src={page.preview_url} alt={`资料页 ${page.position} 缩略图`} loading='lazy' className='mb-3 h-36 w-full object-contain' />
                  <div className='flex items-center justify-between gap-2'>
                    <span className='font-medium'>资料页 {page.position}</span>
                    <Badge variant='outline'>{page.width} × {page.height}</Badge>
                  </div>
                  <div className='mt-3 flex gap-4 text-sm'>
                    <ApiLink href={page.page_url}>查看页面</ApiLink>
                    <ApiLink href={page.preview_url}>查看原图</ApiLink>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className='border-b pb-4'>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <div>
              <CardTitle className='flex items-center gap-2 text-base'><ListChecks className='size-4 text-primary' aria-hidden='true' />整理完整性检查</CardTitle>
              <CardDescription className='mt-1'>可在原图、题面、关联与任务之间回看，不必按固定顺序操作。此处显示已登记缺项，生成前还会再次检查具体内容。</CardDescription>
            </div>
            <Badge variant={readiness.ready ? 'secondary' : 'outline'}>{readiness.ready ? '可进入输出检查' : '仍有待核对项'}</Badge>
          </div>
        </CardHeader>
        <CardContent className='grid gap-5 pt-5 xl:grid-cols-2'>
          <section>
            <h3 className='mb-2 flex items-center gap-2 text-sm font-semibold'><CircleAlert className='size-4 text-amber-700' aria-hidden='true' />阻塞项</h3>
            {readiness.gaps.length === 0 ? <p className='rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900'>当前没有阻塞项。</p> : (
              <ul className='space-y-2'>
                {readiness.gaps.map((gap, index) => <li key={`${index}-${gap}`} className='rounded-md bg-amber-50 px-3 py-2 text-sm leading-5 text-amber-950'>{gap}<GapActions gap={gap} detail={detail} /></li>)}
              </ul>
            )}
            <h3 className='mb-2 mt-5 flex items-center gap-2 text-sm font-semibold'><FileText className='size-4 text-sky-700' aria-hidden='true' />待补内容与页面覆盖</h3>
            {readiness.content_gaps.length === 0 ? <p className='rounded-md bg-muted/40 px-3 py-2 text-sm text-muted-foreground'>当前没有待补提示。</p> : (
              <ul className='space-y-2'>
                {readiness.content_gaps.map((gap, index) => <li key={`${index}-${gap}`} className='rounded-md bg-sky-50 px-3 py-2 text-sm leading-5 text-sky-950'>{gap}<GapActions gap={gap} detail={detail} /></li>)}
              </ul>
            )}
          </section>
          <section>
            <h3 className='mb-2 flex items-center gap-2 text-sm font-semibold'><Check className='size-4 text-primary' aria-hidden='true' />题目与答案核对清单</h3>
            {readiness.questions.length === 0 ? (
              <p className='rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground'>当前资料尚无可列出的题目。复杂题面与来源编辑继续使用旧版资料页。</p>
            ) : (
              <ul className='max-h-[28rem] space-y-2 overflow-y-auto pr-1'>
                {readiness.questions.map((question, index) => (
                  <li key={`${question.question_id}-${question.revision_id}`} className='rounded-lg border p-3'>
                    <p className='font-medium'>{question.number || `题目 ${index + 1}`}</p>
                    <p className='mt-1 whitespace-pre-wrap text-sm leading-5 text-muted-foreground'>{question.text || '题干未记录'}</p>
                    <div className='mt-2 flex flex-wrap gap-2'>
                      <Badge variant={question.confirmed ? 'secondary' : 'outline'}>{question.confirmed ? '题面已确认' : '题面待确认'}</Badge>
                      <Badge variant={question.answer_ready ? 'secondary' : 'outline'}>{question.answer_ready ? '答案已准备' : '答案待补'}</Badge>
                    </div>
                    <div className='mt-3 flex flex-wrap gap-3 text-sm'><ApiLink href={question.edit_url}>补充题面、来源与答案</ApiLink><ApiLink href={question.answer_url}>核对家长答案与依据</ApiLink><ApiLink href={question.association_url}>补充知识与方法关联</ApiLink></div>
                  </li>
                ))}
              </ul>
            )}
            <p className='mt-3 text-xs leading-5 text-muted-foreground'>上传完成不等于整理完成；未读取页、未知内容和需重拍处由旧版页面继续记录。</p>
          </section>
        </CardContent>
      </Card>
    </div>
  )
}

function GapActions({ gap, detail }: { gap: string; detail: MaterialDetailResponse }) {
  const questions = detail.readiness.questions.filter((question) => gap.startsWith(`${question.number || '未编号题目'}：`))
  const page = detail.pages.find((row) => gap.startsWith(`第 ${row.position} 页：`))
  if (page) return <div className='mt-2'><ApiLink href={page.page_url}>整理此页阅读与分区</ApiLink></div>
  if (questions.length) return <div className='mt-2 flex flex-wrap gap-3'>{questions.map((question) => <ApiLink key={question.question_id} href={gap.includes('答案') ? question.answer_url || question.edit_url : gap.includes('关联') ? question.association_url : question.edit_url}>修复题目 {question.number || '未编号'}：{question.text.slice(0, 30)}</ApiLink>)}</div>
  return <div className='mt-2'><ApiLink href={detail.material.material_url}>打开本资料修复缺项</ApiLink></div>
}

export function MaterialTaskHistory({ jobs, selectedJobId, onSelectJob, busy }: {
  jobs: WorkflowJob[]
  selectedJobId: string
  onSelectJob: (jobId: string) => void
  busy: boolean
}) {
  return <section className='space-y-2 border-t pt-4' aria-labelledby='material-task-history-title'>
    <div className='flex flex-wrap items-baseline justify-between gap-2'>
      <h2 id='material-task-history-title' className='text-sm font-semibold'>整理任务历史</h2>
      <span className='text-xs text-muted-foreground'>{jobs.length} 项</span>
    </div>
    {jobs.length === 0 ? <p className='text-sm text-muted-foreground'>尚未为此资料创建任务。</p> : (
      <ul className='divide-y'>
        {jobs.map((job) => <li key={job.id} className='flex flex-wrap items-center justify-between gap-3 py-3'>
          <div className='min-w-0'>
            <p className='font-medium'>{workflowStateLabel(job.state)}</p>
            <p className='mt-1 text-xs text-muted-foreground'>{localDateTime(job.updated_at)} · {job.record_count} 项内容</p>
          </div>
          <Button type='button' variant={selectedJobId === job.id ? 'secondary' : 'outline'} size='sm' disabled={busy} onClick={() => onSelectJob(job.id)}>
            {selectedJobId === job.id ? '正在查看' : '查看任务'}
          </Button>
        </li>)}
      </ul>
    )}
  </section>
}
