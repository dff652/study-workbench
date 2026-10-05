import { BookOpenCheck, FileText } from 'lucide-react'
import type { ProgressResponse } from '../../types'
import { ApiLink, EmptyState, formatCount, LoadingState, RetryState, type Remote } from '../../components/shared'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'

const MATERIAL_GROUPS = [
  {
    title: '资料与页面',
    icon: FileText,
    metrics: [
      { key: 'material_count', label: '资料', unit: '项' },
      { key: 'page_count', label: '资料页', unit: '页' },
      { key: 'pages_complete', label: '已整理', unit: '页' },
      { key: 'pages_unread', label: '待整理', unit: '页' },
      { key: 'pages_need_retake', label: '待重拍', unit: '页' },
    ],
  },
  {
    title: '题目',
    icon: BookOpenCheck,
    metrics: [
      { key: 'questions_confirmed', label: '已确认', unit: '道' },
      { key: 'questions_pending', label: '待确认', unit: '道' },
    ],
  },
  {
    title: '整理任务',
    icon: BookOpenCheck,
    metrics: [
      { key: 'open_workflows', label: '进行中', unit: '项' },
      { key: 'completed_workflows', label: '已完成', unit: '项' },
    ],
  },
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

      <div className='grid gap-3 lg:grid-cols-3'>
        {MATERIAL_GROUPS.map(({ title, icon: Icon, metrics }) => (
          <Card key={title} className='gap-0 py-0 shadow-sm'>
            <CardHeader className='border-b py-3'>
              <CardTitle className='flex items-center gap-2 text-sm'><Icon className='size-4 text-primary' aria-hidden='true' />{title}</CardTitle>
            </CardHeader>
            <CardContent className='grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3'>
              {metrics.map(({ key, label, unit }) => (
                <div key={key}>
                  <p className='text-xs text-muted-foreground'>{label}</p>
                  <p className='mt-1 font-semibold tabular-nums'>{formatCount(counts[key])} <span className='text-xs font-normal text-muted-foreground'>{unit}</span></p>
                </div>
              ))}
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
                <p className='text-sm'><span className='text-muted-foreground'>已整理：</span>{formatCount(material.pages_complete)} 页</p>
                <p className='text-sm'><span className='text-muted-foreground'>待整理：</span>{formatCount(material.pages_unread)} 页</p>
                <p className='text-sm'><span className='text-muted-foreground'>待重拍：</span>{formatCount(material.pages_need_retake)} 页</p>
                <p className='text-sm sm:col-start-2'><span className='text-muted-foreground'>已确认题目：</span>{formatCount(material.questions_confirmed)} 道</p>
                <p className='text-sm'><span className='text-muted-foreground'>待确认题目：</span>{formatCount(material.questions_pending)} 道</p>
              </article>
            ))}
          </CardContent>
        </Card>
      )}
    </section>
  )
}
