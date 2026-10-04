import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ContentWorkspace } from './workspace'
import type { MaterialContentResponse, MaterialPage, PageReadingResponse } from '../../types'

if (!window.PointerEvent) Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent })

const page: MaterialPage = { id: 'page-1', position: 1, sha256: 'private-hash', width: 100, height: 100, page_url: '/page/', preview_url: '/preview/' }
const context = { source_stamp: 'source-stamp-current' }
const secretEditContext = { version: 999, stamp: 'do-not-render-or-submit' }

const question = {
  id: 'question-1', revision_id: 'revision-1', number: '3', printed_text: '原印刷题面', working_text: '当前工作题干',
  sources: [{ page_id: 'page-1', bbox: [1, 2, 30, 40] as [number, number, number, number] }],
  confirmed: true, answer: null, edit_context: secretEditContext, question_url: '/questions/1/',
}

const formulaAst = [{ t: 'f', f: '1/2 + 1/3' }, { t: 'r', v: '⅚' }]

function emptyContent(): MaterialContentResponse {
  return { schema_version: 'swb.api.v1', context, questions: [], nodes: [] }
}

function emptyReading(): PageReadingResponse {
  return { schema_version: 'swb.api.v1', context: { reading_version: 1 }, current: null, history: [] }
}

function mountContent({
  content = emptyContent(),
  reading = emptyReading(),
  onUnauthorized = vi.fn(),
  postResponse,
}: {
  content?: MaterialContentResponse
  reading?: PageReadingResponse
  onUnauthorized?: () => void
  postResponse?: (url: URL, init?: RequestInit) => Promise<Response>
} = {}) {
  const calls: Array<{ url: URL; init?: RequestInit; body?: Record<string, unknown> }> = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin)
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    calls.push({ url, init, body })
    if (init?.method === 'POST' && postResponse) return postResponse(url, init)
    if (init?.method === 'POST') return Response.json({ schema_version: 'swb.api.v1', question_id: 'question-2', revision_id: 'revision-2' })
    if (url.pathname === '/api/v1/materials/material-1/content/') return Response.json(content)
    if (url.pathname === '/api/v1/pages/page-1/reading/') return Response.json(reading)
    throw new Error(`unexpected request: ${url.pathname}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const onBusyChange = vi.fn()
  render(<ContentWorkspace materialId='material-1' pages={[page]} csrfToken='csrf-test' canWrite onUnauthorized={onUnauthorized} onBusyChange={onBusyChange} onClose={vi.fn()} />)
  return { calls, fetchMock, onBusyChange, onUnauthorized }
}

async function addSourceWithDrag(user: ReturnType<typeof userEvent.setup>) {
  const image = (await screen.findAllByAltText('资料页 1 原图'))[0]
  Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 100 })
  Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 100 })
  fireEvent.load(image)
  const overlay = (await screen.findAllByRole('img', { name: '资料页 1 区域选框' }))[0]
  vi.spyOn(overlay, 'getBoundingClientRect').mockReturnValue({
    x: 10, y: 20, left: 10, top: 20, right: 110, bottom: 120, width: 100, height: 100, toJSON: () => ({}),
  })
  fireEvent.pointerDown(overlay, { button: 0, pointerId: 1, clientX: 20, clientY: 30 })
  fireEvent.pointerMove(overlay, { pointerId: 1, clientX: 70, clientY: 80 })
  fireEvent.pointerUp(overlay, { pointerId: 1, clientX: 70, clientY: 80 })
  await user.click(await screen.findByRole('button', { name: '确认添加这个题目来源' }))
}

describe('ContentWorkspace', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('saves a blank, unconfirmed question draft with a selected original-image region', async () => {
    const user = userEvent.setup()
    const { calls } = mountContent()
    await screen.findByRole('button', { name: '保存待补草稿' })
    await user.type(screen.getByLabelText('本次核对原因（必填）'), '原图题干模糊，先保留来源')
    expect((screen.getByRole('button', { name: '保存待补草稿' }) as HTMLButtonElement).disabled).toBe(true)
    await addSourceWithDrag(user)
    const saveDraft = screen.getByRole('button', { name: '保存待补草稿' })
    expect((saveDraft as HTMLButtonElement).disabled).toBe(false)
    await user.click(saveDraft)

    const draftCall = await waitFor(() => calls.find(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/content/draft/')))
    expect(draftCall).toBeDefined()
    expect(draftCall?.url.pathname).toBe('/api/v1/materials/material-1/content/draft/')
    expect(draftCall?.init?.headers).toMatchObject({ 'X-CSRFToken': 'csrf-test' })
    expect(draftCall?.body).toMatchObject({
      expected: context,
      reason: '原图题干模糊，先保留来源',
      printed_text: '',
      original_number: '',
      sources: [{ page_id: 'page-1', bbox: [10, 10, 60, 60] }],
    })
    expect(draftCall?.body?.request_key).toEqual(expect.stringMatching(/^[0-9a-f-]{36}$/i))
    expect(draftCall?.body).not.toHaveProperty('checked')
    expect(draftCall?.body).not.toHaveProperty('answer')
    expect(draftCall?.body).not.toHaveProperty('nodes')
    expect(screen.queryByText(/do-not-render-or-submit|private-hash/)).toBeNull()
  })

  it('preserves existing formula AST and returns the top-level source context while saving an edit', async () => {
    const user = userEvent.setup()
    let releasePost!: (response: Response) => void
    const pendingPost = new Promise<Response>((resolve) => { releasePost = resolve })
    const existing: MaterialContentResponse = {
      ...emptyContent(),
      questions: [{ ...question, answer: { body: '原答案', formulas: formulaAst, basis: '逐步核算', confirmed: true } }],
    }
    const { calls } = mountContent({ content: existing, postResponse: () => pendingPost })
    await user.selectOptions(await screen.findByLabelText('正在核对的题目'), 'question-1')
    expect(screen.getByText('该答案已有 2 个公式，保存时会原样保留。')).toBeTruthy()
    expect(screen.getByRole('link', { name: '高级公式编辑' }).getAttribute('href')).toBe('/questions/1/')
    await user.clear(screen.getByLabelText('家长核对的答案或解答（必填）'))
    await user.type(screen.getByLabelText('家长核对的答案或解答（必填）'), '修订后的答案')
    await user.clear(screen.getByLabelText('答案依据（必填）'))
    await user.type(screen.getByLabelText('答案依据（必填）'), '重新按分母核算')
    await user.type(screen.getByLabelText('本次核对原因（必填）'), '补充答案说明')
    await user.click(screen.getByRole('checkbox', { name: /我已对照原图核对/ }))
    const submit = screen.getByRole('button', { name: '确认并保存题目' })
    await user.click(submit)
    await screen.findByRole('button', { name: '正在保存…' })
    expect((screen.getByLabelText('正在核对的题目') as HTMLSelectElement).disabled).toBe(true)
    expect((screen.getByLabelText('来源页') as HTMLSelectElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '刷新核对数据' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '收起核对面板' }) as HTMLButtonElement).disabled).toBe(true)

    const saveCall = calls.find(({ init, url }) => init?.method === 'POST' && url.pathname.endsWith('/content/'))
    expect(saveCall?.body).toMatchObject({
      expected: context,
      question_id: 'question-1',
      answer: { body: '修订后的答案', formulas: formulaAst, basis: '重新按分母核算' },
    })
    expect(JSON.stringify(saveCall?.body)).not.toContain('do-not-render-or-submit')
    expect(saveCall?.body?.request_key).toEqual(expect.stringMatching(/^[0-9a-f-]{36}$/i))
    await act(async () => { releasePost(Response.json({ schema_version: 'swb.api.v1', question_id: 'question-1', revision_id: 'revision-2' })) })
    expect(await screen.findByText('内容已核对并保存；历史版本和来源仍保留。')).toBeTruthy()
  })

  it('records an erratum through the separate endpoint and retains the printed original', async () => {
    const user = userEvent.setup()
    const existing: MaterialContentResponse = { ...emptyContent(), questions: [question] }
    const { calls } = mountContent({ content: existing })
    await user.selectOptions(await screen.findByLabelText('正在核对的题目'), 'question-1')
    await user.click(screen.getByRole('button', { name: '记录讲义勘误' }))
    expect(screen.getByText('原印刷题面', { selector: 'p' })).toBeTruthy()
    await user.clear(screen.getByLabelText('订正后的讲义题干（必填）'))
    await user.type(screen.getByLabelText('订正后的讲义题干（必填）'), '订正后的内容')
    await user.type(screen.getByLabelText('订正依据（必填）'), '对照出版社勘误表')
    await user.type(screen.getByLabelText('勘误原因（必填）'), '讲义印刷错字')
    await user.click(screen.getByRole('checkbox', { name: /我已核对讲义原文/ }))
    await user.click(screen.getByRole('button', { name: '确认并应用勘误' }))

    const erratumCall = await waitFor(() => calls.find(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/erratum/')))
    expect(erratumCall?.body).toMatchObject({
      expected: context, question_id: 'question-1', corrected_text: '订正后的内容',
      basis: '对照出版社勘误表', checked: true, reason: '讲义印刷错字',
    })
    expect(erratumCall?.body?.request_key).toEqual(expect.stringMatching(/^[0-9a-f-]{36}$/i))
    expect(calls.some(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/content/'))).toBe(false)
  })

  it('blocks complete page coverage with unknown, pending or no partitions, then saves a reviewed region', async () => {
    const user = userEvent.setup()
    const current = {
      reading: 'read', coverage: 'partial', partitions: [{ kind: 'unknown' as const, bbox: [5, 5, 20, 20] as [number, number, number, number] }],
      pending_items: ['右下角题号待辨认'], basis: '已逐区检查', revision_no: 1, recorded_at: '2026-10-04T10:00:00+08:00',
    }
    const reading: PageReadingResponse = { ...emptyReading(), current, history: [current] }
    const { calls } = mountContent({ reading })
    expect(await screen.findByText('未知区域 · 原图区域 [5, 5, 20, 20] px')).toBeTruthy()
    expect(screen.getByText('第 1 次 · 已阅读 · 部分覆盖')).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('阅读覆盖'), 'complete')
    expect(screen.getByRole('alert').textContent).toContain('不能标记为完整覆盖')
    expect((screen.getByRole('button', { name: '保存本页阅读记录' }) as HTMLButtonElement).disabled).toBe(true)

    await user.click(screen.getByRole('button', { name: '移除分区' }))
    await user.clear(screen.getByLabelText('待补事项（每行一项）'))
    const save = screen.getByRole('button', { name: '保存本页阅读记录' })
    expect((save as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('alert').textContent).toContain('尚未标记分区')
    await user.click(save)
    expect(calls.some(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/reading/'))).toBe(false)

    const form = screen.getByLabelText('阅读状态').closest('form')!
    const image = within(form).getByAltText('资料页 1 原图')
    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 100 })
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 100 })
    fireEvent.load(image)
    const overlay = within(form).getByRole('img', { name: '资料页 1 区域选框' })
    vi.spyOn(overlay, 'getBoundingClientRect').mockReturnValue({
      x: 10, y: 20, left: 10, top: 20, right: 110, bottom: 120, width: 100, height: 100, toJSON: () => ({}),
    })
    fireEvent.pointerDown(overlay, { button: 0, pointerId: 1, clientX: 10, clientY: 20 })
    fireEvent.pointerUp(overlay, { pointerId: 1, clientX: 110, clientY: 120 })
    await user.click(within(form).getByRole('button', { name: '确认添加题目分区' }))
    expect((save as HTMLButtonElement).disabled).toBe(false)
    await user.click(save)
    const saveCall = await waitFor(() => calls.find(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/reading/')))
    expect(saveCall?.body).toMatchObject({
      expected: { reading_version: 1 }, reading: 'read', coverage: 'complete', partitions: [{ kind: 'question', bbox: [0, 0, 100, 100] }], pending_items: [], basis: '已逐区检查',
    })
    expect(saveCall?.body?.request_key).toEqual(expect.stringMatching(/^[0-9a-f-]{36}$/i))
  })
})
