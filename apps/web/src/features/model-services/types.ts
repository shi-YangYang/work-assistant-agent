import type { CompanyService, ModelRouting } from '@paa/api-contracts'

export type Listing = { services: CompanyService[]; routing: ModelRouting }

export type Purpose = 'assistant' | 'report' | 'asr' | 'image'

export const purposeNames = {
  assistant: '文字模型',
  report: '报告生成',
  asr: '语音转写',
  image: '图片生成',
}

export const protocolNames = {
  'dashscope-image': '图片 · DashScope 兼容',
  chat: '聊天 · Chat Completions',
  transcriptions: '语音 · 文件转写',
  'qwen-asr': '语音 · Qwen-ASR 兼容',
  'dashscope-asr': '语音 · 阿里原生语音转写',
}

export function protocolPurpose(
  protocol: import('@paa/api-contracts').CompanyModel['protocol'],
): Purpose {
  return protocol === 'chat' ? 'assistant' : protocol === 'dashscope-image' ? 'image' : 'asr'
}
export function supportsPurpose(
  protocol: import('@paa/api-contracts').CompanyModel['protocol'],
  purpose: Purpose,
) {
  return purpose === 'report' ? protocol === 'chat' : protocolPurpose(protocol) === purpose
}
