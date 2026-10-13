import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi } from 'vitest'
import { FormField } from '../../../apps/web/src/components/forms/FormField'
import { ServiceConnectionFields } from '../../../apps/web/src/features/model-services/components/service/ServiceConnectionFields'
import { ServiceEditor } from '../../../apps/web/src/features/model-services/components/service/ServiceEditor'
import { ServiceModelLibrary } from '../../../apps/web/src/features/model-services/components/service/ServiceModelLibrary'
import {
  newModel,
  type ServiceDraft,
} from '../../../apps/web/src/features/model-services/utils/service-drafts'

type Props = { children?: ReactNode; [key: string]: unknown }
function nodes(tree: ReactNode): ReactElement<Props>[] {
  return Children.toArray(tree).flatMap((child) =>
    isValidElement<Props>(child) ? [child, ...nodes(child.props.children)] : [],
  )
}
function text(tree: ReactNode): string {
  return Children.toArray(tree)
    .map((child) => (isValidElement<Props>(child) ? text(child.props.children) : String(child)))
    .join('')
}
function button(tree: ReactNode, name: string) {
  const match = nodes(tree).find(
    (node) =>
      node.props['aria-label'] === name ||
      (typeof node.props.onClick === 'function' && text(node) === name),
  )
  if (!match) throw new Error(`Missing control ${name}`)
  return match.props as Props & { onClick: () => void; disabled?: boolean }
}
const draft = (): ServiceDraft => ({
  id: 'service',
  name: '公司模型',
  baseUrl: 'https://api.example.com/v1',
  revision: 3,
  hasKey: true,
  models: [newModel('company-chat')],
})

it('connection fields route edits, provider changes and secrets to the correct draft callbacks', () => {
  const original = draft()
  const update = vi.fn(),
    changeAddress = vi.fn(),
    onKeyChange = vi.fn()
  const tree = ServiceConnectionFields({
    draft: original,
    busy: '',
    keyValue: '',
    onKeyChange,
    changeAddress,
    update,
  })
  // FormField owns its input; inspect its public change callback at this boundary.
  const fields = nodes(tree).filter((node) => node.type === 'input' || node.type === FormField)
  const change = (field: ReactElement<Props>, value: string) =>
    (field.props.onChange as (event: { target: { value: string } }) => void)({ target: { value } })
  change(
    fields.find((field) => field.props.value === original.name)!,
    '新名称',
  )
  expect(update).toHaveBeenCalledWith({ ...original, name: '新名称' })
  change(
    fields.find((field) => field.props.value === original.baseUrl)!,
    'https://other.example/v1',
  )
  expect(changeAddress).toHaveBeenCalledWith('https://other.example/v1', 'custom')
  change(
    fields.find((field) => field.props.type === 'password')!,
    'local-secret',
  )
  expect(onKeyChange).toHaveBeenCalledWith('local-secret')
  expect(update).toHaveBeenCalledTimes(1)
  expect(original.name).toBe('公司模型')
  expect(renderToStaticMarkup(tree)).toContain('type="password"')
})

it('model library dispatches the selected model and preserves availability guards', () => {
  const service = draft()
  const onAdd = vi.fn(),
    onConfigure = vi.fn(),
    onTest = vi.fn()
  const props = {
    draft: service,
    busy: '',
    connectionReady: true,
    usesFor: () => ['工作助手'],
    onAdd,
    onConfigure,
    onTest,
  }
  const tree = ServiceModelLibrary(props)
  button(tree, ' 获取模型').onClick()
  button(tree, ' 手动添加').onClick()
  button(tree, '设置 company-chat').onClick()
  button(tree, '测试 company-chat').onClick()
  expect(onAdd.mock.calls).toEqual([['catalog'], ['manual']])
  expect(onConfigure).toHaveBeenCalledWith(service.models[0])
  expect(onTest).toHaveBeenCalledWith(service.models[0])
  expect(
    button(ServiceModelLibrary({ ...props, connectionReady: false }), '测试 company-chat').disabled,
  ).toBe(true)
  expect(renderToStaticMarkup(tree)).toContain('工作助手')
})

it('service editor saves without navigating to assignments and keeps its connection guard', () => {
  const service = draft()
  const save = vi.fn().mockResolvedValue(true)
  const setRemoveOpen = vi.fn()
  const props = {
    draft: service,
    busy: '',
    dirty: true,
    setRemoveOpen,
    update: vi.fn(),
    setKeys: vi.fn(),
    connectionReady: true,
    error: '',
    conflict: false,
    save,
    children: createElement('div', null, '连接与模型插槽'),
  }
  const tree = ServiceEditor(props)
  button(tree, '保存服务').onClick()
  expect(save).toHaveBeenCalledExactlyOnceWith()
  button(tree, '删除当前模型服务').onClick()
  expect(setRemoveOpen).toHaveBeenCalledWith(true)
  expect(button(ServiceEditor({ ...props, connectionReady: false }), '保存服务').disabled).toBe(
    true,
  )
  expect(renderToStaticMarkup(ServiceEditor({ ...props, dirty: false }))).toContain(
    '模型用途在“用途分配”中管理',
  )
  expect(renderToStaticMarkup(tree)).toContain('连接与模型插槽')
})
