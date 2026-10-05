import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SolutionsLauncher } from './launcher'

const materials = [
  { id: 'material-1', title: '一次函数练习', page_count: 2, created_at: '2026-10-05T00:00:00Z', material_url: '/materials/1/', prepare_url: '/prepare/1/' },
  { id: 'material-2', title: '几何证明长标题测试资料', page_count: 12, created_at: '2026-10-05T00:00:00Z', material_url: '/materials/2/', prepare_url: '/prepare/2/' },
]

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('SolutionsLauncher', () => {
  it('keeps search, selection, direct actions, and server pagination available', async () => {
    const user = userEvent.setup()
    const calls: URL[] = []
    const onOpen = vi.fn()
    const onPrepareDocuments = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      calls.push(url)
      const page = Number(url.searchParams.get('page'))
      const query = url.searchParams.get('q') || ''
      return Response.json({ schema_version: 'swb.api.v1', items: query ? [materials[1]] : materials, total: 35, page, page_size: 20, has_next: page === 1 })
    }))

    render(<SolutionsLauncher householdId='home-1' onOpen={onOpen} onPrepareDocuments={onPrepareDocuments} onMaterials={vi.fn()} onUnauthorized={vi.fn()} />)
    const row = (await screen.findByRole('heading', { name: materials[1].title })).closest('li')!
    expect(screen.queryByRole('combobox', { name: '选择资料' })).toBeNull()
    await user.click(within(row).getByRole('button', { name: '整理家长解析' }))
    await user.click(within(row).getByRole('button', { name: '制作整套五册' }))
    expect(onOpen).toHaveBeenCalledWith('material-2')
    expect(onPrepareDocuments).toHaveBeenCalledWith('material-2')

    await user.type(screen.getByPlaceholderText('输入资料或文档名称'), '几何')
    await user.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(calls.some((url) => url.searchParams.get('q') === '几何' && url.searchParams.get('page') === '1')).toBe(true))
    await user.click(await screen.findByRole('button', { name: '下一页' }))
    await waitFor(() => expect(calls.some((url) => url.searchParams.get('q') === '几何' && url.searchParams.get('page') === '2')).toBe(true))
  })

  it('explains read-only access without showing the preparation action', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ schema_version: 'swb.api.v1', items: [materials[0]], total: 1, page: 1, page_size: 20, has_next: false })))
    render(<SolutionsLauncher householdId='home-1' onOpen={vi.fn()} onMaterials={vi.fn()} onUnauthorized={vi.fn()} />)
    expect(await screen.findByText('当前成员可查看讲解文档；制作练习册由家庭所有者或审核成员操作。')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '制作整套五册' })).toBeNull()
  })
})
