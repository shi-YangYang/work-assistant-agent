/*!
 * Dither field adapted from https://beui.dev/components/agents/image-generation
 * MIT License — Copyright (c) 2026 Saurabh Chauhan
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
import { useEffect, useRef } from 'react'
import styles from './ImageGenerationPlaceholder.module.css'

export function ImageGenerationDots({ active, flat = false }: { active: boolean; flat?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
    const hover = window.matchMedia('(hover: hover) and (pointer: fine)')
    let frame = 0
    let width = 160
    let height = 160
    let visible = true
    let color = getComputedStyle(canvas).color
    let previous = 0
    const pointer = { x: 80, y: 80, targetX: 80, targetY: 80, inside: false }
    const animated = () => active && !reduce.matches && !document.hidden && visible
    const draw = (time: number) => {
      frame = 0
      const moving = animated()
      const followPointer = moving && hover.matches && pointer.inside
      if (!followPointer) {
        pointer.targetX = width * (0.5 + (moving ? Math.sin(time / 1700) * 0.12 : 0))
        pointer.targetY = height * (0.5 + (moving ? Math.cos(time / 2100) * 0.1 : 0))
      }
      const elapsed = previous ? Math.min(time - previous, 50) : 16.67
      previous = time
      const follow = moving ? 1 - (1 - (followPointer ? 0.16 : 0.045)) ** (elapsed / 16.67) : 1
      pointer.x += (pointer.targetX - pointer.x) * follow
      pointer.y += (pointer.targetY - pointer.y) * follow
      context.clearRect(0, 0, width, height)
      context.fillStyle = color
      // Preserve the demo's dot density and displacement at our smaller sizes.
      const scale = Math.min(width, height) / 208
      const gap = 10 * scale
      const radius = Math.min(width, height) * 0.38
      const columns = Math.ceil(width / gap) + 1
      const rows = Math.ceil(height / gap) + 1
      for (let row = 0; row < rows; row += 1) {
        for (let column = 0; column < columns; column += 1) {
          const anchorX = (width - (columns - 1) * gap) / 2 + column * gap
          const anchorY = (height - (rows - 1) * gap) / 2 + row * gap
          const dx = anchorX - pointer.x
          const dy = anchorY - pointer.y
          const distance = Math.hypot(dx, dy)
          const proximity = Math.max(0, 1 - distance / radius)
          const influence = flat ? 0 : proximity * proximity * (3 - 2 * proximity)
          const displacement = influence * influence * 9 * scale
          const x = anchorX + (distance ? dx / distance : 0) * displacement
          const y = anchorY + (distance ? dy / distance : 0) * displacement
          context.globalAlpha = 0.17 + influence * 0.72
          context.beginPath()
          context.arc(x, y, (0.65 + influence * 0.85) * scale, 0, Math.PI * 2)
          context.fill()
        }
      }
      context.globalAlpha = 1
      if (moving) frame = requestAnimationFrame(draw)
    }
    const refresh = () => {
      cancelAnimationFrame(frame)
      previous = 0
      color = getComputedStyle(canvas).color
      draw(performance.now())
    }
    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      width = rect.width || 160
      height = rect.height || 160
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      pointer.x = width / 2
      pointer.y = height / 2
      refresh()
    }
    const move = (event: PointerEvent) => {
      if (!animated() || !hover.matches || event.pointerType === 'touch') return
      const rect = canvas.getBoundingClientRect()
      pointer.inside = true
      pointer.targetX = event.clientX - rect.left
      pointer.targetY = event.clientY - rect.top
    }
    const leave = () => {
      pointer.inside = false
    }
    const resizeObserver = new ResizeObserver(resize)
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      refresh()
    })
    const theme = new MutationObserver(refresh)
    resize()
    resizeObserver.observe(canvas)
    intersection.observe(canvas)
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    canvas.addEventListener('pointermove', move, { passive: true })
    canvas.addEventListener('pointerleave', leave)
    document.addEventListener('visibilitychange', refresh)
    reduce.addEventListener('change', refresh)
    hover.addEventListener('change', refresh)
    return () => {
      cancelAnimationFrame(frame)
      resizeObserver.disconnect()
      intersection.disconnect()
      theme.disconnect()
      canvas.removeEventListener('pointermove', move)
      canvas.removeEventListener('pointerleave', leave)
      document.removeEventListener('visibilitychange', refresh)
      reduce.removeEventListener('change', refresh)
      hover.removeEventListener('change', refresh)
    }
  }, [active, flat])
  return <canvas ref={ref} className={styles.dots} aria-hidden="true" />
}
