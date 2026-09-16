import { useEffect, useRef } from 'react'

/*
 * Silk shader adapted from React Bits; the WebGL lifecycle below is local.
 * https://github.com/DavidHDev/react-bits/blob/main/src/ts-default/Backgrounds/Silk/Silk.tsx
 *
 * MIT + Commons Clause License Condition v1.0
 * Copyright (c) 2026 David Haz
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, and distribute the Software as part of
 * an application, website, or product, subject to the following conditions:
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * Commons Clause Restriction: You may use this Software, including for any
 * commercial purpose, so long as you do not sell, sublicense, or redistribute
 * the components themselves-whether alone, in a bundle, or as a ported version.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */
const fragmentSource = `
precision mediump float;
varying vec2 uv;
uniform float time;
uniform float dark;
uniform float aspect;

float noise(vec2 p) {
  vec2 r = 2.7182818 * sin(2.7182818 * p);
  return fract(r.x * r.y * (1.0 + p.x));
}

void main() {
  vec2 p = uv - 0.5;
  p.x *= aspect;
  p = mat2(0.94, -0.342, 0.342, 0.94) * p + 0.5;
  p.y += 0.03 * sin(8.0 * p.x - time);
  float pattern = 0.6 + 0.4 * sin(
    5.0 * (p.x + p.y + cos(3.0 * p.x + 5.0 * p.y) + 0.02 * time)
    + sin(20.0 * (p.x + p.y - 0.1 * time))
  );
  float fold = smoothstep(0.28, 0.9, pattern);
  float sheen = smoothstep(0.72, 0.98, pattern);
  vec3 silver = mix(vec3(0.68, 0.70, 0.73), vec3(0.88, 0.89, 0.90), fold);
  silver = mix(silver, vec3(0.98, 0.975, 0.96), sheen * 0.6);
  vec3 graphite = mix(vec3(0.05, 0.052, 0.06), vec3(0.20, 0.215, 0.24), fold);
  graphite = mix(graphite, vec3(0.33, 0.34, 0.37), sheen * 0.4);
  vec3 color = mix(silver, graphite, dark);
  color += (noise(gl_FragCoord.xy) - 0.5) * 0.008;
  gl_FragColor = vec4(color, 1.0);
}
`

function startSilk(canvas: HTMLCanvasElement) {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: false, depth: false })
  if (!gl) return
  const program = gl.createProgram()
  const buffer = gl.createBuffer()
  const shaders: WebGLShader[] = []
  const dispose = () => {
    shaders.forEach((shader) => gl.deleteShader(shader))
    gl.deleteBuffer(buffer)
    gl.deleteProgram(program)
  }
  if (!program || !buffer) {
    dispose()
    return
  }
  const sources: [number, string][] = [
    [
      gl.VERTEX_SHADER,
      `attribute vec2 position; varying vec2 uv;
      void main() { uv = position * 0.5 + 0.5; gl_Position = vec4(position, 0.0, 1.0); }`,
    ],
    [gl.FRAGMENT_SHADER, fragmentSource],
  ]
  for (const [type, source] of sources) {
    const shader = gl.createShader(type)
    if (!shader) {
      dispose()
      return
    }
    shaders.push(shader)
    gl.shaderSource(shader, source)
    gl.compileShader(shader)
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      dispose()
      return
    }
    gl.attachShader(program, shader)
  }
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    dispose()
    return
  }
  gl.useProgram(program)
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
  const position = gl.getAttribLocation(program, 'position')
  gl.enableVertexAttribArray(position)
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0)
  const timeUniform = gl.getUniformLocation(program, 'time')
  const darkUniform = gl.getUniformLocation(program, 'dark')
  const aspectUniform = gl.getUniformLocation(program, 'aspect')
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)')
  let frame = 0
  let lastFrame = 0
  let elapsed = 4
  let lost = false
  let dark = document.documentElement.dataset.theme === 'dark'

  const draw = () => {
    if (lost) return
    gl.uniform1f(timeUniform, elapsed)
    gl.uniform1f(darkUniform, dark ? 1 : 0)
    gl.uniform1f(aspectUniform, canvas.width / Math.max(1, canvas.height))
    gl.drawArrays(gl.TRIANGLES, 0, 3)
  }
  const animate = (now: number) => {
    if (lost) return
    // Limit this decorative layer to 30 fps, independent of monitor refresh rate.
    if (!lastFrame || now - lastFrame >= 1000 / 30) {
      elapsed += lastFrame ? Math.min((now - lastFrame) / 1000, 0.1) * 0.45 : 0
      lastFrame = now
      draw()
    }
    frame = requestAnimationFrame(animate)
  }
  const resume = () => {
    cancelAnimationFrame(frame)
    lastFrame = 0
    draw()
    if (!lost && !document.hidden && !reducedMotion.matches) {
      frame = requestAnimationFrame(animate)
    }
  }
  const resize = () => {
    const { width, height } = canvas.getBoundingClientRect()
    // The smooth surface does not need a full Retina-resolution drawing buffer.
    const scale = Math.min(devicePixelRatio || 1, 1.25, 1600 / Math.max(width, height, 1))
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    gl.viewport(0, 0, canvas.width, canvas.height)
    draw()
  }
  const contextLost = () => {
    lost = true
    cancelAnimationFrame(frame)
    canvas.style.visibility = 'hidden'
  }
  const sizeObserver = new ResizeObserver(resize)
  const themeObserver = new MutationObserver(() => {
    dark = document.documentElement.dataset.theme === 'dark'
    draw()
  })
  sizeObserver.observe(canvas)
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
  document.addEventListener('visibilitychange', resume)
  reducedMotion.addEventListener('change', resume)
  canvas.addEventListener('webglcontextlost', contextLost)
  resize()
  resume()

  return () => {
    cancelAnimationFrame(frame)
    sizeObserver.disconnect()
    themeObserver.disconnect()
    document.removeEventListener('visibilitychange', resume)
    reducedMotion.removeEventListener('change', resume)
    canvas.removeEventListener('webglcontextlost', contextLost)
    dispose()
  }
}

export function LoginBackground() {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (!canvas.current) return
    return startSilk(canvas.current)
  }, [])
  return (
    <div className="login-ambient" aria-hidden="true">
      <canvas ref={canvas} />
    </div>
  )
}
