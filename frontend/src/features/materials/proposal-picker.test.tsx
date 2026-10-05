import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MaterialPage } from '../../types'
import { ProposalPicker } from './proposal-picker'

const page: MaterialPage = {
  id: 'page-private-id', position: 1, sha256: 'private-hash', width: 100, height: 100,
  page_url: '/page/', preview_url: '/preview/',
}

function packageData() {
  return {
    schema_version: 'swb.skill-import.v1',
    sources: [{ id: 'source-private-id', page_id: page.id, sha256: page.sha256 }],
    records: [{ id: 'record-private-id', kind: 'question', data: {
      printed_text: '题干内容', original_number: '1',
      display_markup: '不可见的题面格式',
      sources: [{ source_id: 'source-private-id', bbox: [10, 12, 70, 80] }],
    } }, { id: 'answer-private-id', kind: 'answer', data: {
      question: 'record-private-id', body: '答案内容', basis: '依据内容', formulas: [{ text: '不可见公式内容' }],
    } }],
    tool_inputs: { preparation: 'private-metadata' },
  }
}

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('ProposalPicker', () => {
  it('shows localized content and original-page evidence without technical metadata', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const view = render(<ProposalPicker pages={[page]} value={null} onChange={onChange} />)
    const input = screen.getByLabelText('选择导入文件（.json）')
    const file = new File(['placeholder'], 'package.json', { type: 'application/json' })
    Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(JSON.stringify(packageData())) })
    await user.upload(input, file)

    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    view.rerender(<ProposalPicker pages={[page]} value={onChange.mock.calls.at(-1)?.[0] ?? null} onChange={onChange} />)
    expect(await screen.findByText('题干内容')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '题目 1' })).toBeTruthy()
    expect(screen.getByAltText('资料页 1 原图').getAttribute('src')).toBe('/preview/')
    expect(screen.getAllByRole('status').filter((item) => item.textContent === '另有内容待核对，已保留。')).toHaveLength(2)
    expect(screen.queryByText(/不可见的题面格式|不可见公式内容/)).toBeNull()
    expect(screen.getByText(/答案内容/)).toBeTruthy()
    expect(screen.getByText('补充信息（待核对）')).toBeTruthy()
    expect(screen.queryByText(/private-id|private-hash|private-metadata|sha256|source_id|swb\./i)).toBeNull()
    expect(screen.queryByText(/10, 12, 70, 80/)).toBeNull()
  })

  it('rejects unknown fields with a safe message and leaves no stale preview', async () => {
    const user = userEvent.setup()
    render(<ProposalPicker pages={[page]} value={null} onChange={vi.fn()} />)
    const input = screen.getByLabelText('选择导入文件（.json）')
    const file = new File(['placeholder'], 'unknown.json', { type: 'application/json' })
    Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(JSON.stringify({ ...packageData(), private_field_name: 'secret' })) })
    await user.upload(input, file)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('包含无法识别的信息，未能安全导入')
    expect(alert.textContent).not.toContain('private_field_name')
    expect(screen.queryByText('题干内容')).toBeNull()
  })
})
