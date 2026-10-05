import { useEffect, useRef, useState } from 'react'
import { FileJson, Trash2 } from 'lucide-react'
import type { MaterialPage, SkillImport } from '../../types'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { parseProposal, proposalPreview } from './exchange'

export function ProposalPicker({
  pages,
  value,
  onChange,
}: {
  pages: MaterialPage[]
  value: SkillImport | null
  onChange: (proposal: SkillImport | null) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const readGeneration = useRef(0)
  const [fileName, setFileName] = useState('')
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => () => { readGeneration.current += 1 }, [])

  const chooseFile = async (file: File | undefined) => {
    const generation = ++readGeneration.current
    setError('')
    onChange(null)
    if (!file) {
      setFileName('')
      return
    }
    setFileName(file.name)
    if (file.size > 1024 * 1024) {
      setError('交换 JSON 超过 1 MiB，请先缩小内容。')
      return
    }
    setReading(true)
    try {
      const text = await file.text()
      if (generation !== readGeneration.current) return
      onChange(parseProposal(text, pages))
    } catch (readError) {
      if (generation !== readGeneration.current) return
      setError(readError instanceof Error ? readError.message : '无法读取交换 JSON。')
    } finally {
      if (generation === readGeneration.current) setReading(false)
    }
  }

  const clear = () => {
    readGeneration.current += 1
    setFileName('')
    setError('')
    setReading(false)
    onChange(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <Card>
      <CardHeader className='pb-4'>
        <CardTitle className='flex items-center gap-2 text-base'><FileJson className='size-4 text-primary' aria-hidden='true' />可选结构化交换包</CardTitle>
        <CardDescription>创建任务前只在本机预览；创建后保存到家庭服务器，核对确认后进入题库。</CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        <div className='flex flex-wrap items-center gap-3'>
          <input
            ref={inputRef}
            type='file'
            accept='application/json,.json'
            disabled={pages.length === 0 || reading}
            aria-label='选择结构化交换 JSON'
            className='block max-w-full text-sm file:mr-3 file:rounded-md file:border file:bg-background file:px-3 file:py-2 file:text-sm file:font-medium'
            onChange={(event) => void chooseFile(event.currentTarget.files?.[0])}
          />
          {fileName ? <span className='max-w-full truncate text-xs text-muted-foreground' title={fileName}>{fileName}</span> : null}
          {fileName ? <Button type='button' variant='ghost' size='sm' onClick={clear} disabled={reading}><Trash2 className='size-4' aria-hidden='true' />移除此文件</Button> : null}
        </div>
        {pages.length === 0 ? <p className='text-sm text-muted-foreground'>先上传至少一张原图，才能核对交换包明确指定的资料页。</p> : null}
        {reading ? <p role='status' className='text-sm text-muted-foreground'>正在本机读取并检查 JSON…</p> : null}
        {error ? <p role='alert' className='rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900'>{error}</p> : null}
        {value ? (
          <div className='rounded-lg border bg-muted/20 p-4'>
            <div className='flex flex-wrap items-center gap-2'>
              <Badge variant='secondary'>版本已识别</Badge>
              <span className='text-sm font-medium'>{value.records.length} 条内容记录</span>
              <span className='text-sm text-muted-foreground'>{value.sources.length} 个原图来源</span>
            </div>
            <details className='mt-2 text-xs text-muted-foreground'>
              <summary className='cursor-pointer'>高级校验信息</summary>
              <p className='mt-1 leading-5'>每个来源均已按包内指定的资料页 ID 与 SHA-256 精确匹配；不会按图片哈希自动选择页面。</p>
            </details>
            <div className='mt-4 max-h-[34rem] space-y-3 overflow-y-auto pr-1'>
              {value.records.length === 0 ? <p className='text-sm text-muted-foreground'>包内没有待确认的内容记录。</p> : null}
              {value.records.map((record) => {
                const preview = proposalPreview(record, value.records, value, pages)
                return (
                  <article key={record.id} className='rounded-lg border bg-background p-4'>
                    <div className='flex flex-wrap items-center gap-2'>
                      <Badge variant='outline'>{preview.kindLabel}</Badge>
                      <h3 className='font-semibold'>{preview.title}</h3>
                    </div>
                    <p className='mt-2 whitespace-pre-wrap break-words text-sm leading-6'>{preview.text}</p>
                    {preview.sources.length ? <details className='mt-3 border-t pt-3 text-xs text-muted-foreground'>
                      <summary className='cursor-pointer'>来源与原图区域</summary>
                      <ul className='mt-2 space-y-1.5'>
                        {preview.sources.map((source, index) => (
                          <li key={`${source.pagePosition}-${index}`}>资料页 {source.pagePosition} · 原图区域 {source.bbox.join(', ')} px</li>
                        ))}
                      </ul>
                    </details> : null}
                  </article>
                )
              })}
            </div>
            <details className='mt-4 border-t pt-3 text-xs text-muted-foreground'>
              <summary className='cursor-pointer'>交换包中的可选数据</summary>
              <div className='mt-2 flex flex-wrap gap-2'>
              {value.packet !== undefined ? <Badge variant='outline'>含打印包</Badge> : null}
              {value.ledger !== undefined ? <Badge variant='outline'>含账本</Badge> : null}
              {value.catalog !== undefined ? <Badge variant='outline'>含目录</Badge> : null}
              {value.tool_inputs !== undefined ? <Badge variant='outline'>含工具输入元数据：{Object.keys(value.tool_inputs).join('、') || '空对象'}</Badge> : null}
              </div>
            </details>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
