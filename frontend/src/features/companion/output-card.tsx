import { sameOriginHref } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { Disclosure } from '../../components/disclosure'
import { outputIsProcessing } from '../solutions/model'
import type { CompanionOutput } from './types'
import { PdfPreview } from '../../components/pdf-preview'

export function OutputCard<O extends CompanionOutput>({ checkNames, output, expanded, onToggleExpanded, checks, writable, onCheckChange, onAction }: {
  output: O
  checkNames: Array<[keyof O['checks'] & string, string]>
  expanded: boolean
  onToggleExpanded: () => void
  checks: O['checks']
  writable: boolean
  onCheckChange: (name: keyof O['checks'], patch: Partial<CompanionOutput['checks'][string]>) => void
  onAction: (action: 'cancel' | 'retry' | 'check', checks?: O['checks']) => void
}) {
  const allNotesPresent = Object.values(checks).every((check) => check.status === 'not_tested' || Boolean(check.notes.trim()))
  return <article className='rounded-lg border'>
    <header className='flex flex-wrap items-start justify-between gap-3 border-b p-3'>
      <div><h3 className='font-semibold'>{output.state_label} · 版本 {output.revision_version}</h3><p className='mt-1 text-sm text-muted-foreground'>{output.message || `创建于 ${output.created_at}`}</p></div>
      <div className='flex flex-wrap gap-2'>
        <Button type='button' size='sm' variant='outline' onClick={onToggleExpanded}>{expanded ? '收起输出' : '查看输出'}</Button>
        {writable && ['queued', 'running'].includes(output.state) ? <Button type='button' size='sm' variant='outline' onClick={() => onAction('cancel')}>取消生成</Button> : null}
        {writable && output.state === 'failed' ? <Button type='button' size='sm' variant='outline' onClick={() => onAction('retry')}>重试生成</Button> : null}
      </div>
    </header>
    {expanded ? <div className='space-y-4 p-3'>
      {output.state === 'queued' || output.state === 'running' ? <p role='status' className='text-sm text-muted-foreground'>文档仍在后台生成；本页会每 3 秒读取一次状态。离开页面后轮询将停止。</p> : null}
      {output.documents.map((document) => <section key={document.id} className='space-y-3 rounded-md border p-3'>
        <div className='flex flex-wrap items-center justify-between gap-2'><div><h4 className='font-medium'>{document.title}</h4><p className='text-xs text-muted-foreground'>{organizationLabel(document.organization)} · {document.page_count} 页</p></div>
          {document.docx_url ? <a className='rounded-md border px-3 py-2 text-sm font-medium underline-offset-4 hover:bg-muted hover:underline' href={safeLink(document.docx_url) || undefined} download>下载 Word</a> : null}</div>
        {document.pdf_url ? <PdfPreview title={document.title} src={document.pdf_url} /> : null}
        {document.previews.length ? <div className='grid gap-2 sm:grid-cols-2 lg:grid-cols-3'>{document.previews.map((preview, index) => <figure key={`${preview}:${index}`} className='overflow-hidden rounded-md border'><img src={safeLink(preview) || undefined} alt={`${document.title} 第 ${index + 1} 页预览`} className='h-auto w-full' loading='lazy' /><figcaption className='px-2 py-1 text-xs text-muted-foreground'>第 {index + 1} 页</figcaption></figure>)}</div> : null}
      </section>)}
      {output.documents.length === 0 && !outputIsProcessing(output.state) ? <p className='text-sm text-muted-foreground'>当前输出没有可预览的文档。</p> : null}
      {output.zip_url ? <a className='inline-flex rounded-md border px-3 py-2 text-sm font-medium underline-offset-4 hover:bg-muted hover:underline' href={safeLink(output.zip_url) || undefined} download>下载全部 ZIP</a> : null}
      {writable && output.state === 'output_check' ? <Disclosure title='逐项检查输出' description='五项检查独立记录；Word 的 Windows 与 macOS 实机检查保持“未测试”，除非确实打开验证。' className='border-primary/30 bg-primary/[0.03]'>
        <div className='grid gap-3 lg:grid-cols-2'>{checkNames.map(([name, label]) => <div key={name} className='rounded-md border bg-background p-3'>
          <label className='text-sm font-medium'>{label}<select className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm' value={checks[name].status} onChange={(event) => onCheckChange(name, { status: event.target.value as typeof checks[typeof name]['status'] })}><option value='not_tested'>未测试</option><option value='pass'>通过</option><option value='fail'>未通过</option></select></label>
          <label className='mt-2 block text-xs font-medium'>检查依据或备注<textarea className='mt-1 min-h-16 w-full rounded-md border bg-background px-3 py-2 text-sm' maxLength={2000} value={checks[name].notes} onChange={(event) => onCheckChange(name, { notes: event.target.value })} /></label>
        </div>)}</div>
        <Button type='button' disabled={!allNotesPresent} onClick={() => onAction('check', checks)}>保存检查记录</Button>
        {!allNotesPresent ? <p className='text-xs text-amber-900'>标为“通过”或“未通过”时请填写检查依据；“未测试”可以保留空备注。</p> : null}
      </Disclosure> : null}
    </div> : null}
  </article>
}

function organizationLabel(value: string) {
  if (value === 'inventory') return '知识点目录'
  if (value === 'per_knowledge') return '逐知识点'
  if (value === 'per_question') return '逐题'
  if (value === 'per_lecture') return '按讲次'
  return '合并'
}

function safeLink(value: string | null) {
  return sameOriginHref(value)
}
