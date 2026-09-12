import { describe, expect, it } from 'vitest'
import {
  cleanServiceDraft,
  newModel,
  validateCompanyParameters,
} from '../../src/web/model-service-drafts'

describe('company model drafts', () => {
  it('retains ordinary edits without retaining write-only credentials', () => {
    const model = newModel('long-model-id')
    const input = {
      id: 'draft',
      name: '服务',
      baseUrl: 'https://example.com/v1',
      models: [model],
      revision: 0,
      hasKey: false,
      apiKey: 'never-persist-me',
    }
    const stored = cleanServiceDraft(input)
    expect(JSON.stringify(stored)).not.toContain('never-persist-me')
    expect(stored.models[0].streaming).toBe(true)
    input.models[0].model = 'changed'
    expect(stored.models[0].model).toBe('long-model-id')
  })
  it('protects nested credentials, transport and resource controls with server-equivalent boundaries', () => {
    for (const invalid of [
      { headers: {} },
      { thinking: { max_tokens: 200 } },
      { reasoning_effort: '${secret}' },
      { stream: false },
      { timeout: 600 },
    ]) {
      expect(() => validateCompanyParameters(invalid)).toThrow()
    }
    expect(validateCompanyParameters({ reasoning_effort: 'high' })).toEqual({
      reasoning_effort: 'high',
    })
    expect(validateCompanyParameters({})).toEqual({})
  })
})
