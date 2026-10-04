import type { AboutResponse } from '../types'
import type { Remote } from './shared'
import { ApiLink } from './shared'
import { Button } from './ui/button'

export function AboutPanel({ about, onRetry }: { about: Remote<AboutResponse>; onRetry: () => void }) {
  if (about.status === 'loading') return <p className='px-1 py-2 text-sm text-muted-foreground'>正在读取版本信息…</p>
  if (about.status === 'error') {
    return <div className='space-y-2 px-1 py-2'><p className='text-sm text-muted-foreground'>版本与更新信息暂不可用。</p><Button type='button' size='sm' variant='outline' onClick={onRetry}>重试</Button></div>
  }

  const release = about.data.release_state === 'development' ? '开发中' : about.data.release_state === 'stable' ? '稳定版' : '状态未确认'
  return (
    <div className='max-h-[70svh] space-y-3 overflow-y-auto px-1 py-2'>
      <div>
        <p className='text-sm font-semibold'>学习工作台 v{about.data.version}</p>
        <p className='mt-1 text-xs text-muted-foreground'>{release}{about.data.build_date ? ` · 构建于 ${about.data.build_date}` : ''}</p>
      </div>
      <section className='border-t pt-3'>
        <h2 className='text-xs font-semibold'>更新记录</h2>
        {about.data.changelog.length === 0 ? <p className='mt-2 text-xs text-muted-foreground'>暂无更新记录。</p> : (
          <div className='mt-2 space-y-3'>
            {about.data.changelog.map((entry) => (
              <section key={`${entry.version}-${entry.date}`}>
                <h3 className='text-xs font-semibold'>v{entry.version} · {entry.date}</h3>
                <ul className='mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-muted-foreground'>
                  {entry.changes.map((change, index) => <li key={`${index}-${change}`}>{change}</li>)}
                </ul>
              </section>
            ))}
          </div>
        )}
      </section>
      {about.data.help_url ? <div className='border-t pt-3 text-sm'><ApiLink href={about.data.help_url}>使用帮助</ApiLink></div> : null}
    </div>
  )
}
