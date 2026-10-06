import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ContentWorkspace } from './workspace'
import type { MaterialContentResponse, MaterialPage, PageReadingResponse } from '../../types'

if (!window.PointerEvent) Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent })

const page: MaterialPage = { id: 'page-1', position: 1, sha256: 'private-hash', width: 100, height: 100, page_url: '/page/', preview_url: '/preview/' }
const context = { source_stamp: 'source-stamp-current' }
const secretEditContext = { version: 999, stamp: 'do-not-render-or-submit' }
const originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')

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
  pages = [page],
  onUnauthorized = vi.fn(),
  onUnsavedChange = vi.fn(),
  postResponse,
  contentResponse,
}: {
  content?: MaterialContentResponse
  reading?: PageReadingResponse
  pages?: MaterialPage[]
  onUnauthorized?: () => void
  onUnsavedChange?: (dirty: boolean) => void
  postResponse?: (url: URL, init?: RequestInit) => Promise<Response>
  contentResponse?: (requestNo: number) => Response | Promise<Response>
} = {}) {
  const calls: Array<{ url: URL; init?: RequestInit; body?: Record<string, unknown> }> = []
  let contentReads = 0
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin)
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    calls.push({ url, init, body })
    if (init?.method === 'POST' && postResponse) return postResponse(url, init)
    if (init?.method === 'POST') return Response.json({ schema_version: 'swb.api.v1', question_id: 'question-2', revision_id: 'revision-2' })
    if (url.pathname === '/api/v1/materials/material-1/content/') return contentResponse ? contentResponse(++contentReads) : Response.json(content)
    if (/^\/api\/v1\/pages\/[^/]+\/reading\/$/.test(url.pathname)) return Response.json(reading)
    throw new Error(`unexpected request: ${url.pathname}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const onBusyChange = vi.fn()
  render(<ContentWorkspace materialId='material-1' pages={pages} csrfToken='csrf-test' canWrite onUnauthorized={onUnauthorized} onBusyChange={onBusyChange} onUnsavedChange={onUnsavedChange} onClose={vi.fn()} />)
  return { calls, fetchMock, onBusyChange, onUnauthorized, onUnsavedChange }
}

async function addSourceWithDrag(user: ReturnType<typeof userEvent.setup>, confirmSelection = true) {
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
  const addSelection = await screen.findByRole('button', { name: '确认添加这个题目来源' })
  if (confirmSelection) await user.click(addSelection)
}

describe('ContentWorkspace', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    if (originalScrollIntoView) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScrollIntoView)
    else Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
  })

  it('locates real text, source canvas and manual confirmation gaps without completing them', async () => {
    const user = userEvent.setup()
    const scrollIntoView = vi.fn()
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
    const incompleteQuestion = {
      ...question,
      printed_text: '',
      working_text: '',
      missing_fields: ['printed_text', 'working_text'],
      sources_ready: false,
      confirmed: false,
    }
    mountContent({ content: { ...emptyContent(), questions: [incompleteQuestion] } })

    const printedRow = await screen.findByText('待补：图中印刷题面转写')
    const printedJump = within(printedRow.closest('li')!).getByRole('button', { name: '去补充：图中印刷题面转写' })
    expect(printedJump.getAttribute('data-ux-target')).toBe('content-gap-printed-text')
    await user.click(printedJump)
    const printed = screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement
    expect(document.activeElement).toBe(printed)
    expect(printed.value).toBe('')
    expect(scrollIntoView).toHaveBeenCalled()

    const image = screen.getAllByAltText('资料页 1 原图')[0]
    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 100 })
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 100 })
    fireEvent.load(image)
    const sourceRow = screen.getByText('待补：原图来源区域')
    const sourceJump = within(sourceRow.closest('li')!).getByRole('button', { name: '去补充：原图来源区域' })
    expect(sourceJump.getAttribute('data-ux-target')).toBe('content-gap-source-region')
    await user.click(sourceJump)
    const canvas = await screen.findByRole('img', { name: '资料页 1 区域选框' })
    await waitFor(() => expect(document.activeElement).toBe(canvas))
    expect(canvas.getAttribute('id')).toBe('content-question-source-canvas')
    expect(canvas.getAttribute('tabindex')).toBe('0')
    expect(canvas.getAttribute('aria-disabled')).toBe('false')
    expect(scrollIntoView).toHaveBeenCalledTimes(2)

    const confirmRow = screen.getByText('待补：人工核对与确认')
    const confirmationJump = within(confirmRow.closest('li')!).getByRole('button', { name: '去补充：人工核对与确认' })
    expect(confirmationJump.getAttribute('data-ux-target')).toBe('content-gap-confirmation')
    await user.click(confirmationJump)
    const confirmation = screen.getByRole('checkbox', { name: /我已对照原图核对题面/ })
    expect(document.activeElement).toBe(confirmation)
    expect((confirmation as HTMLInputElement).checked).toBe(false)
    expect(screen.getByText('待补：人工核对与确认')).toBeTruthy()
  })

  it('keeps unknown server missing fields visible without a misleading jump action', async () => {
    const opaqueQuestion = {
      ...question,
      missing_fields: ['opaque_server_field'],
      sources_ready: true,
      confirmed: false,
    }
    mountContent({ content: { ...emptyContent(), questions: [opaqueQuestion] } })
    const row = await screen.findByText('待核对：其他内容待核对')
    expect(within(row.closest('li')!).queryByRole('button')).toBeNull()
    expect(within(row.closest('li')!).getByText(/无法对应到本页的具体控件/)).toBeTruthy()
    expect(within(row.closest('li')!).getByText('查看缺项记录')).toBeTruthy()
    expect(row.closest('li')!.querySelector('details')?.open).toBe(false)
    expect(row.closest('li')!.querySelector('code')?.textContent).toBe('opaque_server_field')
  })

  it('does not derive a second work-text requirement when printed text is usable', async () => {
    const user = userEvent.setup()
    const printedOnlyQuestion = { ...question, working_text: '', sources_ready: true }
    mountContent({ content: { ...emptyContent(), questions: [printedOnlyQuestion] } })
    await screen.findByLabelText('正在核对的题目')
    await user.selectOptions(screen.getByLabelText('正在核对的题目'), 'question-1')
    expect(screen.queryByText('待补：当前工作题干字段')).toBeNull()
    expect(screen.getByText('已具备：可用于练习的题面文本已记录')).toBeTruthy()
  })

  it('shows an explicitly flagged work-text field without requiring duplicate text for practice', async () => {
    const explicitlyFlaggedQuestion = {
      ...question,
      working_text: '',
      missing_fields: ['working_text'],
      sources_ready: true,
      confirmed: false,
    }
    mountContent({ content: { ...emptyContent(), questions: [explicitlyFlaggedQuestion] } })
    const workTextRow = await screen.findByText('待核对：当前工作题干字段')
    expect(within(workTextRow.closest('li')!).queryByRole('button')).toBeNull()
    expect(screen.getByText('已具备：可用于练习的题面文本已记录')).toBeTruthy()
  })

  it('keeps question input when a question switch is cancelled and switches after confirmation', async () => {
    const user = userEvent.setup()
    const secondQuestion = { ...question, id: 'question-2', revision_id: 'revision-2', number: '4', printed_text: '第二题题面' }
    mountContent({ content: { ...emptyContent(), questions: [question, secondQuestion] } })
    const picker = await screen.findByLabelText('正在核对的题目')
    await user.selectOptions(picker, 'question-1')
    const printed = screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement
    await user.clear(printed)
    await user.type(printed, '尚未保存的题面')

    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    await user.selectOptions(picker, 'question-2')
    expect((picker as HTMLSelectElement).value).toBe('question-1')
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('尚未保存的题面')

    await user.selectOptions(picker, 'question-2')
    expect((picker as HTMLSelectElement).value).toBe('question-2')
    expect((await screen.findByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('第二题题面')
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('confirms source-page changes and refreshes before discarding reading input', async () => {
    const user = userEvent.setup()
    const secondPage = { ...page, id: 'page-2', position: 2 }
    mountContent({ pages: [page, secondPage] })
    const basis = await screen.findByLabelText('阅读依据（必填）') as HTMLTextAreaElement
    await user.type(basis, '尚未保存的阅读依据')

    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true).mockReturnValueOnce(false).mockReturnValueOnce(true)
    const sourcePage = screen.getByLabelText('来源页')
    await user.selectOptions(sourcePage, 'page-2')
    expect((sourcePage as HTMLSelectElement).value).toBe('page-1')
    expect((screen.getByLabelText('阅读依据（必填）') as HTMLTextAreaElement).value).toBe('尚未保存的阅读依据')

    await user.selectOptions(sourcePage, 'page-2')
    expect((sourcePage as HTMLSelectElement).value).toBe('page-2')
    expect((await screen.findByLabelText('阅读依据（必填）') as HTMLTextAreaElement).value).toBe('')

    await user.selectOptions(screen.getByLabelText('正在核对的题目'), '')
    await user.type(screen.getByLabelText('图中印刷题面转写（必填）'), '尚未保存的新题面')
    await user.click(screen.getByRole('button', { name: '刷新核对数据' }))
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('尚未保存的新题面')
    await user.click(screen.getByRole('button', { name: '刷新核对数据' }))
    await screen.findByRole('button', { name: '保存待补草稿' })
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('')
    expect(confirm).toHaveBeenCalledTimes(4)
  })

  it('confirms source-page changes with a pending question region and keeps the question draft', async () => {
    const user = userEvent.setup()
    const onUnsavedChange = vi.fn()
    const secondPage = { ...page, id: 'page-2', position: 2 }
    mountContent({ pages: [page, secondPage], onUnsavedChange })
    const printed = await screen.findByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement
    await user.type(printed, '保留的题目草稿')
    await addSourceWithDrag(user, false)

    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const sourcePage = screen.getByLabelText('来源页')
    await user.selectOptions(sourcePage, 'page-2')
    expect((sourcePage as HTMLSelectElement).value).toBe('page-1')
    expect(screen.getByRole('button', { name: '确认添加这个题目来源' })).toBeTruthy()
    expect(printed.value).toBe('保留的题目草稿')

    await user.selectOptions(sourcePage, 'page-2')
    await waitFor(() => expect((sourcePage as HTMLSelectElement).value).toBe('page-2'))
    await waitFor(() => expect(screen.queryByRole('button', { name: '确认添加这个题目来源' })).toBeNull())
    expect(screen.getByLabelText('图中印刷题面转写（必填）')).toBe(printed)
    expect(printed.value).toBe('保留的题目草稿')
    expect(onUnsavedChange).toHaveBeenLastCalledWith(true)
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('clears only the saved form from the aggregate dirty state', async () => {
    const user = userEvent.setup()
    const onUnsavedChange = vi.fn()
    mountContent({ content: { ...emptyContent(), questions: [question] }, onUnsavedChange })
    await user.selectOptions(await screen.findByLabelText('正在核对的题目'), 'question-1')
    await user.clear(screen.getByLabelText('图中印刷题面转写（必填）'))
    await user.type(screen.getByLabelText('图中印刷题面转写（必填）'), '已编辑题面')
    await user.type(screen.getByLabelText('阅读依据（必填）'), '未保存阅读依据')
    await user.type(screen.getByLabelText('本次核对原因（必填）'), '对照原图核实')
    await user.click(screen.getByRole('checkbox', { name: /我已对照原图核对/ }))
    await user.click(screen.getByRole('button', { name: '确认并保存题目' }))
    await screen.findByText('内容已核对并保存；历史版本和来源仍保留。')
    expect(onUnsavedChange).toHaveBeenLastCalledWith(true)

    await user.click(screen.getByRole('tab', { name: '整页阅读' }))
    await user.click(screen.getByRole('button', { name: '保存本页阅读记录' }))
    await screen.findByText('本页阅读记录已保存，历史修订仍保留。')
    expect(onUnsavedChange).toHaveBeenLastCalledWith(false)
  })

  it('preserves reading input and dirty state if content refresh fails after a successful question save', async () => {
    const user = userEvent.setup()
    const onUnsavedChange = vi.fn()
    const existing = { ...emptyContent(), questions: [question] }
    const savedResponse = async () => Response.json({ schema_version: 'swb.api.v1', question_id: 'question-1', revision_id: 'revision-2' })
    const contentResponse = (requestNo: number) => requestNo === 2
      ? Promise.reject(new Error('temporary refresh failure'))
      : Response.json(existing)
    mountContent({ content: existing, onUnsavedChange, postResponse: savedResponse, contentResponse })
    await user.selectOptions(await screen.findByLabelText('正在核对的题目'), 'question-1')
    await user.clear(screen.getByLabelText('图中印刷题面转写（必填）'))
    await user.type(screen.getByLabelText('图中印刷题面转写（必填）'), '已成功保存的题面')
    const readingBasis = screen.getByLabelText('阅读依据（必填）') as HTMLTextAreaElement
    await user.type(readingBasis, '仍未保存的阅读依据')
    await user.type(screen.getByLabelText('本次核对原因（必填）'), '对照原图核实')
    await user.click(screen.getByRole('checkbox', { name: /我已对照原图核对/ }))
    await user.click(screen.getByRole('button', { name: '确认并保存题目' }))

    await screen.findByText('内容已核对并保存；历史版本和来源仍保留。')
    expect((await screen.findByRole('alert')).textContent).toContain('当前输入仍保留')
    expect(screen.getByRole('button', { name: '重试更新' })).toBeTruthy()
    expect((screen.getByLabelText('阅读依据（必填）') as HTMLTextAreaElement).value).toBe('仍未保存的阅读依据')
    expect(onUnsavedChange).toHaveBeenLastCalledWith(true)

    await user.clear(screen.getByLabelText('图中印刷题面转写（必填）'))
    await user.type(screen.getByLabelText('图中印刷题面转写（必填）'), '失败后继续编辑的题面')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    await user.click(screen.getByRole('button', { name: '重试更新' }))
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('失败后继续编辑的题面')
    await user.click(screen.getByRole('button', { name: '重试更新' }))
    await waitFor(() => expect(screen.queryByText(/无法更新题目和来源/)).toBeNull())
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('原印刷题面')
    expect((screen.getByLabelText('阅读依据（必填）') as HTMLTextAreaElement).value).toBe('仍未保存的阅读依据')
    expect(onUnsavedChange).toHaveBeenLastCalledWith(true)
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('locks question editing during a deferred post-save refresh while preserving the page-reading draft', async () => {
    const user = userEvent.setup()
    const onUnsavedChange = vi.fn()
    const existing = { ...emptyContent(), questions: [question] }
    let finishRefresh!: (response: Response) => void
    const pendingRefresh = new Promise<Response>((resolve) => { finishRefresh = resolve })
    const contentResponse = (requestNo: number) => requestNo === 2 ? pendingRefresh : Response.json(existing)
    const savedResponse = async () => Response.json({ schema_version: 'swb.api.v1', question_id: 'question-1', revision_id: 'revision-2' })
    mountContent({ content: existing, onUnsavedChange, postResponse: savedResponse, contentResponse })
    await user.selectOptions(await screen.findByLabelText('正在核对的题目'), 'question-1')
    await user.clear(screen.getByLabelText('图中印刷题面转写（必填）'))
    await user.type(screen.getByLabelText('图中印刷题面转写（必填）'), '已保存的题面')
    const readingBasis = screen.getByLabelText('阅读依据（必填）') as HTMLTextAreaElement
    await user.type(readingBasis, '未保存的整页阅读依据')
    await user.type(screen.getByLabelText('本次核对原因（必填）'), '对照原图核实')
    await user.click(screen.getByRole('checkbox', { name: /我已对照原图核对/ }))
    await user.click(screen.getByRole('button', { name: '确认并保存题目' }))

    await screen.findByText('内容已核对并保存；历史版本和来源仍保留。')
    expect((screen.getByLabelText('正在核对的题目') as HTMLSelectElement).disabled).toBe(true)
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).disabled).toBe(true)
    expect(readingBasis.disabled).toBe(false)
    await user.type(readingBasis, '；还在继续核对')

    const updated = {
      ...existing,
      context: { source_stamp: 'refreshed-source-stamp' },
      questions: [{ ...question, revision_id: 'revision-2', printed_text: '已保存的题面' }],
    }
    await act(async () => finishRefresh(Response.json(updated)))
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('已保存的题面')
    expect(readingBasis.isConnected).toBe(true)
    expect(readingBasis.value).toBe('未保存的整页阅读依据；还在继续核对')
    expect(onUnsavedChange).toHaveBeenLastCalledWith(true)
  })

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
    expect((screen.getByRole('button', { name: '返回原图与进度' }) as HTMLButtonElement).disabled).toBe(true)

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
    await user.click(await screen.findByRole('tab', { name: '整页阅读' }))
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
