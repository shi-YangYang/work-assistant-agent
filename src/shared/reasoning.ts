import type { JsonValue, ModelPresets } from './summary-contracts'
const protectedKeys = new Set([
  'model',
  'messages',
  'stream',
  'stream_options',
  'tools',
  'tool_choice',
  'functions',
  'function_call',
  'response_format',
  'n',
  'store',
  'api_key',
  'apikey',
  'authorization',
  'headers',
  'extra_headers',
  'base_url',
  'baseurl',
  'url',
  'endpoint',
  'method',
  'body',
  'extra_body',
  'extra_query',
  'query',
  'input',
  'prompt',
  'user',
  '__proto__',
  'prototype',
  'constructor',
])
export function validateParameters(value: unknown): asserts value is Record<string, JsonValue> {
  let keys = 0
  function walk(item: unknown, depth: number): void {
    if (depth > 5) throw new Error('推理参数嵌套不能超过 5 层。')
    if (Array.isArray(item)) {
      if (item.length > 32) throw new Error('推理参数数组过长。')
      item.forEach((child) => walk(child, depth + 1))
    } else if (item !== null && typeof item === 'object') {
      if (Object.getPrototypeOf(item) !== Object.prototype)
        throw new Error('推理参数必须是普通 JSON 对象。')
      for (const [key, child] of Object.entries(item)) {
        if (
          ++keys > 64 ||
          !/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(key) ||
          protectedKeys.has(key.toLowerCase())
        )
          throw new Error('推理参数包含受保护字段或过多字段。')
        walk(child, depth + 1)
      }
    } else if (typeof item === 'string') {
      if (
        item.length > 512 ||
        [...item].some(
          (character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127,
        ) ||
        /\$\{|\{\{|<%|javascript:/i.test(item)
      )
        throw new Error('推理参数只接受普通 JSON 值，不支持模板或代码。')
    } else if (typeof item === 'number') {
      if (!Number.isFinite(item) || Math.abs(item) > 1e12) throw new Error('推理参数数值无效。')
    } else if (item !== null && typeof item !== 'boolean')
      throw new Error('推理参数不是合法 JSON。')
  }
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    new TextEncoder().encode(JSON.stringify(value)).length > 4096
  )
    throw new Error('推理参数必须是 4 KiB 以内的 JSON 对象。')
  walk(value, 0)
}
export function selectedParameters(
  models: ModelPresets[],
  model: string,
): Record<string, JsonValue> {
  const entry = models.find((item) => item.model === model)
  const preset = entry?.presets.find((item) => item.id === entry.selectedPresetId)
  if (!preset) return {}
  const value = preset.mode === 'simple' ? { reasoning_effort: preset.value } : preset.parameters
  validateParameters(value)
  return value
}
