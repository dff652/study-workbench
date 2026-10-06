import { useCallback, useEffect, useRef, useState } from 'react'
import { FormulaDisplay } from './formula-preview'
import { Button } from './ui/button'
import { getErrorMessage, postJson } from '../api'

type FormulaPreview = { expression: string; value: unknown }

const COMMON_FORMULAS = [
  ['分数', '1/2'],
  ['平方', '2^2'],
  ['比值', '2/3'],
] as const

export function KnowledgeFormulaTools({ root, csrfToken }: { root: HTMLElement; csrfToken: string }) {
  const [expression, setExpression] = useState('')
  const [previewResult, setPreviewResult] = useState<FormulaPreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const expressionRef = useRef(expression)
  const requestId = useRef(0)
  const activeRequest = useRef<AbortController | null>(null)
  const debounceTimer = useRef<number | null>(null)

  const clearDebounce = useCallback(() => {
    if (debounceTimer.current !== null) {
      window.clearTimeout(debounceTimer.current)
      debounceTimer.current = null
    }
  }, [])

  const invalidateRequest = useCallback(() => {
    requestId.current += 1
    activeRequest.current?.abort()
    activeRequest.current = null
  }, [])

  const requestPreview = useCallback(async (source: string) => {
    const normalized = source.trim()
    if (!normalized || normalized !== expressionRef.current.trim()) return

    invalidateRequest()
    const currentRequestId = requestId.current
    const controller = new AbortController()
    activeRequest.current = controller
    setBusy(true)
    setPreviewResult(null)
    setError('')

    try {
      const data = await postJson<{ formula: unknown }>(
        '/api/v1/solutions/formula-preview/',
        { expression: normalized },
        csrfToken,
        controller.signal,
      )
      if (!controller.signal.aborted && currentRequestId === requestId.current) {
        setPreviewResult({ expression: normalized, value: data.formula })
        setError('')
      }
    } catch (cause) {
      if (!controller.signal.aborted && currentRequestId === requestId.current) {
        setPreviewResult(null)
        setError(getErrorMessage(cause))
      }
    } finally {
      if (currentRequestId === requestId.current && !controller.signal.aborted) {
        activeRequest.current = null
        setBusy(false)
      }
    }
  }, [csrfToken, invalidateRequest])

  useEffect(() => {
    const normalized = expression.trim()
    if (!normalized) return

    const timer = window.setTimeout(() => {
      if (debounceTimer.current === timer) debounceTimer.current = null
      void requestPreview(normalized)
    }, 400)
    debounceTimer.current = timer
    return () => {
      window.clearTimeout(timer)
      if (debounceTimer.current === timer) debounceTimer.current = null
      invalidateRequest()
    }
  }, [expression, invalidateRequest, requestPreview])

  const changeExpression = (value: string) => {
    if (value === expression) return
    clearDebounce()
    invalidateRequest()
    setBusy(false)
    expressionRef.current = value
    setExpression(value)
    setPreviewResult(null)
    setError('')
  }

  const preview = () => {
    clearDebounce()
    void requestPreview(expression)
  }

  const insert = () => {
    const value = expression.trim()
    if (!previewResult || previewResult.expression !== value || !value) return
    const definition = root.querySelector<HTMLTextAreaElement>('#id_definition')
    const markup = root.querySelector<HTMLTextAreaElement>('#id_display_markup')
    if (!definition || !markup) return

    const definitionLines = definition.value.split('\n')
    const alreadyInDefinition = definitionLines.some((line) => line.trim() === value)
    if (!alreadyInDefinition) {
      const separator = definition.value && !definition.value.endsWith('\n') ? '\n' : ''
      definition.value = `${definition.value}${separator}${value}`
    }

    const mathLine = `[[math:${value}]]`
    const markupLines = (markup.value || definition.value).split('\n')
    const alreadyInMarkup = markupLines.some((line) => line.trim() === mathLine)
    if (!alreadyInMarkup) {
      const plainFormulaIndex = markupLines.findIndex((line) => line.trim() === value)
      if (plainFormulaIndex >= 0) markupLines[plainFormulaIndex] = mathLine
      else markupLines.push(mathLine)
      markup.value = markupLines.join('\n')
    }

    for (const field of [definition, markup]) field.dispatchEvent(new Event('input', { bubbles: true }))
    setError('已加入当前输入；保存后仍需按定义、来源和审核规则核定。')
  }

  const currentFormula = previewResult?.expression === expression.trim() ? previewResult.value : null

  return <div className='space-y-3 rounded-md border p-3'>
    <label className='block text-sm font-medium'>公式辅助<input type='text' className='mt-1 h-10 w-full rounded-md border px-3' value={expression} onChange={(event) => changeExpression(event.target.value)} placeholder='例如 1/2 + 1/3 或 2^3' /></label>
    <div className='flex flex-wrap gap-2' aria-label='常用公式'>{COMMON_FORMULAS.map(([label, value]) => <Button key={label} type='button' variant='ghost' size='sm' onClick={() => changeExpression(value)}>{label}</Button>)}</div>
    <div className='flex flex-wrap items-center gap-3'>
      <Button type='button' size='sm' variant='outline' disabled={!expression.trim()} onClick={preview}>预览公式</Button>
      {busy ? <span role='status' className='text-xs text-muted-foreground'>正在预览公式…</span> : null}
      {currentFormula ? <><FormulaDisplay value={currentFormula} /><Button type='button' size='sm' variant='outline' onClick={insert}>加入定义与排版</Button></> : null}
    </div>
    <p className='text-xs text-muted-foreground'>已有同一公式行时仅补排版标记；新公式会同时追加定义与排版。原始语法可在字段帮助中查看。保存后的文字仍须与定义一致。</p>
    {error ? <p role='status' className='text-sm'>{error}</p> : null}
  </div>
}
