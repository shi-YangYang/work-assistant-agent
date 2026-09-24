export function loginConfigurationErrors(
  value: { corpId: string; clientId: string; secret: string },
  hasSecret: boolean,
) {
  const identifierError = (input: string) =>
    !input.trim() || input.trim().length > 128 || /\s/.test(input.trim())
      ? '请输入 1–128 个字符，不能包含空白。'
      : ''
  return {
    corpId: identifierError(value.corpId),
    clientId: identifierError(value.clientId),
    secret:
      (!hasSecret || value.secret !== '') && (!value.secret.trim() || value.secret.length > 512)
        ? 'Secret 需为 1–512 个字符，不能全为空白。'
        : '',
  }
}
