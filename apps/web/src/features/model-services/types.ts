import type { CompanyService, ModelRouting } from '@paa/api-contracts'

export type Listing = { services: CompanyService[]; routing: ModelRouting }

export type Purpose = 'assistant' | 'report' | 'asr'

export const purposeNames = { assistant: '工作助手', report: '报告生成', asr: '语音转写' }

export const protocolNames = {
  chat: '聊天 · Chat Completions',
  transcriptions: '语音 · 文件转写',
  'qwen-asr': '语音 · Qwen-ASR 兼容',
  'dashscope-asr': '语音 · 阿里原生语音转写',
}
