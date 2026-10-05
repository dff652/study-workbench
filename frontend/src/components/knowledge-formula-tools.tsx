import { useState } from 'react'
import { FormulaDisplay } from './formula-preview'
import { Button } from './ui/button'
import { getErrorMessage, postJson } from '../api'

export function KnowledgeFormulaTools({ root, csrfToken }: { root: HTMLElement; csrfToken: string }) {
  const [expression, setExpression] = useState('')
  const [formula, setFormula] = useState<unknown>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const preview = async () => {
    if (busy || !expression.trim()) return
    setBusy(true); setError(''); setFormula(null)
    try { const data = await postJson<{ formula: unknown }>('/api/v1/solutions/formula-preview/', { expression: expression.trim() }, csrfToken); setFormula(data.formula) }
    catch (cause) { setError(getErrorMessage(cause)) }
    finally { setBusy(false) }
  }
  const insert = () => {
    if (!formula) return
    const definition = root.querySelector<HTMLTextAreaElement>('#id_definition')
    const markup = root.querySelector<HTMLTextAreaElement>('#id_display_markup')
    if (!definition || !markup) return
    const value = expression.trim()
    const base = markup.value || definition.value
    const alreadyPresent = definition.value.split('\n').some((line) => line.trim() === value)
    if (alreadyPresent) markup.value = base.split('\n').map((line) => line.trim() === value ? `[[math:${value}]]` : line).join('\n')
    else { definition.value = `${definition.value}${definition.value ? '\n' : ''}${value}`; markup.value = `${base}${base ? '\n' : ''}[[math:${value}]]` }
    for (const field of [definition, markup]) field.dispatchEvent(new Event('input', { bubbles: true }))
    setError('已加入当前输入；保存后仍需按定义、来源和审核规则核定。')
  }
  return <div className='space-y-3 rounded-md border p-3'>
    <label className='block text-sm font-medium'>公式辅助<input type='text' disabled={busy} className='mt-1 h-10 w-full rounded-md border px-3' value={expression} onChange={(event) => { setExpression(event.target.value); setFormula(null) }} placeholder='例如 1/2 + 1/3 或 2^3' /></label>
    <div className='flex flex-wrap items-center gap-3'><Button type='button' size='sm' variant='outline' disabled={busy || !expression.trim()} onClick={() => void preview()}>{busy ? '正在预览…' : '预览公式'}</Button>{formula ? <><FormulaDisplay value={formula} /><Button type='button' size='sm' variant='outline' onClick={insert}>加入定义与排版</Button></> : null}</div>
    <p className='text-xs text-muted-foreground'>已有同一公式行时仅补排版标记；新公式会同时追加定义与排版。原始语法可在字段帮助中查看。保存后的文字仍须与定义一致。</p>
    {error ? <p role='status' className='text-sm'>{error}</p> : null}
  </div>
}
