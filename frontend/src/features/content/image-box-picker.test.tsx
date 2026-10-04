import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { bboxFromDrag, ImageBoxPicker } from './image-box-picker'
import type { MaterialPage } from '../../types'

if (!window.PointerEvent) Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent })

const page: MaterialPage = { id: 'page-1', position: 1, sha256: 'synthetic', width: 100, height: 100, page_url: '/page/', preview_url: '/preview/' }

describe('ImageBoxPicker', () => {
  afterEach(() => { cleanup() })

  it('maps an image drag to bounded, integer original-image coordinates', () => {
    expect(bboxFromDrag({ x: 80.2, y: 40.8 }, { x: -5, y: 120 }, 100, 100)).toEqual([0, 41, 80, 100])
    expect(bboxFromDrag({ x: 4, y: 5 }, { x: 4.5, y: 20 }, 100, 100)).toBeNull()
  })

  it('requires explicit confirmation before adding a selected region', async () => {
    const onAdd = vi.fn()
    render(<ImageBoxPicker page={page} boxes={[]} onAdd={onAdd} />)
    const image = screen.getByAltText('资料页 1 原图')
    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 100 })
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 100 })
    fireEvent.load(image)
    const svg = screen.getByRole('img', { name: '资料页 1 区域选框' })
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      x: 10, y: 20, left: 10, top: 20, right: 210, bottom: 220, width: 200, height: 200,
      toJSON: () => ({}),
    })
    fireEvent.pointerDown(svg, { button: 0, pointerId: 1, clientX: 30, clientY: 40 })
    fireEvent.pointerMove(svg, { pointerId: 1, clientX: 130, clientY: 140 })
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: 130, clientY: 140 })
    expect(onAdd).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '将选区加入来源' }))
    expect(onAdd).toHaveBeenCalledWith([10, 10, 60, 60])
  })

  it('maps portrait previews against the full image and clears readiness and selection on page changes', () => {
    const onAdd = vi.fn()
    const portrait: MaterialPage = { ...page, width: 100, height: 200, preview_url: '/portrait/' }
    const view = render(<ImageBoxPicker page={portrait} boxes={[]} onAdd={onAdd} />)
    const image = screen.getByAltText('资料页 1 原图')
    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 100 })
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 200 })
    fireEvent.load(image)
    const svg = screen.getByRole('img', { name: '资料页 1 区域选框' })
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      x: 10, y: 20, left: 10, top: 20, right: 210, bottom: 420, width: 200, height: 400, toJSON: () => ({}),
    })
    fireEvent.pointerDown(svg, { button: 0, pointerId: 1, clientX: 20, clientY: 40 })
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: 100, clientY: 200 })
    expect(screen.getByRole('button', { name: '将选区加入来源' })).toBeTruthy()

    const nextPage: MaterialPage = { ...portrait, id: 'page-2', position: 2, preview_url: '/portrait-2/' }
    view.rerender(<ImageBoxPicker page={nextPage} boxes={[]} onAdd={onAdd} />)
    expect(screen.getByText('正在读取原图预览…')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '将选区加入来源' })).toBeNull()
    expect(screen.queryByRole('img', { name: '资料页 2 区域选框' })).toBeNull()

    const nextImage = screen.getByAltText('资料页 2 原图')
    Object.defineProperty(nextImage, 'naturalWidth', { configurable: true, value: 100 })
    Object.defineProperty(nextImage, 'naturalHeight', { configurable: true, value: 200 })
    fireEvent.load(nextImage)
    expect(screen.queryByRole('button', { name: '将选区加入来源' })).toBeNull()
    expect((nextImage as HTMLImageElement).className).toContain('h-auto')
    expect((nextImage as HTMLImageElement).className).not.toContain('object-contain')
    expect(onAdd).not.toHaveBeenCalled()
  })
})
