# 图片模型配置扩展实施

## 实现

- `dashscope-image` 保持兼容；`imageSettings` 通过已有模型 JSON 保存 `api`（auto／multimodal-sync／image-async）、`sizeMode`（auto／provider／fixed）、最多 16 个 `sizes` 与 `defaultSize`。未知模型必须明确接口，不使用模型名称猜测或失败后切换 POST。
- 保留 Wan 默认 2K，加入 Wan Pro 的 4K 能力。未知模型及 provider 模式未指定尺寸时不发送 `size`；fixed 模式按配置选择、检查比例和精确宽高，不替换不支持的显式要求。
- 管理员模型设置提供图片请求方式、尺寸模式、Enter 尺寸标签与默认尺寸选择；切换回聊天／语音清除图片配置。草稿、服务版本、测试、用途分配和任务均携带设置。
- 原生／Token Plan／明确选择协议的兼容 HTTPS 网关复用两个固定路径；同源密钥、SSRF、同步 300 秒、异步回执和幂等保护不变。同步请求不带异步 header，非 Wan 模型不附加 Wan 专用参数。
- 操作领取时从冻结版本规范化尺寸；已存在操作优先使用自己的 binding，管理员更新模型或刷新任务配置后，原操作仍恢复原结果。无新增 migration、模型阶段或聊天预算调整。
- PNG 校验与具体模型尺寸分离：32 MiB、最多 4096² 总像素、16384 单边，检查格式和解码；允许合法较小尺寸及 Pro 4K，仍拒绝损坏与超大文件。

## 变更文件

后端：

- `integrations/models/images/profiles.py`（新增）、`sizes.py`、`wan.py`、`results.py`。
- `modules/model_services/{schemas,bindings,drafts,image_probe}.py`。
- `modules/image_generation/service.py`。
- `agent/prompts/main.py`、`agent/tools/resources/images.py`。

前端与契约：

- `packages/api-contracts/src/index.ts`。
- `features/model-services/types.ts`、`utils/{service-presets,service-drafts,image-settings}.ts`（最后一项新增）。
- `features/model-services/components/catalog/{ModelOptions,ImageSettings}.tsx`（最后一项新增）。
- `ImageSettings` 复用同目录现有标签样式，没有新增依赖。

测试：

- `tests/server/modules/image_generation/{test_configuration,test_protocol}.py`。
- `tests/server/modules/image_generation/test_model_settings.py`（新增）。
- `tests/web/model-services/image-model.test.ts`。
- `tests/web/dom/settings/image-settings.test.tsx`（新增）。

## 验证

按 S3 选择受影响子系统；后端均由 `artifacts/spec065/tests/environment.json` 管理的隔离测试环境运行，没有使用日常数据库或真实服务密钥。

```text
pytest -q --tb=short tests/server/modules/image_generation tests/server/modules/model_services
156 passed in 20.95s

npm run test:web -- tests/web/model-services tests/web/dom/settings/image-settings.test.tsx tests/web/dom/settings/model-routing-legacy.test.tsx
Test Files 6 passed (6)
Tests 44 passed (44)
Duration 635ms

npm run typecheck:web
exit 0

npx eslint <本次 9 个 TS/TSX 文件>
exit 0
```

Pro 不支持分辨率的错误文案修正后，仅复验有关尺寸分支：

```text
pytest -q --tb=short tests/server/modules/image_generation/test_model_settings.py::test_model_validation_and_profile_sizes tests/server/modules/image_generation/test_protocol.py::test_invalid_sizes_fail_before_provider
10 passed in 1.41s
```

本次 TS/TSX 使用项目 Prettier 格式化；`git diff --check` 通过。固定输入覆盖未知模型保存／用途／管理员测试／Agent 生成、provider 默认不发送尺寸、fixed 比例及宽高错误、配置变更后恢复不重发、4K PNG 与像素上界，既有同步／异步／取消／幂等／权限用例继续通过。

## 边界

- 只支持两个已实现的 DashScope 兼容请求／结果协议及 PNG；完全不同的协议、Base64、JPEG／WebP 或上传图编辑不在范围内。
- 自动能力只内置已确认 Wan 与 Wan Pro；其他模型手动选择接口和尺寸规则。固定尺寸匹配明确比例，不假设供应商会生成任意比例。
- 本实施 Agent 未调用真实外部模型，未修改日常配置，未迁移／重启、commit 或 push；真实服务回归和运行更新由主 Agent 决定，独立验收另行进行。

## 协调 Agent 补充验证

- 隔离 UI 环境使用现有 owned schema 和合成账号，浏览器添加 `1024*1024`、`1536*1024` 两个尺寸标签，选后者为默认尺寸，保存服务后刷新，界面仍显示相同配置。没有调用测试服务的外部模型，也没有修改日常账号的模型设置。布局与刷新后证据分别为 `artifacts/spec065/ui/model-config-layout.png`、`model-config-fixed.png`；后者截图底部选择框受视口裁剪，默认值由刷新后的 AX 状态确认。
- 另使用日常已保存的 Wan2.7 Token Plan 配置做一次真实 `image_probe` 回归：返回 **2048 × 2048 PNG，13.619 秒，849 输入／2 输出／851 总 tokens**。脚本仅包装实际安全下载留存图片，不模拟返回，不改服务或用途。脚本、原始结果和图片见 `artifacts/spec065/model-config/{real_probe.py,real-probe.json,generated-bird.png}`。
- 这次实测证明原 Wan 配置在扩展后仍可用，不代表所有兼容模型或 Pro 4K 均已真实调用；其他模型的配置与协议行为使用固定输入验证。
- 已通过标准 `npm run dev:web` 优雅停止并重新启动日常 API、worker 和 Web，API `8000` 与 Web `5174` 代理健康检查均为 `200 / ready`。本扩展无新增迁移，保留既有 `0030`；临时 UI 的 API／Web 进程和浏览器标签已关闭。
