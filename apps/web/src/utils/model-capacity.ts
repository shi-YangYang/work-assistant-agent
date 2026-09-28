export function capacitySourceLabel(source: string) {
  if (source === 'override') return '管理员配置'
  if (source === 'unknown') return '未知'
  if (source.startsWith('official:')) return '服务官方规格'
  if (source.startsWith('metadata:') || source === 'provider') return '服务返回的模型信息'
  return source
}
