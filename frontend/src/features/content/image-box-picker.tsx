import { useLayoutEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import { sameOriginHref } from '../../components/shared'
import type { MaterialPage } from '../../types'

export type ImageBox = {
  bbox: [number, number, number, number]
  label: string
  color?: string
}

type Point = { x: number; y: number }

export function bboxFromDrag(start: Point, end: Point, width: number, height: number): [number, number, number, number] | null {
  const clampX = (value: number) => Math.max(0, Math.min(width, Math.round(value)))
  const clampY = (value: number) => Math.max(0, Math.min(height, Math.round(value)))
  const x0 = clampX(Math.min(start.x, end.x))
  const y0 = clampY(Math.min(start.y, end.y))
  const x1 = clampX(Math.max(start.x, end.x))
  const y1 = clampY(Math.max(start.y, end.y))
  return x1 - x0 >= 2 && y1 - y0 >= 2 ? [x0, y0, x1, y1] : null
}

export function ImageBoxPicker({
  page,
  boxes,
  onAdd,
  disabled = false,
  addLabel = '将选区加入来源',
}: {
  page: MaterialPage
  boxes: ImageBox[]
  onAdd: (bbox: [number, number, number, number]) => void
  disabled?: boolean
  addLabel?: string
}) {
  const imageRef = useRef<HTMLImageElement>(null)
  const previewUrl = sameOriginHref(page.preview_url)
  const imageKey = JSON.stringify([page.id, previewUrl, page.width, page.height])
  const startRef = useRef<{ imageKey: string; point: Point } | null>(null)
  const [selection, setSelection] = useState<{ imageKey: string; bbox: [number, number, number, number] } | null>(null)
  const [imageState, setImageState] = useState<{ imageKey: string; loaded: boolean; aspectMatches: boolean }>({ imageKey, loaded: false, aspectMatches: false })
  const imageLoaded = imageState.imageKey === imageKey && imageState.loaded
  const aspectMatches = imageState.imageKey === imageKey && imageState.aspectMatches
  const previewBox = selection?.imageKey === imageKey ? selection.bbox : null
  const validBoxes = useMemo(() => boxes.filter((box) => validBbox(box.bbox, page.width, page.height)), [boxes, page.height, page.width])
  const ready = imageLoaded && aspectMatches && !disabled && Boolean(previewUrl)

  const previousImageKey = useRef(imageKey)
  useLayoutEffect(() => {
    if (previousImageKey.current === imageKey) return
    previousImageKey.current = imageKey
    startRef.current = null
    setSelection(null)
    setImageState({ imageKey, loaded: false, aspectMatches: false })
  }, [imageKey])

  const pointFromEvent = (event: PointerEvent<SVGSVGElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect()
    return {
      x: rect.width ? Math.max(0, Math.min(page.width, (event.clientX - rect.left) * page.width / rect.width)) : 0,
      y: rect.height ? Math.max(0, Math.min(page.height, (event.clientY - rect.top) * page.height / rect.height)) : 0,
    }
  }

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (!ready || event.button > 0) return
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    const point = pointFromEvent(event)
    startRef.current = { imageKey, point }
    setSelection({ imageKey, bbox: [Math.round(point.x), Math.round(point.y), Math.round(point.x), Math.round(point.y)] })
  }

  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!startRef.current || startRef.current.imageKey !== imageKey) return
    const end = pointFromEvent(event)
    const start = startRef.current.point
    setSelection({ imageKey, bbox: [
      Math.min(start.x, end.x), Math.min(start.y, end.y),
      Math.max(start.x, end.x), Math.max(start.y, end.y),
    ] })
  }

  const onPointerUp = (event: PointerEvent<SVGSVGElement>) => {
    if (!startRef.current || startRef.current.imageKey !== imageKey) return
    const next = bboxFromDrag(startRef.current.point, pointFromEvent(event), page.width, page.height)
    startRef.current = null
    setSelection(next ? { imageKey, bbox: next } : null)
  }

  const handleImageLoad = () => {
    const image = imageRef.current
    if (!image?.naturalWidth || !image.naturalHeight) return
    const actualRatio = image.naturalWidth / image.naturalHeight
    const originalRatio = page.width / page.height
    setImageState({ imageKey, loaded: true, aspectMatches: Math.abs(actualRatio - originalRatio) <= Math.max(0.001, originalRatio * 0.002) })
  }

  return (
    <div className='space-y-3'>
      <div className='relative isolate mx-auto w-full max-w-4xl overflow-hidden rounded-lg border bg-muted/20'>
        {previewUrl ? (
          <img
            ref={imageRef}
            src={previewUrl}
            alt={`资料页 ${page.position} 原图`}
            className='block h-auto w-full select-none'
            draggable={false}
            onLoad={handleImageLoad}
            onError={() => setImageState({ imageKey, loaded: false, aspectMatches: false })}
          />
        ) : (
          <div className='flex min-h-40 items-center justify-center px-4 text-sm text-muted-foreground'>原图预览链接暂不可用。</div>
        )}
        {previewUrl && imageLoaded ? (
          <svg
            viewBox={`0 0 ${page.width} ${page.height}`}
            preserveAspectRatio='none'
            aria-label={`资料页 ${page.position} 区域选框`}
            role='img'
            className={`absolute inset-0 h-full w-full touch-none ${ready ? 'cursor-crosshair' : 'pointer-events-none'}`}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={() => { startRef.current = null; setSelection(null) }}
          >
            {validBoxes.map((box, index) => {
              const [x0, y0, x1, y1] = box.bbox
              const color = box.color || '#0b6e99'
              return <g key={`${box.label}:${index}`}><rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill={`${color}24`} stroke={color} strokeWidth={Math.max(2, Math.min(page.width, page.height) / 400)} vectorEffect='non-scaling-stroke' /><title>{box.label}</title></g>
            })}
            {previewBox ? (() => {
              const [x0, y0, x1, y1] = previewBox
              return <rect x={Math.min(x0, x1)} y={Math.min(y0, y1)} width={Math.abs(x1 - x0)} height={Math.abs(y1 - y0)} fill='#d7831424' stroke='#d78314' strokeWidth={Math.max(2, Math.min(page.width, page.height) / 400)} vectorEffect='non-scaling-stroke' />
            })() : null}
          </svg>
        ) : null}
      </div>
      {!imageLoaded && previewUrl ? <p className='text-sm text-amber-900'>正在读取原图预览…</p> : null}
      {imageLoaded && !aspectMatches ? <p role='alert' className='text-sm text-amber-900'>预览方向或比例与原图坐标不一致，已停用框选以避免错误定位。</p> : null}
      {disabled && imageLoaded && aspectMatches ? <p className='text-sm text-muted-foreground'>当前为只读查看。</p> : null}
      {ready ? <p className='text-xs text-muted-foreground'>在原图上拖动可添加矩形来源区域；坐标按原图像素取整。</p> : null}
      {previewBox && ready ? <div className='flex flex-wrap gap-4'><button type='button' className='text-sm font-medium text-primary underline' onClick={() => {
        const next = bboxFromDrag({ x: previewBox[0], y: previewBox[1] }, { x: previewBox[2], y: previewBox[3] }, page.width, page.height)
        startRef.current = null
        setSelection(null)
        if (next) onAdd(next)
      }}>{addLabel}</button><button type='button' className='text-sm text-muted-foreground underline' onClick={() => setSelection(null)}>清除选区</button></div> : null}
    </div>
  )
}

function validBbox(bbox: number[], width: number, height: number): bbox is [number, number, number, number] {
  if (bbox.length !== 4 || !bbox.every(Number.isInteger)) return false
  const [x0, y0, x1, y1] = bbox
  return x0 >= 0 && y0 >= 0 && x1 <= width && y1 <= height && x1 - x0 >= 1 && y1 - y0 >= 1
}
