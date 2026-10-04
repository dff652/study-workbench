import type { AboutResponse } from '../types'
import type { Remote } from './shared'
import { ApiLink, sameOriginHref } from './shared'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

export function AboutPanel({ about, onRetry }: { about: Remote<AboutResponse>; onRetry: () => void }) {
  return (
    <Card className='overflow-hidden border-sidebar-border bg-sidebar text-sidebar-foreground shadow-none'>
      <CardHeader className='gap-2 px-4 pb-3 pt-4'>
        <div className='flex items-center justify-between gap-2'>
          <CardTitle className='text-sm'>版本与更新</CardTitle>
          {about.status === 'loaded' ? (
            <Badge variant='secondary' className='bg-amber-100 text-amber-900 hover:bg-amber-100'>
              {about.data.release_state === 'development' ? '开发中' : about.data.release_state}
            </Badge>
          ) : null}
        </div>
        {about.status === 'loaded' ? (
          <p className='text-xs text-muted-foreground'>当前版本 v{about.data.version}</p>
        ) : about.status === 'loading' ? (
          <p className='text-xs text-muted-foreground'>版本信息加载中</p>
        ) : null}
      </CardHeader>
      <CardContent className='px-4 pb-4'>
        {about.status === 'error' ? (
          <div className='space-y-2'>
            <p className='text-xs leading-5 text-muted-foreground'>更新信息暂不可用。</p>
            <Button type='button' size='sm' variant='outline' className='h-8' onClick={onRetry}>
              重试
            </Button>
          </div>
        ) : about.status === 'loaded' ? (
          <details className='group'>
            <summary className='cursor-pointer list-none text-xs font-medium text-primary marker:hidden'>
              查看更新记录
            </summary>
            <div className='mt-3 space-y-3 border-t pt-3'>
              <p className='break-words text-xs text-muted-foreground'>
                源码版本：{about.data.source_revision === 'unknown' ? '未记录提交身份' : about.data.source_revision}
                <br />构建时间：{about.data.build_date || '未记录'}
              </p>
              {about.data.changelog.length === 0 ? (
                <p className='text-xs text-muted-foreground'>暂无更新记录。</p>
              ) : (
                about.data.changelog.map((entry) => (
                  <section key={`${entry.version}-${entry.date}`}>
                    <h3 className='text-xs font-semibold'>v{entry.version} · {entry.date}</h3>
                    <ul className='mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-muted-foreground'>
                      {entry.changes.map((change, index) => <li key={`${index}-${change}`}>{change}</li>)}
                    </ul>
                  </section>
                ))
              )}
              {sameOriginHref(about.data.help_url) ? (
                <ApiLink href={about.data.help_url}>使用帮助</ApiLink>
              ) : null}
            </div>
          </details>
        ) : null}
      </CardContent>
    </Card>
  )
}
