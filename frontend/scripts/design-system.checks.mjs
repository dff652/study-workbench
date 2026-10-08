import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { checkOutputs, generateTokens, validateDesign } from './design-system.mjs'

const source = readFileSync(new URL('../../DESIGN.md', import.meta.url), 'utf8')

test('current design preserves semantic OKLCH, dark values, font list and matching outputs', () => {
  const { tokens } = validateDesign(source)
  const css = generateTokens(tokens)
  assert.match(css, /--primary: oklch\(0.208 0.042 265.755\)/)
  assert.match(css, /\.dark \{[\s\S]*--primary: oklch\(0.929 0.013 255.508\)/)
  assert.match(css, /--font-body: Inter, "Noto Sans SC", system-ui, sans-serif;/)
  assert.match(css, /--workspace-width: 90rem;/)
  checkOutputs(css)
})

test('broken token references are rejected', () => {
  assert.throws(() => validateDesign(source.replace('{colors.primary}', '{colors.missing}')), /broken-ref/)
})

test('upstream low-contrast warnings block the project gate in both themes', () => {
  for (const key of ['primary-foreground', 'dark-primary-foreground']) {
    const color = key.startsWith('dark-') ? '#eeeeee' : '#111111'
    const changed = source.replace(new RegExp(`(^  ${key}: )[^\\n]+`, 'm'), `$1"${color}"`)
    assert.throws(() => validateDesign(changed), /contrast-ratio/)
  }
})

test('stale frontend or standalone generated output is rejected', () => {
  const css = generateTokens(validateDesign(source).tokens)
  for (const target of ['frontend/src/styles/design-tokens.css', 'app/web/static/web/design-tokens.css']) {
    assert.throws(() => checkOutputs(css, path => path === target ? css + '\n' : css), /Stale design tokens/)
  }
})

test('missing theme counterpart and malformed project layout token fail', () => {
  const { tokens } = validateDesign(source)
  delete tokens.colors['dark-primary']
  assert.throws(() => generateTokens(tokens), /Missing dark color primary/)
  const other = validateDesign(source).tokens
  other.spacing.workspace = 'invalid; width:100vw'
  assert.throws(() => generateTokens(other), /Invalid dimension workspace/)
})

test('removing both counterparts of a required semantic color cannot bypass consistency', () => {
  const { tokens } = validateDesign(source)
  delete tokens.colors.popover
  delete tokens.colors['dark-popover']
  assert.throws(() => generateTokens(tokens), /Missing semantic color popover/)
})
