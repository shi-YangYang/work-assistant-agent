export const purposeNames: Record<string, string> = {
  assistant: '工作助手',
  report: '报告生成',
  asr: '语音转写',
  image: '图片生成',
  admin_test: '配置测试',
}

export const stateNames: Record<string, string> = {
  reserved: '尚未发出',
  running: '进行中',
  succeeded: '成功',
  failed: '失败',
  unknown: '结果未知',
  legacy: '历史未知',
  not_sent: '未发出',
}

export const number = (value: number | null) =>
  value === null ? '未知' : value.toLocaleString('zh-CN')

export const duration = (value: number | null) =>
  value === null ? '未知' : `${(value / 1000).toFixed(2)} 秒`
