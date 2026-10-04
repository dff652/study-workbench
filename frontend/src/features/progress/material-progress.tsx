import { BookOpenCheck, FileText, RotateCcw, Workflow } from 'lucide-react'
import type { ProgressResponse } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, type Remote } from '../../components/shared'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'

const MATERIAL_METRICS = [
  { key: 'material_count', label: '资料', icon: FileText },
  { key: 'page_count', label: '资料页', icon: BookOpenCheck },
  { key: 'pages_complete', label: '已整理页面', icon: BookOpenCheck },
  { key: 'pages_unread', label: '待整理页面', icon: FileText },
  { key: 'pages_need_retake', label: '需要重拍', icon: RotateCcw },
  { key: 'questions_confirmed', label: '已确认题目', icon: BookOpenCheck },
  { key: 'questions_pending', label: '待确认题目', icon: FileText },
  { key: 'open_workflows', label: '进行中任务', icon: Workflow },
  { key: 'completed_workflows', label: '已完成任务', icon: Workflow },
] as const

export function MaterialProgress({ remote, onRetry }: { remote: Remote<ProgressResponse>; onRetry: () => void }) {
  if (remote.status === 'loading') return <LoadingState label='正在读取资料进度…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={onRetry} />

  const { counts, materials, total, scope } = remote.data
  return (
    <section className='space-y-4' aria-labelledby='material-progress-title'>
      <div className='flex flex-wrap items-end justify-between gap-2'>
        <div>
          <h2 id='material-progress-title' className='text-lg font-semibold'>资料进度</h2>
          <p className='mt-1 text-sm text-muted-foreground'>截至 {scope.as_of}；显示已记录的资料、页面、题目和任务数量。</p>
        </div>
        <p className='text-xs text-muted-foreground'>资料 {formatCount(materials.length)} / {formatCount(total)} 项</p>
      </div>

      <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-3'>
        {MATERIAL_METRICS.map(({ key, label, icon: Icon }) => (
          <Card key={key} className='gap-0 py-0 shadow-sm'>
            <CardContent className='flex items-center justify-between gap-3 px-4 py-4'>
              <div>
                <p className='text-xs font-medium text-muted-foreground'>{label}</p>
                <p className='mt-1 text-2xl font-semibold tabular-nums'>{formatCount(counts[key])}</p>
              </div>
              <Icon className='size-5 text-primary' aria-hidden='true' />
            </CardContent>
          </Card>
        ))}
      </div>

      {materials.length === 0 ? (
        <EmptyState title='当前家庭还没有资料' detail='资料页和题目进度会在家庭资料进入工作台后显示。' icon={FileText} />
      ) : (
        <Card className='gap-0 py-0 shadow-sm'>
          <CardHeader className='border-b py-4'>
            <CardTitle className='text-base'>资料清单</CardTitle>
            <CardDescription>最多展示 200 项；汇总仍按全部资料数计算。</CardDescription>
          </CardHeader>
          <CardContent className='divide-y px-0 py-0'>
            {materials.map((material) => (
              <article key={material.id} className='grid gap-3 px-5 py-4 sm:grid-cols-[minmax(12rem,1fr)_repeat(3,minmax(7rem,auto))] sm:items-center'>
                <div className='min-w-0'>
                  <ApiLink href={material.material_url}>{material.title || '未命名资料'}</ApiLink>
                  <p className='mt-1 text-xs text-muted-foreground'>{formatCount(material.page_count)} 页</p>
                </div>
                <p className='text-sm'><span className='text-muted-foreground'>已整理：</span>{formatCount(material.pages_complete)}</p>
                <p className='text-sm'><span className='text-muted-foreground'>待整理：</span>{formatCount(material.pages_unread)}</p>
                <p className='text-sm'><span className='text-muted-foreground'>待重拍：</span>{formatCount(material.pages_need_retake)}</p>
                <p className='text-sm sm:col-start-2'><span className='text-muted-foreground'>已确认题目：</span>{formatCount(material.questions_confirmed)}</p>
                <p className='text-sm'><span className='text-muted-foreground'>待确认题目：</span>{formatCount(material.questions_pending)}</p>
              </article>
            ))}
          </CardContent>
        </Card>
      )}
    </section>
  )
}
