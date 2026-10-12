// First tile of the approved generated sheet. All face/body/keyboard pixels
// remain fixed; only the two clipped paw meshes are displaced.
const tileSize = 627
const hands = [
  {
    x: 94,
    y: 404,
    width: 163,
    height: 146,
    phase: 0,
    outline:
      'M149 404 C113 416 95 445 99 477 C96 503 106 522 132 530 C166 540 213 543 241 532 C257 523 250 487 237 470 C223 443 196 422 149 404Z',
  },
  {
    x: 397,
    y: 407,
    width: 157,
    height: 148,
    phase: 240,
    outline:
      'M466 408 C430 422 405 454 402 488 C398 516 408 534 437 539 C466 546 508 543 532 528 C553 508 553 475 536 449 C514 425 489 413 466 408Z',
  },
]
type Point = { x: number; y: number; weight: number }
type Triangle = [Point, Point, Point]
const meshes = hands.map((hand) => {
  const columns = 10,
    rows = 12
  const point = (x: number, y: number): Point => ({
    x: hand.x + (x / columns) * hand.width,
    y: hand.y + (y / rows) * hand.height,
    weight: Math.sin((Math.PI * x) / columns) ** 1.1 * Math.sin((Math.PI * y) / rows) ** 1.2,
  })
  const triangles: Triangle[] = []
  for (let y = 0; y < rows; y++)
    for (let x = 0; x < columns; x++) {
      const a = point(x, y),
        b = point(x + 1, y),
        c = point(x + 1, y + 1),
        d = point(x, y + 1)
      triangles.push([a, b, c], [a, c, d])
    }
  return { ...hand, triangles }
})
export function typingLift(time: number, phase: number) {
  const beat = (time + phase) % 2400
  return beat >= 1920 ? 0 : Math.sin((Math.PI * (beat % 480)) / 480) ** 4 * 32
}
function triangle(
  ctx: CanvasRenderingContext2D,
  image: CanvasImageSource,
  points: Triangle,
  lift: number,
) {
  const [a, b, c] = points
  const y0 = a.y - lift * a.weight,
    y1 = b.y - lift * b.weight,
    y2 = c.y - lift * c.weight
  const determinant = (b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)
  const skew = ((y1 - y0) * (c.y - a.y) - (y2 - y0) * (b.y - a.y)) / determinant
  const scale = ((b.x - a.x) * (y2 - y0) - (c.x - a.x) * (y1 - y0)) / determinant
  ctx.save()
  ctx.beginPath()
  ctx.moveTo(a.x, y0)
  ctx.lineTo(b.x, y1)
  ctx.lineTo(c.x, y2)
  ctx.closePath()
  ctx.clip()
  ctx.transform(1, skew, 0, scale, 0, y0 - skew * a.x - scale * a.y)
  ctx.drawImage(image, 0, 0)
  ctx.restore()
}
export function createTypingRenderer(image: HTMLImageElement, canvas: HTMLCanvasElement) {
  const out = canvas.getContext('2d')
  if (!out) return null
  // At most 64 small physical-size frames (~11 MB at 204px), shared across
  // repeated beats. No full-size texture deformation on every animation tick.
  const frames = new Map<string, HTMLCanvasElement>()
  const paths = meshes.map((hand) => new Path2D(hand.outline))
  const draw = (time: number) => {
    const lifts = meshes.map((hand) => Math.round(typingLift(time, hand.phase)))
    const key = lifts.join(':')
    let frame = frames.get(key)
    if (!frame) {
      frame = document.createElement('canvas')
      frame.width = frame.height = canvas.width
      const ctx = frame.getContext('2d')!
      ctx.scale(canvas.width / tileSize, canvas.width / tileSize)
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, tileSize, tileSize)
      ctx.drawImage(image, 0, 0)
      meshes.forEach((hand, index) => {
        if (!lifts[index]) return
        ctx.save()
        ctx.clip(paths[index])
        for (const points of hand.triangles) triangle(ctx, image, points, lifts[index])
        ctx.restore()
      })
      if (frames.size >= 64) frames.delete(frames.keys().next().value!)
      frames.set(key, frame)
    }
    out.clearRect(0, 0, canvas.width, canvas.height)
    out.drawImage(frame, 0, 0)
  }
  return draw
}
