import { useEffect, useRef, useState } from 'react'
import { FileText, Trash2 } from 'lucide-react'
import type { MaterialPage, SkillImport } from '../../types'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { ImageBoxPicker } from '../content/image-box-picker'
import { parseProposal, ProposalError, proposalPreview } from './exchange'

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
      setError('导入文件超过 1 MiB，请精简文件后重试。')
      return
    }
    setReading(true)
    try {
      const text = await file.text()
      if (generation !== readGeneration.current) return
      onChange(parseProposal(text, pages))
    } catch (readError) {
      if (generation !== readGeneration.current) return
      setError(readError instanceof ProposalError ? readError.message : '无法读取导入文件，请重新选择后重试。')
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
        <CardTitle className='flex items-center gap-2 text-base'><FileText className='size-4 text-primary' aria-hidden='true' />导入资料内容</CardTitle>
        <CardDescription>创建任务前在本机预览。创建后才保存到家庭；逐项核对并确认后才进入题库。</CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        <div className='flex flex-wrap items-center gap-3'>
          <input
            ref={inputRef}
            type='file'
            accept='application/json,.json'
            disabled={pages.length === 0 || reading}
            aria-label='选择导入文件（.json）'
            className='block max-w-full text-sm file:mr-3 file:rounded-md file:border file:bg-background file:px-3 file:py-2 file:text-sm file:font-medium'
            onChange={(event) => void chooseFile(event.currentTarget.files?.[0])}
          />
          {fileName ? <span className='max-w-full truncate text-xs text-muted-foreground' title={fileName}>{fileName}</span> : null}
          {fileName ? <Button type='button' variant='ghost' size='sm' onClick={clear} disabled={reading}><Trash2 className='size-4' aria-hidden='true' />移除此文件</Button> : null}
        </div>
        {pages.length === 0 ? <p className='text-sm text-muted-foreground'>先上传至少一张原图，才能核对导入内容的来源页。</p> : null}
        {reading ? <p role='status' className='text-sm text-muted-foreground'>正在读取并核对文件…</p> : null}
        {error ? <p role='alert' className='rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900'>{error}</p> : null}
        {value ? (
          <div className='rounded-lg border bg-muted/20 p-4'>
            <div className='flex flex-wrap items-center gap-2'>
              <Badge variant='secondary'>文件已读取</Badge>
              <span className='text-sm font-medium'>{value.records.length} 条内容记录</span>
              <span className='text-sm text-muted-foreground'>{value.sources.length} 个原图来源</span>
            </div>
            <p className='mt-2 text-xs text-muted-foreground'>每个来源都必须对应当前资料中的原图页；系统不会替你猜测来源。</p>
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
                    {preview.hasAdditionalContent ? <p role='status' className='mt-2 text-sm text-amber-900'>另有内容待核对，已保留。</p> : null}
                    {preview.sources.length ? <ul className='mt-3 space-y-3 border-t pt-3'>
                      {preview.sources.map((source, index) => {
                        const page = pages.find((candidate) => candidate.position === source.pagePosition)
                        return <li key={`${source.pagePosition}-${index}`} className='space-y-1'>
                          <p className='text-xs text-muted-foreground'>资料页 {source.pagePosition} · 原图来源区域 {index + 1}</p>
                          {page ? <ImageBoxPicker page={page} boxes={[{ bbox: source.bbox, label: `来源区域 ${index + 1}` }]} onAdd={() => undefined} disabled /> : <p className='text-sm text-amber-900'>找不到对应的原图页，请重新核对来源。</p>}
                        </li>
                      })}
                    </ul> : null}
                  </article>
                )
              })}
            </div>
            {value.packet !== undefined || value.ledger !== undefined || value.catalog !== undefined || value.tool_inputs !== undefined ? <div className='mt-4 border-t pt-3 text-xs text-muted-foreground'>
              <p className='font-medium'>文件还包含其他已保留内容</p>
              <div className='mt-2 flex flex-wrap gap-2'>
                {value.packet !== undefined ? <Badge variant='outline'>打印内容</Badge> : null}
                {value.ledger !== undefined ? <Badge variant='outline'>历史记录</Badge> : null}
                {value.catalog !== undefined ? <Badge variant='outline'>内容目录</Badge> : null}
                {value.tool_inputs !== undefined ? <Badge variant='outline'>补充信息（待核对）</Badge> : null}
              </div>
            </div> : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
