import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SubjectEditor } from './subjects'

const initial = { subject: 'unknown', version: 0 }
function json(value: object, status = 200) { return Response.json({ schema_version: 'swb.api.v1', ...value }, { status }) }
const props = { materialId: 'material-1', csrfToken: 'csrf', writable: true, onUnauthorized: vi.fn() }
async function edit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText(/^资料学科 ·/))
  await waitFor(() => expect((screen.getByRole('combobox', { name: '学校学科' }) as HTMLSelectElement).disabled).toBe(false))
  await user.selectOptions(screen.getByRole('combobox', { name: '学校学科' }), 'english')
  await user.type(screen.getByRole('textbox', { name: '分类依据' }), '按封面核对英语课程')
}

describe('manual school subject classification', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('keeps input and reuses the request key when a successful response is lost', async () => {
    const user = userEvent.setup(); const writes: Array<Record<string, unknown>> = []; const saved = vi.fn(); const dirty = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        writes.push(JSON.parse(String(init.body)))
        if (writes.length === 1) throw new Error('保存回执暂时无法读取')
        return json({ material: { classification: { subject: 'english', version: 1 } } })
      }
      return json({ classification: writes.length > 1 ? { subject: 'english', version: 1 } : initial, history: [], history_next_before: null })
    }))
    render(<SubjectEditor {...props} onSaved={saved} onDirtyChange={dirty} />); await edit(user)
    await user.click(screen.getByRole('button', { name: '保存分类新版本' })); await screen.findByRole('alert')
    expect((screen.getByRole('textbox', { name: '分类依据' }) as HTMLInputElement).value).toBe('按封面核对英语课程')
    await user.click(screen.getByRole('button', { name: '保存分类新版本' })); await screen.findByText(/学科分类已保存为第 1 版/)
    expect(writes[0].request_key).toBe(writes[1].request_key); expect(saved).toHaveBeenCalledTimes(1)
    expect(dirty).toHaveBeenLastCalledWith(false)
  })

  it('preserves its selection on a stale version and appends only after explicit comparison', async () => {
    const user = userEvent.setup(); const writes: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        writes.push(JSON.parse(String(init.body)))
        if (writes.length === 1) return json({ error: { code: 'stale_subject', message: '学科已在另一窗口更新' } }, 409)
        return json({ material: { classification: { subject: 'english', version: 2 } } })
      }
      return json({ classification: writes.length ? { subject: 'mathematics', version: 1 } : initial, history: [], history_next_before: null })
    }))
    render(<SubjectEditor {...props} />); await edit(user)
    await user.click(screen.getByRole('button', { name: '保存分类新版本' })); await screen.findByText(/另一窗口当前分类/)
    expect((screen.getByRole('combobox', { name: '学校学科' }) as HTMLSelectElement).value).toBe('english')
    expect((screen.getByRole('button', { name: '保存分类新版本' }) as HTMLButtonElement).disabled).toBe(true)
    await user.click(screen.getByRole('button', { name: '已比较，保留本页选择' })); await user.click(screen.getByRole('button', { name: '保存分类新版本' }))
    await screen.findByText(/学科分类已保存为第 2 版/)
    expect(writes[1]).toMatchObject({ expected_version: 1, subject: 'english', reason: '按封面核对英语课程' })
  })

  it('ignores a save callback after its material work area was unmounted', async () => {
    const user = userEvent.setup(); let release: ((response: Response) => void) | undefined
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST'
      ? new Promise<Response>((resolve) => { release = resolve })
      : json({ classification: initial, history: [], history_next_before: null })))
    const oldSaved = vi.fn(); const old = render(<SubjectEditor {...props} onSaved={oldSaved} />); await edit(user)
    await user.click(screen.getByRole('button', { name: '保存分类新版本' })); old.unmount()
    render(<SubjectEditor {...props} materialId='material-2' />); await edit(user)
    await act(async () => release?.(json({ material: { classification: { subject: 'english', version: 1 } } })))
    expect(oldSaved).not.toHaveBeenCalled()
    expect((screen.getByRole('textbox', { name: '分类依据' }) as HTMLInputElement).value).toBe('按封面核对英语课程')
  })

  it('compares a replayed save receipt with a newer classification without losing the choice', async () => {
    const user = userEvent.setup(); let written = false
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        written = true
        return json({ saved_classification: { subject: 'english', version: 1 }, material: { classification: { subject: 'physics', version: 2 } } })
      }
      return json({ classification: written ? { subject: 'physics', version: 2 } : initial, history: [], history_next_before: null })
    }))
    render(<SubjectEditor {...props} />); await edit(user)
    await user.click(screen.getByRole('button', { name: '保存分类新版本' }))
    expect(await screen.findByText(/学科分类已保存为第 1 版/)).toBeTruthy()
    expect(await screen.findByText(/另一窗口当前分类：物理，第 2 版/)).toBeTruthy()
    expect((screen.getByRole('combobox', { name: '学校学科' }) as HTMLSelectElement).value).toBe('english')
    expect((screen.getByRole('textbox', { name: '分类依据' }) as HTMLInputElement).value).toBe('按封面核对英语课程')
    expect((screen.getByRole('button', { name: '保存分类新版本' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
