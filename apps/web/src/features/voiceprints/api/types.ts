export type Enrollment = {
  memberId: string
  name: string
  role: string
  active: boolean
  state: 'empty' | 'queued' | 'processing' | 'ready' | 'failed' | 'incompatible'
  revision: number
  ready: boolean
  filename: string
  error: string
  speechSeconds: number
  updatedAt: string | null
}

export type VoiceprintList = { modelId: string; items: Enrollment[]; limit: number }

export const status = {
  empty: '未登记',
  queued: '等待处理',
  processing: '正在提取',
  ready: '已就绪',
  failed: '登记失败',
  incompatible: '需要重新登记',
}
