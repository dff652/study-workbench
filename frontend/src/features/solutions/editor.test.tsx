import { useState } from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SolutionEditor } from './editor'
import { newSolutionQuestion } from './model'
import type { SolutionAsset, SolutionContent, SolutionSource, SolutionWorkspaceResponse } from '../../types'

const question = { ...newSolutionQuestion('lecture-1'), formulas: [''] }
const content: SolutionContent = {
  schema_version: 'swb.solution.v1', title: '测试解析', lectures: [{ id: 'lecture-1', title: '第 1 讲' }],
  questions: [question], outputs: { per_question: ['pdf'], per_lecture: [], combined: [] },
}
const workspace: SolutionWorkspaceResponse = {
  schema_version: 'swb.api.v1', material: { id: 'material-1', title: '测试资料' }, writable: true,
  revision: null, initial_content: content, history: [], outputs: [], assets: [], pages: [], questions: [], nodes: [],
}

function EditorHarness() {
  const [currentContent, setCurrentContent] = useState(content)
  return <SolutionEditor
    content={currentContent} workspace={workspace} materialId='material-1' csrfToken='csrf-token' canWrite
    onChange={setCurrentContent} onAssetsChanged={() => undefined} onUnauthorized={() => undefined}
  />
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
    const formula = screen.getByRole('textbox', { name: '公式 1' })
    await user.type(formula, '4*2+1/2-1/2')
    const preview = await screen.findByRole('region', { name: '公式 1 预览' })
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
    const sourceContent = { ...content, questions: [{ ...question, sources }] }
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
    await user.selectOptions(screen.getByLabelText('对应原图来源'), '0')
    await user.type(screen.getByLabelText('图示名称'), '原图裁切')
    await user.type(screen.getByLabelText('依据'), '保留透明像素')
    await user.click(screen.getByRole('button', { name: '上传素材' }))
    expect((await screen.findByRole('alert')).textContent).toContain('派生结果响应丢失')
    await user.click(screen.getByRole('button', { name: '上传素材' }))
    expect(await screen.findByText('图示已收存，可在图示列表中选择。')).toBeTruthy()
    expect(requests).toHaveLength(2)
    expect(requests[1].body.request_key).toBe(requests[0].body.request_key)
    expect(requests[0]).toMatchObject({
      body: { kind: 'source_crop', source: sources[0], label: '原图裁切', basis: '保留透明像素' },
    })
    expect(requests[0].headers.get('X-CSRFToken')).toBe('csrf-token')
    expect(assetsByKey.size).toBe(1)

    await user.selectOptions(screen.getByLabelText('对应原图来源'), '1')
    await user.clear(screen.getByLabelText('依据'))
    await user.type(screen.getByLabelText('依据'), '改用第二个区域')
    await user.click(screen.getByRole('button', { name: '上传素材' }))
    expect(requests).toHaveLength(3)
    expect(requests[2].body.request_key).not.toBe(requests[1].body.request_key)
    expect(requests[2].body).toMatchObject({ source: sources[1], basis: '改用第二个区域' })
    expect(await screen.findByText('图示已收存，可在图示列表中选择。')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '上传素材' }))
    expect(requests).toHaveLength(4)
    expect(requests[3].body.request_key).not.toBe(requests[2].body.request_key)
    expect(assetsByKey.size).toBe(3)
    expect(onAssetsChanged).toHaveBeenCalledTimes(3)
  })
})
