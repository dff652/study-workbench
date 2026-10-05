import { useState } from 'react'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SolutionEditor } from './editor'
import { newSolutionQuestion, newSolutionStep, toStructuredSolutionContent } from './model'
import type { SolutionAsset, SolutionContent, SolutionQuestion, SolutionSource, SolutionStep, SolutionWorkspaceResponse, StructuredSolutionContent } from '../../types'

const question: SolutionQuestion = { ...newSolutionQuestion('lecture-1'), steps: [], formulas: [], figures: [] }
const content: SolutionContent = {
  schema_version: 'swb.solution.v1', title: '测试解析', lectures: [{ id: 'lecture-1', title: '第 1 讲' }],
  questions: [question], outputs: { per_question: ['pdf'], per_lecture: [], combined: [] },
}
const workspace: SolutionWorkspaceResponse = {
  schema_version: 'swb.api.v1', material: { id: 'material-1', title: '测试资料' }, writable: true,
  revision: null, initial_content: content, history: [], outputs: [], assets: [], pages: [], questions: [], nodes: [],
}

function contentWithFormulaStep(): StructuredSolutionContent {
  const structured = toStructuredSolutionContent(content)
  structured.questions[0].steps = [{ ...newSolutionStep(), formula: '' }]
  return structured
}

function EditorHarness({ initialContent = contentWithFormulaStep(), assets = workspace.assets, onContentChange }: {
  initialContent?: StructuredSolutionContent
  assets?: SolutionAsset[]
  onContentChange?: (content: StructuredSolutionContent) => void
} = {}) {
  const [currentContent, setCurrentContent] = useState(initialContent)
  return <SolutionEditor
    content={currentContent} workspace={{ ...workspace, assets }} materialId='material-1' csrfToken='csrf-token' canWrite
    onChange={(next) => { onContentChange?.(next); setCurrentContent(next) }} onAssetsChanged={() => undefined} onUnauthorized={() => undefined}
  />
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

describe('SolutionEditor formula preview', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('previews supported expression structure and keeps invalid source text intact', async () => {
    const user = userEvent.setup()
    const requests: Array<{ url: string; init?: RequestInit }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      requests.push({ url: `${url.pathname}${url.search}`, init })
      const body = JSON.parse(String(init?.body)) as { expression: string }
      if (body.expression === '1+') return Response.json({ schema_version: 'swb.api.v1', error: { code: 'invalid_solution', message: '表达式语法不支持。' } }, { status: 400 })
      return Response.json({ schema_version: 'swb.api.v1', formula: ['r', ['t', '('], ['t', '4'], ['t', '×'], ['t', '2'], ['t', '+'], ['f', ['t', '1'], ['t', '2']], ['t', '-'], ['f', ['t', '1'], ['t', '2']], ['t', ')']] })
    }))

    render(<EditorHarness />)
    const formula = screen.getByRole('textbox', { name: '第 1 步公式表达式' })
    await user.type(formula, '4*2+1/2-1/2')
    expect(formula).toBe(document.activeElement)
    const preview = await screen.findByRole('region', { name: '第 1 步公式预览' })
    await waitFor(() => expect(requests).toHaveLength(1))
    await waitFor(() => expect(preview.querySelectorAll('.inline-grid')).toHaveLength(2))
    expect(requests.at(-1)?.url).toBe('/api/v1/solutions/formula-preview/')
    expect(JSON.parse(String(requests.at(-1)?.init?.body))).toEqual({ expression: '4*2+1/2-1/2' })
    expect(new Headers(requests.at(-1)?.init?.headers).get('X-CSRFToken')).toBe('csrf-token')

    await user.clear(formula)
    await user.type(formula, '1+')
    expect(await screen.findByText(/预览失败：表达式语法不支持/)).toBeTruthy()
    expect((formula as HTMLTextAreaElement).value).toBe('1+')
  })

  it('retries original-source derivation with the same key and starts a new key after success or changed evidence', async () => {
    const user = userEvent.setup()
    const sources: SolutionSource[] = [
      { page_id: 'page-1', region: [2, 3, 25, 30] },
      { page_id: 'page-1', region: [31, 32, 50, 55] },
    ]
    const sourceContent = toStructuredSolutionContent({ ...content, questions: [{ ...question, sources }] })
    const sourceWorkspace = {
      ...workspace,
      pages: [{ id: 'page-1', label: '第 1 页', width: 100, height: 100, preview_url: '/page/page-1/preview/0/', detail_url: '/page/page-1/' }],
    }
    const assetsByKey = new Map<string, SolutionAsset>()
    const requests: Array<{ body: Record<string, unknown>; headers: Headers }> = []
    const onAssetsChanged = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname !== '/api/v1/materials/material-1/solutions/source-assets/') throw new Error(`unexpected request: ${url.pathname}`)
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      requests.push({ body, headers: new Headers(init?.headers) })
      const key = String(body.request_key)
      let asset = assetsByKey.get(key)
      if (!asset) {
        asset = {
          id: `asset-${assetsByKey.size + 1}`, kind: body.kind as SolutionAsset['kind'], label: String(body.label), basis: String(body.basis),
          source: body.source as SolutionSource, width: 23, height: 27, url: `/assets/${assetsByKey.size + 1}.png`,
        }
        assetsByKey.set(key, asset)
      }
      if (requests.length === 1) throw new Error('派生结果响应丢失')
      return Response.json({ ...sourceWorkspace, assets: [...assetsByKey.values()] })
    }))

    render(<SolutionEditor
      content={sourceContent} workspace={sourceWorkspace} materialId='material-1' csrfToken='csrf-token' canWrite
      onChange={vi.fn()} onAssetsChanged={onAssetsChanged} onUnauthorized={vi.fn()}
    />)
    await user.selectOptions(screen.getByLabelText('图片类型'), 'source_crop')
    const firstSource = JSON.stringify(['page-1', sources[0].region])
    const secondSource = JSON.stringify(['page-1', sources[1].region])
    await user.selectOptions(screen.getByLabelText('对应原图来源'), firstSource)
    await user.type(screen.getByLabelText('图示名称'), '原图裁切')
    await user.type(screen.getByLabelText('依据'), '保留透明像素')
    await user.click(screen.getByRole('button', { name: '上传素材' }))
    expect((await screen.findByRole('alert')).textContent).toContain('派生结果响应丢失')
    await user.click(screen.getByRole('button', { name: '上传素材' }))
    expect(await screen.findByText(/素材已加入本资料素材库；它没有自动关联步骤/)).toBeTruthy()
    expect(requests).toHaveLength(2)
    expect(requests[1].body.request_key).toBe(requests[0].body.request_key)
    expect(requests[0]).toMatchObject({
      body: { kind: 'source_crop', source: sources[0], label: '原图裁切', basis: '保留透明像素' },
    })
    expect(requests[0].headers.get('X-CSRFToken')).toBe('csrf-token')
    expect(assetsByKey.size).toBe(1)

    await user.selectOptions(screen.getByLabelText('对应原图来源'), secondSource)
    await user.clear(screen.getByLabelText('依据'))
    await user.type(screen.getByLabelText('依据'), '改用第二个区域')
    await user.click(screen.getByRole('button', { name: '上传素材' }))
    expect(requests).toHaveLength(3)
    expect(requests[2].body.request_key).not.toBe(requests[1].body.request_key)
    expect(requests[2].body).toMatchObject({ source: sources[1], basis: '改用第二个区域' })
    expect(await screen.findByText(/素材已加入本资料素材库；它没有自动关联步骤/)).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '上传素材' }))
    expect(requests).toHaveLength(4)
    expect(requests[3].body.request_key).not.toBe(requests[2].body.request_key)
    expect(assetsByKey.size).toBe(3)
    expect(onAssetsChanged).toHaveBeenCalledTimes(3)
  })

  it('keeps step ids, formulas, and figures bound through moves and deletion while discarding late formula responses', async () => {
    const user = userEvent.setup()
    const firstFigure: SolutionStep['figure'] = { asset_id: 'asset-first', role: 'method', caption: '第一步图示', width_mm: 80 }
    const secondFigure: SolutionStep['figure'] = { asset_id: 'asset-second', role: 'answer', caption: '第二步图示', width_mm: 90 }
    const firstStep: SolutionStep = { id: 'step-first', text: '第一步文字', formula: 'x+1', figure: firstFigure, new_page: false }
    const secondStep: SolutionStep = { id: 'step-second', text: '第二步文字', formula: 'x+2', figure: secondFigure, new_page: true }
    const initialContent = toStructuredSolutionContent(content)
    initialContent.questions[0].steps = [firstStep, secondStep]
    const assets: SolutionAsset[] = [
      { id: 'asset-first', kind: 'auxiliary', label: '第一步图示', basis: '第一步', source: null, width: 80, height: 60, url: '/assets/first.png' },
      { id: 'asset-second', kind: 'auxiliary', label: '第二步图示', basis: '第二步', source: null, width: 80, height: 60, url: '/assets/second.png' },
    ]
    const requests: Array<{ expression: string; signal?: AbortSignal | null; resolve: (label: string) => void }> = []
    const onContentChange = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const { expression } = JSON.parse(String(init?.body)) as { expression: string }
      const pending = deferred<Response>()
      requests.push({ expression, signal: init?.signal, resolve: (label) => pending.resolve(Response.json({ schema_version: 'swb.api.v1', formula: ['r', ['t', label]] })) })
      return pending.promise
    }))

    render(<EditorHarness initialContent={initialContent} assets={assets} onContentChange={onContentChange} />)
    await waitFor(() => expect(requests.map((item) => item.expression)).toEqual(expect.arrayContaining(['x+1', 'x+2'])), { timeout: 2500 })
    const lateFirst = requests.find((item) => item.expression === 'x+1')!
    const pendingSecond = requests.find((item) => item.expression === 'x+2')!
    pendingSecond.resolve('第二步预览')
    expect(await screen.findByText('第二步预览')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '第 2 步上移' }))
    expect(onContentChange.mock.lastCall?.[0].questions[0].steps).toEqual([secondStep, firstStep])
    expect((screen.getAllByLabelText('图片素材') as HTMLSelectElement[]).map((select) => select.value)).toEqual(['asset-second', 'asset-first'])

    const movedFormula = screen.getByRole('textbox', { name: '第 1 步公式表达式' })
    const movedPreview = screen.getByRole('region', { name: '第 1 步公式预览' })
    await user.clear(movedFormula)
    await user.type(movedFormula, 'x+3')
    expect(within(movedPreview).queryByText('第二步预览')).toBeNull()
    await waitFor(() => expect(requests.some((item) => item.expression === 'x+3')).toBe(true), { timeout: 2500 })
    requests.find((item) => item.expression === 'x+3')!.resolve('新表达式预览')
    expect(await within(movedPreview).findByText('新表达式预览')).toBeTruthy()

    const removedFormula = screen.getByRole('textbox', { name: '第 2 步公式表达式' })
    const removedStep = removedFormula.closest('fieldset')
    if (!removedStep) throw new Error('step fieldset not found')
    await user.click(within(removedStep).getByRole('button', { name: '删除步骤' }))
    expect(lateFirst.signal?.aborted).toBe(true)
    lateFirst.resolve('迟到的旧表达式预览')
    expect(screen.queryByText('迟到的旧表达式预览')).toBeNull()
    expect(onContentChange.mock.lastCall?.[0].questions[0].steps).toEqual([
      expect.objectContaining({ id: 'step-second', text: '第二步文字', formula: 'x+3', figure: secondFigure, new_page: true }),
    ])
  })

  it('converts only v1 text steps and preserves standalone formulas and figures', () => {
    const figure = { asset_id: 'asset-legacy', role: 'method' as const, caption: '辅助图', width_mm: 80 }
    const legacy: SolutionContent = { ...content, questions: [{ ...question, steps: ['第一步', '第二步'], formulas: ['x+1', 'x+2'], figures: [figure] }] }
    const converted = toStructuredSolutionContent(legacy)
    const steps = converted.questions[0].steps
    expect(converted.schema_version).toBe('swb.solution.v2')
    expect(steps.map((step) => [step.text, step.formula, step.figure?.caption])).toEqual([
      ['第一步', null, undefined], ['第二步', null, undefined],
    ])
    expect(new Set(steps.map((step) => step.id)).size).toBe(steps.length)
    expect(converted.questions[0].alternative_steps).toEqual([])
    expect(converted.questions[0].formulas).toEqual(['x+1', 'x+2'])
    expect(converted.questions[0].figures).toEqual([figure])
    expect(legacy.questions[0].steps).toEqual(['第一步', '第二步'])
    expect(legacy.questions[0].formulas).toEqual(['x+1', 'x+2'])
    expect(legacy.questions[0].figures).toEqual([figure])
  })
})
