import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { KnowledgeFormulaTools } from './knowledge-formula-tools'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

const formulaResponse = (label: string) => Response.json({ schema_version: 'swb.api.v1', formula: ['t', label] })

afterEach(() => { cleanup(); document.querySelector('#synthetic-root')?.remove(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('previews bounded math and inserts the same text into definition and markup without replacing the definition', async () => {
  const root = document.createElement('div'); root.id = 'synthetic-root'
  root.innerHTML = '<textarea id="id_definition">分数相加\n1/2 + 1/3</textarea><textarea id="id_display_markup"></textarea>'
  document.body.append(root)
  const changed = vi.fn(); root.addEventListener('input', changed)
  const fetchMock = vi.fn(async () => Response.json({ schema_version: 'swb.api.v1', formula: ['r', ['t', '('], ['f', ['t', '1'], ['t', '2']], ['t', '+'], ['f', ['t', '1'], ['t', '3']], ['t', ')']] }))
  vi.stubGlobal('fetch', fetchMock)
  render(<KnowledgeFormulaTools root={root} csrfToken='synthetic-csrf' />)
  fireEvent.change(screen.getByRole('textbox', { name: '公式辅助' }), { target: { value: '1/2 + 1/3' } })
  fireEvent.click(screen.getByRole('button', { name: '预览公式' }))
  fireEvent.click(await screen.findByRole('button', { name: '加入定义与排版' }))
  expect((root.querySelector('#id_definition') as HTMLTextAreaElement).value).toBe('分数相加\n1/2 + 1/3')
  expect((root.querySelector('#id_display_markup') as HTMLTextAreaElement).value).toBe('分数相加\n[[math:1/2 + 1/3]]')
  expect(changed).toHaveBeenCalledTimes(2)
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('does not offer insertion after the parser rejects a formula', async () => {
  const root = document.createElement('div')
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: { message: '公式结构无效' } }, { status:400 })))
  render(<KnowledgeFormulaTools root={root} csrfToken='synthetic-csrf' />)
  fireEvent.change(screen.getByRole('textbox', { name:'公式辅助' }), { target:{value:'bad('} })
  fireEvent.click(screen.getByRole('button', { name:'预览公式' }))
  expect(await screen.findByText('公式结构无效')).toBeTruthy()
  expect((screen.getByRole('textbox', { name:'公式辅助' }) as HTMLInputElement).value).toBe('bad(')
  expect(screen.queryByRole('button', { name:'加入定义与排版' })).toBeNull()
})

it('keeps editing enabled and ignores an old preview even if fetch resolves after cancellation', async () => {
  vi.useFakeTimers()
  const requests: Array<{ signal?: AbortSignal; body: { expression: string }; reply: ReturnType<typeof deferred<Response>> }> = []
  vi.stubGlobal('fetch', vi.fn((_: RequestInfo | URL, init?: RequestInit) => {
    const reply = deferred<Response>()
    requests.push({ signal: init?.signal as AbortSignal | undefined,
      body: JSON.parse(String(init?.body)) as { expression: string }, reply })
    return reply.promise
  }))
  render(<KnowledgeFormulaTools root={document.createElement('div')} csrfToken='synthetic-csrf' />)
  const input = screen.getByRole('textbox', { name: '公式辅助' }) as HTMLInputElement

  fireEvent.change(input, { target: { value: '1/2' } })
  await act(async () => { await vi.advanceTimersByTimeAsync(400) })
  expect(requests).toHaveLength(1)
  expect(input.disabled).toBe(false)

  fireEvent.change(input, { target: { value: '2^2' } })
  expect(requests[0].signal?.aborted).toBe(true)
  expect(input.value).toBe('2^2')
  await act(async () => { await vi.advanceTimersByTimeAsync(400) })
  expect(requests).toHaveLength(2)
  expect(requests[1].body.expression).toBe('2^2')

  await act(async () => { requests[1].reply.resolve(formulaResponse('current')); await Promise.resolve() })
  expect(screen.getByLabelText('公式 current')).toBeTruthy()
  await act(async () => { requests[0].reply.resolve(formulaResponse('stale')); await Promise.resolve() })
  expect(screen.getByLabelText('公式 current')).toBeTruthy()
  expect(screen.queryByLabelText('公式 stale')).toBeNull()
})

it('serializes manual and automatic previews and aborts the superseded request', async () => {
  vi.useFakeTimers()
  const requests: Array<{ signal?: AbortSignal; reply: ReturnType<typeof deferred<Response>> }> = []
  vi.stubGlobal('fetch', vi.fn((_: RequestInfo | URL, init?: RequestInit) => {
    const reply = deferred<Response>()
    requests.push({ signal: init?.signal as AbortSignal | undefined, reply })
    return reply.promise
  }))
  render(<KnowledgeFormulaTools root={document.createElement('div')} csrfToken='synthetic-csrf' />)
  const input = screen.getByRole('textbox', { name: '公式辅助' })
  fireEvent.change(input, { target: { value: '2/3' } })
  fireEvent.click(screen.getByRole('button', { name: '预览公式' }))
  expect(requests).toHaveLength(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(400) })
  expect(requests).toHaveLength(1)

  fireEvent.change(input, { target: { value: '1/2' } })
  await act(async () => { await vi.advanceTimersByTimeAsync(400) })
  expect(requests).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: '预览公式' }))
  expect(requests[1].signal?.aborted).toBe(true)
  expect(requests).toHaveLength(3)

  await act(async () => { requests[2].reply.resolve(formulaResponse('manual')); await Promise.resolve() })
  await act(async () => { requests[1].reply.resolve(formulaResponse('automatic')); await Promise.resolve() })
  expect(screen.getByLabelText('公式 manual')).toBeTruthy()
  expect(screen.queryByLabelText('公式 automatic')).toBeNull()
})

