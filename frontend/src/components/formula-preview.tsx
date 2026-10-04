import type { ReactNode } from 'react'

export function FormulaReview({ value }: { value: unknown }) {
  if (!Array.isArray(value) || value.length === 0) return <span className='text-sm text-muted-foreground'>未记录</span>
  return <ol className='space-y-2'>{value.map((formula, index) => <li key={index} className='flex flex-wrap items-center gap-2 rounded-md border bg-muted/20 px-3 py-2'>
    <span className='text-xs text-muted-foreground'>公式 {index + 1}</span>
    <FormulaDisplay value={formula} />
  </li>)}</ol>
}

export function FormulaDisplay({ value }: { value: unknown }) {
  const label = formulaText(value)
  return <span className='overflow-x-auto font-serif text-base' aria-label={`公式 ${label}`}>{renderFormula(value)}</span>
}

function formulaText(value: unknown, depth = 0): string {
  if (depth > 24 || !Array.isArray(value) || typeof value[0] !== 'string') return '公式结构无法识别'
  if (value[0] === 't' && typeof value[1] === 'string') return value[1]
  if (value[0] === 'r') return value.slice(1).map((part) => formulaText(part, depth + 1)).join('')
  if (value[0] === 'f' && value.length === 3) return `(${formulaText(value[1], depth + 1)}) / (${formulaText(value[2], depth + 1)})`
  if (value[0] === 'u' && value.length === 3) return `${formulaText(value[1], depth + 1)}^${formulaText(value[2], depth + 1)}`
  return '公式结构无法识别'
}

function renderFormula(value: unknown, depth = 0): ReactNode {
  if (depth > 24 || !Array.isArray(value) || typeof value[0] !== 'string') return formulaText(value)
  if (value[0] === 't' && typeof value[1] === 'string') return value[1]
  if (value[0] === 'r') return <>{value.slice(1).map((part, index) => <span key={index}>{renderFormula(part, depth + 1)}</span>)}</>
  if (value[0] === 'f' && value.length === 3) return <span className='inline-grid align-middle text-center leading-tight'><span className='border-b border-current px-1'>{renderFormula(value[1], depth + 1)}</span><span className='px-1'>{renderFormula(value[2], depth + 1)}</span></span>
  if (value[0] === 'u' && value.length === 3) return <span>{renderFormula(value[1], depth + 1)}<sup>{renderFormula(value[2], depth + 1)}</sup></span>
  return formulaText(value)
}
