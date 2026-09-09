import { createInterface } from 'node:readline'

const lines = createInterface({ input: process.stdin })
lines.on('line', (line) => {
  const request = JSON.parse(line)
  const output =
    JSON.stringify({ id: request.id, result: { method: request.method, text: '中文' } }) + '\n'
  switch (request.method) {
    case 'hang':
      break
    case 'delayed':
      setTimeout(() => process.stdout.write(output), 150)
      break
    case 'split': {
      const bytes = Buffer.from(output)
      const split = bytes.indexOf(Buffer.from('中')) + 1
      process.stdout.write(bytes.subarray(0, split))
      setTimeout(() => process.stdout.write(bytes.subarray(split)), 20)
      break
    }
    case 'invalid':
      process.stdout.write('unexpected log\n')
      break
    case 'flood':
      process.stdout.write('x'.repeat(70_000))
      break
    case 'both':
      process.stdout.write(
        JSON.stringify({ id: request.id, result: {}, error: { code: 'x', message: 'x' } }) + '\n',
      )
      break
    case 'remote_error':
      process.stdout.write(
        JSON.stringify({ id: request.id, error: { code: 'unknown', message: 'private detail' } }) +
          '\n',
      )
      break
    case 'exit':
      process.exit(4)
      break
    case 'shutdown':
      process.stdout.write(output, () => process.exit(0))
      break
    default:
      process.stdout.write(output)
  }
})