it('aborts pending preview on unmount and ignores a late response', async () => {
  vi.useFakeTimers()
  const reply = deferred<Response>()
  let signal: AbortSignal | undefined
  vi.stubGlobal('fetch', vi.fn((_: RequestInfo | URL, init?: RequestInit) => {
    signal = init?.signal as AbortSignal | undefined
    return reply.promise
  }))
  const { unmount } = render(<KnowledgeFormulaTools root={document.createElement('div')} csrfToken='synthetic-csrf' />)
  fireEvent.change(screen.getByRole('textbox', { name: '公式辅助' }), { target: { value: '1/2' } })
  await act(async () => { await vi.advanceTimersByTimeAsync(400) })
  unmount()
  expect(signal?.aborted).toBe(true)
  await act(async () => { reply.resolve(formulaResponse('late')); await Promise.resolve() })
})

it('uses supported ratio syntax and inserts missing markup without duplicating either field', async () => {
  const root = document.createElement('div')
  root.innerHTML = '<textarea id="id_definition">比值说明\n2/3</textarea><textarea id="id_display_markup">==比例关系==</textarea>'
  vi.stubGlobal('fetch', vi.fn(async () => formulaResponse('2/3')))
  render(<KnowledgeFormulaTools root={root} csrfToken='synthetic-csrf' />)
  fireEvent.click(screen.getByRole('button', { name: '比值' }))
  fireEvent.click(screen.getByRole('button', { name: '预览公式' }))
  fireEvent.click(await screen.findByRole('button', { name: '加入定义与排版' }))
  fireEvent.click(screen.getByRole('button', { name: '加入定义与排版' }))
  expect((root.querySelector('#id_definition') as HTMLTextAreaElement).value).toBe('比值说明\n2/3')
  expect((root.querySelector('#id_display_markup') as HTMLTextAreaElement).value).toBe('==比例关系==\n[[math:2/3]]')
})

it('sends every common preset using the formula parser expression syntax', async () => {
  const expressions: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (_: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { expression: string }
    expressions.push(body.expression)
    return formulaResponse(body.expression)
  }))
  render(<KnowledgeFormulaTools root={document.createElement('div')} csrfToken='synthetic-csrf' />)

  for (const [label, expression] of [['分数', '1/2'], ['平方', '2^2'], ['比值', '2/3']]) {
    fireEvent.click(screen.getByRole('button', { name: label }))
    fireEvent.click(screen.getByRole('button', { name: '预览公式' }))
    await screen.findByLabelText(`公式 ${expression}`)
  }

  expect(expressions).toEqual(['1/2', '2^2', '2/3'])
})

it('supports keyboard access to common formula presets', async () => {
  const user = userEvent.setup()
  render(<KnowledgeFormulaTools root={document.createElement('div')} csrfToken='synthetic-csrf' />)
  const input = screen.getByRole('textbox', { name: '公式辅助' })
  await user.click(input)
  await user.keyboard('{Tab}{Enter}')
  expect((input as HTMLInputElement).value).toBe('1/2')
})
