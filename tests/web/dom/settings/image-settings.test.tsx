// @vitest-environment jsdom
import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { ImageSettings } from '../../../../apps/web/src/features/model-services/components/catalog/ImageSettings'
import {
  newModel,
  modelFieldErrors,
} from '../../../../apps/web/src/features/model-services/utils/service-drafts'
import { changeModelProtocol } from '../../../../apps/web/src/features/model-services/utils/service-presets'

afterEach(cleanup)
function Harness() {
  const [model, setModel] = useState(
    changeModelProtocol(newModel('future-image'), 'dashscope-image'),
  )
  const [invalid, setInvalid] = useState(false)
  return (
    <>
      <ImageSettings model={model} updateModel={setModel} onValidityChange={setInvalid} />
      <button disabled={invalid || !!modelFieldErrors(model).imageSettings}>保存</button>
      <output>{JSON.stringify(model.imageSettings)}</output>
    </>
  )
}

it('configures a new model with Enter tags, default selection and removable sizes', () => {
  render(<Harness />)
  const save = screen.getByRole('button', { name: '保存' }) as HTMLButtonElement
  expect(save.disabled).toBe(true)
  fireEvent.change(screen.getByRole('combobox', { name: /图片请求方式/ }), {
    target: { value: 'multimodal-sync' },
  })
  expect(save.disabled).toBe(false)
  fireEvent.change(screen.getByRole('combobox', { name: /图片尺寸/ }), {
    target: { value: 'fixed' },
  })
  expect(save.disabled).toBe(true)
  const input = screen.getByRole('textbox', { name: '可选尺寸' })
  fireEvent.change(input, { target: { value: '1024x1024' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(screen.getByRole('button', { name: '删除尺寸 1024*1024' })).toBeTruthy()
  expect(save.disabled).toBe(false)
  fireEvent.change(input, { target: { value: '1536*1024' } })
  expect(save.disabled).toBe(true)
  fireEvent.keyDown(input, { key: 'Enter' })
  fireEvent.change(screen.getByRole('combobox', { name: '默认尺寸' }), {
    target: { value: '1536*1024' },
  })
  fireEvent.click(screen.getByRole('button', { name: '删除尺寸 1536*1024' }))
  expect((screen.getByRole('combobox', { name: '默认尺寸' }) as HTMLSelectElement).value).toBe(
    '1024*1024',
  )
  fireEvent.change(screen.getByRole('combobox', { name: /图片尺寸/ }), {
    target: { value: 'provider' },
  })
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('"sizes":[]')
  expect(save.disabled).toBe(false)
})
