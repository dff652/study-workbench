import { useCallback, useEffect, useState } from 'react'
import { CalendarClock, ClipboardList, GraduationCap, House, Layers3 } from 'lucide-react'
import { api, ApiError } from './api'
import { AboutPanel } from './components/about-panel'
import { NavButton } from './components/nav-button'
import { EmptyState, isUnauthorized, type Remote } from './components/shared'
import { Main } from './components/layout/main'
import { Button } from './components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { MaterialWorkspace } from './features/materials/workspace'
import { EvidenceWorkspace } from './features/evidence/workspace'
import { ProgressWorkspace } from './features/progress/workspace'
import type { AboutResponse, LearnersResponse, SessionResponse } from './types'

type Page = 'materials' | 'progress' | 'overview' | 'attempts'

export default function App() {
  const [session, setSession] = useState<Remote<SessionResponse>>({ status: 'loading' })
  const [about, setAbout] = useState<Remote<AboutResponse>>({ status: 'loading' })
  const [learners, setLearners] = useState<Remote<LearnersResponse>>({ status: 'loading' })
  const [householdId, setHouseholdId] = useState('')
  const [learnerId, setLearnerId] = useState('')
  const [activePage, setActivePage] = useState<Page>('materials')
  const [sessionRetry, setSessionRetry] = useState(0)
  const [aboutRetry, setAboutRetry] = useState(0)
  const [learnersRetry, setLearnersRetry] = useState(0)
  const [unauthorized, setUnauthorized] = useState(false)

  const handleUnauthorized = useCallback(() => setUnauthorized(true), [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setSession({ status: 'loading' })
    setUnauthorized(false)
    api.session(controller.signal).then((data) => {
      if (!active) return
      setSession({ status: 'loaded', data })
      setHouseholdId((current) => current && data.households.some((item) => item.id === current)
        ? current
        : data.households[0]?.id || '')
    }).catch((error: unknown) => {
      if (!active) return
      setSession({ status: 'error', message: messageFor(error) })
      if (isUnauthorized(error)) setUnauthorized(true)
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [sessionRetry])

  useEffect(() => {
    if (session.status !== 'loaded') return
    const controller = new AbortController()
    let active = true
    setAbout({ status: 'loading' })
    api.about(controller.signal).then((data) => {
      if (active) setAbout({ status: 'loaded', data })
    }).catch((error: unknown) => {
      if (!active) return
      setAbout({ status: 'error', message: messageFor(error) })
      if (isUnauthorized(error)) handleUnauthorized()
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [session.status, aboutRetry, handleUnauthorized])

  useEffect(() => {
    if (session.status !== 'loaded' || !householdId) {
      setLearners({ status: 'loading' })
      setLearnerId('')
      return
    }
    const controller = new AbortController()
    let active = true
    setLearners({ status: 'loading' })
    setLearnerId('')
    api.learners(householdId, controller.signal).then((data) => {
      if (!active) return
      setLearners({ status: 'loaded', data })
      setLearnerId((current) => data.items.some((item) => item.id === current)
        ? current
        : data.items[0]?.id || '')
    }).catch((error: unknown) => {
      if (!active) return
      setLearners({ status: 'error', message: messageFor(error) })
      if (isUnauthorized(error)) handleUnauthorized()
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [session.status, householdId, learnersRetry, handleUnauthorized])

  if (unauthorized) return <LoginRequired onRetry={() => setSessionRetry((count) => count + 1)} />
  if (session.status === 'loading') {
    return <div className='flex min-h-svh items-center justify-center bg-muted/40 p-5'><p role='status'>正在连接学习工作台…</p></div>
  }
  if (session.status === 'error') {
    return (
      <div className='flex min-h-svh items-center justify-center bg-muted/40 p-5'>
        <Card className='w-full max-w-lg'>
          <CardHeader><CardTitle>连接学习工作台失败</CardTitle><CardDescription>{session.message}</CardDescription></CardHeader>
          <CardContent><Button type='button' onClick={() => setSessionRetry((count) => count + 1)}>重试连接</Button></CardContent>
        </Card>
      </div>
    )
  }

  const households = session.data.households
  const selectedHousehold = households.find((item) => item.id === householdId)
  const learner = learners.status === 'loaded'
    ? learners.data.items.find((item) => item.id === learnerId)
    : undefined
  const title = activePage === 'materials'
    ? '资料整理'
    : activePage === 'progress'
      ? '进度与复测'
      : activePage === 'overview'
        ? '学习总览'
        : '作答记录'
  const householdQuery = householdId ? new URLSearchParams({ household_id: householdId }).toString() : ''

  const selectHousehold = (nextId: string) => {
    setHouseholdId(nextId)
    setLearnerId('')
    setLearners({ status: 'loading' })
  }

  return (
    <div className='min-h-svh bg-muted/30 text-foreground'>
      <a href='#content' className='fixed left-4 top-2 z-[100] -translate-y-16 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus:translate-y-0'>跳到主要内容</a>
      <div className='min-h-svh lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]'>
        <aside className='border-b bg-sidebar text-sidebar-foreground lg:sticky lg:top-0 lg:h-svh lg:border-b-0 lg:border-r'>
          <div className='flex items-center gap-3 px-5 py-5'>
            <div className='flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground'><GraduationCap className='size-5' aria-hidden='true' /></div>
            <div>
              <p className='font-semibold leading-tight'>学习工作台</p>
              <p className='mt-1 text-xs text-muted-foreground'>家庭学习与资料整理</p>
            </div>
          </div>
          <nav aria-label='主导航' className='flex gap-2 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible'>
            <NavButton active={activePage === 'materials'} icon={House} onClick={() => setActivePage('materials')}>资料整理</NavButton>
            <NavButton active={activePage === 'progress'} icon={CalendarClock} onClick={() => setActivePage('progress')}>进度与复测</NavButton>
            <NavButton active={activePage === 'overview'} icon={Layers3} onClick={() => setActivePage('overview')}>学习总览</NavButton>
            <NavButton active={activePage === 'attempts'} icon={ClipboardList} onClick={() => setActivePage('attempts')}>作答记录</NavButton>
          </nav>
          {householdId ? <section className='mx-3 mb-4 rounded-lg border border-sidebar-border px-3 py-3'>
            <h2 className='mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground'>更多工具</h2>
            <nav aria-label='更多工具' className='flex flex-col gap-2 text-sm'>
              <a className='rounded-md px-2 py-1.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground' href={`/knowledge/?${householdQuery}`}>知识与题库</a>
              <a className='rounded-md px-2 py-1.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground' href={`/learning/?household=${encodeURIComponent(householdId)}`}>学习档案</a>
              <a className='rounded-md px-2 py-1.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground' href={`/members/?${householdQuery}`}>家庭成员</a>
              <a className='rounded-md px-2 py-1.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground' href={`/ai/config/${encodeURIComponent(householdId)}/`}>模型配置</a>
            </nav>
          </section> : null}
          <div className='hidden px-3 pb-4 lg:block'><AboutPanel about={about} onRetry={() => setAboutRetry((count) => count + 1)} /></div>
        </aside>

        <div className='min-w-0'>
          <header className='sticky top-0 z-30 border-b bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75'>
            <div className='flex min-h-16 items-center justify-between gap-4 px-4 py-3 sm:px-6 xl:px-8'>
              <div className='min-w-0'>
                <p className='text-xs font-medium uppercase tracking-wide text-muted-foreground'>{title}</p>
                <p className='truncate text-sm font-semibold'>{session.data.user.username}</p>
              </div>
              <div className='flex shrink-0 items-center gap-2'>
                {about.status === 'loaded' ? <><span className='hidden text-xs text-muted-foreground sm:inline'>v{about.data.version}</span><span className='rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900'>{releaseLabel(about.data.release_state)}</span></> : null}
                {about.status === 'error' ? <button className='text-xs text-muted-foreground underline' type='button' onClick={() => setAboutRetry((count) => count + 1)}>版本信息重试</button> : null}
                <form method='post' action='/accounts/logout/' className='ml-1'>
                  <input type='hidden' name='csrfmiddlewaretoken' value={session.data.csrf_token} />
                  <Button type='submit' variant='outline' size='sm'>退出</Button>
                </form>
              </div>
            </div>
          </header>

          <Main id='content' fluid className='space-y-6 px-4 py-6 sm:px-6 xl:px-8'>
            <div className='flex flex-wrap items-end justify-between gap-4'>
              <div>
                <h1 className='text-2xl font-semibold tracking-tight sm:text-3xl'>{title}</h1>
                <p className='mt-2 max-w-2xl text-sm leading-6 text-muted-foreground'>
                  {activePage === 'materials'
                    ? '从家庭资料开始，按来源核对题面与作答内容，再检查五册输出。'
                    : activePage === 'progress'
                      ? '统一查看资料整理、知识与题型关联、真实学习证据和复测计划。'
                      : '查看逐次作答、来源和评价依据。未知与未测状态会明确保留。'}
                </p>
              </div>
              {activePage === 'materials' ? <a href='/materials/' className='text-sm font-medium text-primary underline-offset-4 hover:underline'>打开旧版资料库</a> : null}
            </div>

            {households.length === 0 ? (
              <EmptyState title='当前账号没有可访问的家庭' detail='请使用有权限的账号登录，或联系家庭所有者调整访问权限。' icon={House} />
            ) : (
              <Card className='shadow-sm'>
                <CardContent className='grid gap-4 p-4 sm:grid-cols-[minmax(14rem,0.8fr)_minmax(14rem,1fr)] sm:items-end sm:p-5'>
                  <div>
                    <p id='household-label' className='mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground'><House className='size-3.5' aria-hidden='true' />家庭</p>
                    {households.length === 1 ? (
                      <div className='flex h-10 items-center rounded-md border bg-muted/40 px-3 text-sm font-medium'>{households[0].name}</div>
                    ) : (
                      <select aria-labelledby='household-label' className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={householdId} onChange={(event) => selectHousehold(event.target.value)}>
                        {households.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                      </select>
                    )}
                  </div>
                  {activePage !== 'materials' ? (
                    <div>
                      <p id='learner-label' className='mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground'><GraduationCap className='size-3.5' aria-hidden='true' />学习者</p>
                      {learners.status === 'loading' ? <div className='flex h-10 items-center rounded-md border bg-muted/20 px-3 text-sm text-muted-foreground'>读取学习者…</div> : null}
                      {learners.status === 'error' ? <div className='flex h-10 items-center justify-between rounded-md border border-amber-300 bg-amber-50 px-3 text-xs text-amber-900'><span>读取失败</span><button type='button' className='underline' onClick={() => setLearnersRetry((count) => count + 1)}>重试</button></div> : null}
                      {learners.status === 'loaded' && learners.data.items.length > 0 ? (
                        <select aria-labelledby='learner-label' className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={learnerId} onChange={(event) => setLearnerId(event.target.value)}>
                          {learners.data.items.map((item) => <option key={item.id} value={item.id}>{item.display_name}{item.grade ? ` · ${item.grade}` : ''}</option>)}
                        </select>
                      ) : null}
                      {learners.status === 'loaded' && learners.data.items.length === 0 ? <div className='flex h-10 items-center rounded-md border border-dashed px-3 text-sm text-muted-foreground'>暂无学习者记录</div> : null}
                    </div>
                  ) : (
                    <div className='rounded-lg bg-primary/[0.04] px-4 py-3'>
                      <p className='text-xs text-muted-foreground'>当前家庭</p>
                      <p className='mt-1 truncate font-semibold'>{selectedHousehold?.name || '未选择'}</p>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {households.length > 0 && activePage === 'materials' ? (
              <MaterialWorkspace
                key={householdId}
                householdId={householdId}
                householdName={selectedHousehold?.name || ''}
                csrfToken={session.data.csrf_token}
                canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
                learners={learners.status === 'loaded' ? learners.data.items : []}
                selectedLearnerId={learnerId}
                onUnauthorized={handleUnauthorized}
              />
            ) : null}
            {households.length > 0 && activePage !== 'materials' && learners.status === 'error' ? (
              <Card className='border-amber-300/70 bg-amber-50/70'><CardContent className='flex flex-wrap items-center justify-between gap-3 p-5'><p className='text-sm'>{learners.message}</p><Button type='button' variant='outline' onClick={() => setLearnersRetry((count) => count + 1)}>重试</Button></CardContent></Card>
            ) : null}
            {households.length > 0 && activePage !== 'materials' && learners.status === 'loaded' && learners.data.items.length === 0 ? (
              <EmptyState title='这个家庭还没有学习者' detail='添加学习者后，这里会显示真实的作答和证据记录。' icon={GraduationCap} />
            ) : null}
            {households.length > 0 && activePage !== 'materials' && learner ? (
              activePage === 'progress' ? (
                <ProgressWorkspace
                  key={`${householdId}:${learner.id}`}
                  householdId={householdId}
                  learner={learner}
                  csrfToken={session.data.csrf_token}
                  canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
                  onUnauthorized={handleUnauthorized}
                />
              ) : (
                <EvidenceWorkspace key={`${householdId}:${learner.id}`} householdId={householdId} learner={learner} activePage={activePage} onUnauthorized={handleUnauthorized} />
              )
            ) : null}
          </Main>
          <div className='px-4 pb-5 sm:px-6 xl:px-8 lg:hidden'><AboutPanel about={about} onRetry={() => setAboutRetry((count) => count + 1)} /></div>
        </div>
      </div>
    </div>
  )
}

function LoginRequired({ onRetry }: { onRetry: () => void }) {
  return (
    <div className='flex min-h-svh items-center justify-center bg-muted/40 p-5'>
      <Card className='w-full max-w-lg'>
        <CardHeader>
          <div className='flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground'><House className='size-6' aria-hidden='true' /></div>
          <CardTitle className='mt-2 text-xl'>请先登录学习工作台</CardTitle>
          <CardDescription>登录后可查看所属家庭的学习记录和原图证据。</CardDescription>
        </CardHeader>
        <CardContent className='space-y-4'>
          <Button asChild><a href='/accounts/login/?next=/app/'>前往登录</a></Button>
          <button type='button' className='ml-3 text-sm text-primary underline-offset-4 hover:underline' onClick={onRetry}>重试连接</button>
        </CardContent>
      </Card>
    </div>
  )
}

function messageFor(error: unknown) {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : '连接暂时不可用，请重试。'
}

function releaseLabel(releaseState: string) {
  return releaseState === 'development' ? '开发中' : releaseState
}
