import { Check, CircleAlert, FileImage, FileText, ListChecks } from 'lucide-react'
import type { MaterialDetailResponse, WorkflowJob } from '../../types'
import { ApiLink } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { workflowStateLabel, localDateTime } from './workflow-labels'

export function MaterialReadiness({
  detail,
  selectedJobId,
  onSelectJob,
  busy,
}: {
  detail: MaterialDetailResponse
  selectedJobId: string
  onSelectJob: (jobId: string) => void
  busy: boolean
}) {
  const { material, pages, readiness, jobs } = detail
  return (
    <div className='space-y-5'>
      <Card>
        <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b pb-4'>
          <div>
            <CardTitle className='flex items-center gap-2 text-base'><FileImage className='size-4 text-primary' aria-hidden='true' />原图资料页</CardTitle>
            <CardDescription className='mt-1'>原图保持原样。仅显示当前资料中的已保存页面。</CardDescription>
          </div>
          <div className='flex flex-wrap gap-3 text-sm'>
            <ApiLink href={material.material_url}>旧版资料页：编辑题面和来源</ApiLink>
            <ApiLink href={material.prepare_url}>旧版五册准备页</ApiLink>
          </div>
        </CardHeader>
        <CardContent className='pt-5'>
          {pages.length === 0 ? (
            <div className='rounded-lg border border-dashed p-5 text-sm text-muted-foreground'>尚未上传原图。选择一张本机图片后可逐张上传，服务端保留原始文件。</div>
          ) : (
            <ul className='grid gap-3 sm:grid-cols-2 xl:grid-cols-3'>
              {pages.map((page) => (
                <li key={page.id} className='rounded-lg border bg-muted/10 p-4'>
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
              <CardTitle className='flex items-center gap-2 text-base'><ListChecks className='size-4 text-primary' aria-hidden='true' />五册生成前检查</CardTitle>
              <CardDescription className='mt-1'>完整度仅针对当前资料和检查项，不代表整页内容都已完成。</CardDescription>
            </div>
            <Badge variant={readiness.ready ? 'secondary' : 'outline'}>{readiness.ready ? '可进入输出检查' : '仍有待核对项'}</Badge>
          </div>
        </CardHeader>
        <CardContent className='grid gap-5 pt-5 xl:grid-cols-2'>
          <section>
            <h3 className='mb-2 flex items-center gap-2 text-sm font-semibold'><CircleAlert className='size-4 text-amber-700' aria-hidden='true' />阻塞项</h3>
            {readiness.gaps.length === 0 ? <p className='rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900'>当前没有阻塞项。</p> : (
              <ul className='space-y-2'>
                {readiness.gaps.map((gap, index) => <li key={`${index}-${gap}`} className='rounded-md bg-amber-50 px-3 py-2 text-sm leading-5 text-amber-950'>{gap}</li>)}
              </ul>
            )}
            <h3 className='mb-2 mt-5 flex items-center gap-2 text-sm font-semibold'><FileText className='size-4 text-sky-700' aria-hidden='true' />待补内容与页面覆盖</h3>
            {readiness.content_gaps.length === 0 ? <p className='rounded-md bg-muted/40 px-3 py-2 text-sm text-muted-foreground'>当前没有待补提示。</p> : (
              <ul className='space-y-2'>
                {readiness.content_gaps.map((gap, index) => <li key={`${index}-${gap}`} className='rounded-md bg-sky-50 px-3 py-2 text-sm leading-5 text-sky-950'>{gap}</li>)}
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
                  </li>
                ))}
              </ul>
            )}
            <p className='mt-3 text-xs leading-5 text-muted-foreground'>上传完成不等于整理完成；未读取页、未知内容和需重拍处由旧版页面继续记录。</p>
          </section>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className='border-b pb-4'>
          <CardTitle className='text-base'>资料任务历史</CardTitle>
          <CardDescription>只显示最近任务；选择一项可查看阶段、事件和当前操作。</CardDescription>
        </CardHeader>
        <CardContent className='pt-4'>
          {jobs.length === 0 ? <p className='text-sm text-muted-foreground'>尚未为此资料创建任务。</p> : (
            <ul className='space-y-2'>
              {jobs.map((job: WorkflowJob) => (
                <li key={job.id} className='flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3'>
                  <div className='min-w-0'>
                    <p className='font-medium'>{workflowStateLabel(job.state)}</p>
                    <p className='mt-1 text-xs text-muted-foreground'>{localDateTime(job.updated_at)} · {job.record_count} 项结构化记录</p>
                  </div>
                  <Button type='button' variant={selectedJobId === job.id ? 'secondary' : 'outline'} size='sm' disabled={busy} onClick={() => onSelectJob(job.id)}>
                    {selectedJobId === job.id ? '正在查看' : '查看任务'}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
