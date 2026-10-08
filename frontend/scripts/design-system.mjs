import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { lint } from '@google/design.md/linter'
import { parseDocument } from 'yaml'

const root = fileURLToPath(new URL('../../', import.meta.url))
export const outputPaths = [
  'frontend/src/styles/design-tokens.css',
  'app/web/static/web/design-tokens.css',
]

// Upstream lint does not fail on contrast warnings. Treat those as errors here.
export function validateDesign(content) {
  const report = lint(content)
  const blockers = report.findings.filter(finding =>
    finding.severity === 'error' || finding.rule === 'contrast-ratio')
  if (blockers.length) {
    throw new Error(blockers.map(finding => `${finding.rule}: ${finding.path || ''} ${finding.message}`).join('\n'))
  }
  const front = content.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)
  if (!front) throw new Error('DESIGN.md must start with YAML design tokens')
  const document = parseDocument(front[1], { uniqueKeys: true })
  if (document.errors.length) throw new Error(document.errors.map(error => error.message).join('\n'))
  return { tokens: document.toJS(), report }
}

const sizes = { page: 'page', section: 'section', body: 'body', small: 'small', metric: 'metric' }
const spaces = { unit: '1', compact: '2', field: '3', panel: '4', section: '6', page: '8' }
const widths = { workspace: 'workspace-width', settings: 'settings-width', reading: 'reading-width' }

function dimension(value, name) {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?(?:px|rem|em)$/.test(value)) {
    throw new Error(`Invalid dimension ${name}`)
  }
  return value
}

export function generateTokens(tokens) {
  if (!tokens.colors || !tokens.typography || !tokens.spacing || !tokens.rounded) {
    throw new Error('Missing required design token group')
  }
  const light = [], dark = []
  for (const [name, value] of Object.entries(tokens.colors)) {
    if (!/^[a-z][a-z0-9-]*$/.test(name) || typeof value !== 'string' || /[;{}\n\r]/.test(value)) {
      throw new Error(`Invalid color token ${name}`)
    }
    // Preserve source CSS colors, including OKLCH and alpha; no lossy export round trip.
    const isDark = name.startsWith('dark-')
    const semantic = isDark ? name.slice(5) : name
    ;(isDark ? dark : light).push(`  --${semantic}: ${value};`)
  }
  const names = Object.keys(tokens.colors)
  for (const name of ['background', 'foreground', 'card', 'card-foreground', 'popover', 'popover-foreground',
    'primary', 'primary-foreground', 'secondary', 'secondary-foreground', 'muted', 'muted-foreground',
    'accent', 'accent-foreground', 'destructive', 'destructive-foreground', 'border', 'input', 'ring',
    'chart-1', 'chart-2', 'chart-3', 'chart-4', 'chart-5',
    ...['success', 'warning', 'danger'].flatMap(state =>
      [`status-${state}`, `status-${state}-foreground`, `status-${state}-border`])]) {
    if (!names.includes(name)) throw new Error(`Missing semantic color ${name}`)
  }
  for (const name of names.filter(name => !name.startsWith('dark-'))) {
    if (!names.includes(`dark-${name}`)) throw new Error(`Missing dark color ${name}`)
  }
  for (const name of names.filter(name => name.startsWith('dark-'))) {
    if (!names.includes(name.slice(5))) throw new Error(`Missing light color ${name}`)
  }
  for (const [key, name] of Object.entries(sizes)) {
    const type = tokens.typography[key]
    light.push(`  --type-${name}: ${dimension(type?.fontSize, key)};`)
    if (!/^\d+(?:\.\d+)?$/.test(String(type.lineHeight)) || Number(type.lineHeight) < 1) {
      throw new Error(`Invalid line height ${key}`)
    }
    if (!Number.isInteger(type.fontWeight) || type.fontWeight < 100 || type.fontWeight > 900) {
      throw new Error(`Invalid font weight ${key}`)
    }
    if (type.fontFamily !== tokens.typography.body.fontFamily) {
      throw new Error(`Typography ${key} must use the shared reading font family`)
    }
    light.push(`  --line-${name}: ${type.lineHeight};`, `  --weight-${name}: ${type.fontWeight};`)
  }
  const body = tokens.typography.body
  if (!/^(?:\d+(?:\.\d+)?)$/.test(String(body.lineHeight)) || Number(body.lineHeight) < 1.4) {
    throw new Error('Body line height must be at least 1.4')
  }
  if (typeof body.fontFamily !== 'string' || /[;{}\n\r]/.test(body.fontFamily)) {
    throw new Error('Invalid body font family')
  }
  light.push(`  --font-body: ${body.fontFamily};`)
  for (const [key, name] of Object.entries(spaces)) {
    light.push(`  --space-${name}: ${dimension(tokens.spacing[key], key)};`)
  }
  for (const [key, name] of Object.entries(widths)) {
    light.push(`  --${name}: ${dimension(tokens.spacing[key], key)};`)
  }
  light.push(`  --radius: ${dimension(tokens.rounded.control, 'rounded.control')};`)
  return `/* Generated from DESIGN.md by npm run design:generate. Do not edit. */\n:root {\n${light.join('\n')}\n}\n\n.dark {\n${dark.join('\n')}\n}\n`
}

export function checkOutputs(css, read = path => readFileSync(resolve(root, path), 'utf8')) {
  for (const path of outputPaths) {
    if (read(path) !== css) throw new Error(`Stale design tokens: ${path}; run npm run design:generate`)
  }
}

export function run(mode) {
  if (!['check', 'generate'].includes(mode)) throw new Error('Expected check or generate')
  const { tokens, report } = validateDesign(readFileSync(resolve(root, 'DESIGN.md'), 'utf8'))
  const css = generateTokens(tokens)
  const warnings = report.findings.filter(finding => finding.severity === 'warning')
  // Palette-only colors (charts, focus, borders) are intentionally not text pairs.
  const unexpected = warnings.filter(finding => finding.rule !== 'orphaned-tokens')
  if (unexpected.length) throw new Error(JSON.stringify(unexpected, null, 2))
  if (mode === 'generate') {
    for (const path of outputPaths) writeFileSync(resolve(root, path), css)
  } else {
    checkOutputs(css)
  }
  console.log(`Design ${mode} passed; ${warnings.length} palette-only token warnings; browser checks still required.`)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { run(process.argv[2] || 'check') }
  catch (error) { console.error(error.message); process.exitCode = 1 }
}
