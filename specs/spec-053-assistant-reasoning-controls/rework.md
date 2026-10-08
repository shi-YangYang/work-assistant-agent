# Implementation Rework

## 修复内容

- 保存现有服务时，若助手初始预设不在新开放列表，且管理员在模型草稿中明确选中了开放预设，则在同一事务更新助手用途和用途 revision。有效初始选择保持不变，不猜选首项，不替换独立报告配置；全部用途验证通过后才写入。
- 附件上传后、首次生成待发送请求前再次读取已保存强度引用。账号偏好仍在保存时结束本次发送，保留草稿和已上传附件；后续由用户发送。已有不确定请求继续重放原请求体和幂等键。
- 预设开放开关使用组件私有横向布局，标签触摸高度为 44px。模型预设下说明初始档位失效时的原子同步规则。

## 涉及文件

- `apps/server/app/modules/model_services/service.py`
- `apps/web/src/features/assistant/hooks/useMessageSubmission.ts`
- `apps/web/src/features/model-services/components/catalog/{ModelOptions.tsx,ReasoningPresetEditor.tsx,ReasoningPresetEditor.module.css}`
- `tests/server/test_assistant_reasoning.py`
- `tests/web/dom/assistant-reasoning.test.tsx`

## 验证

- 从 `artifacts/spec053/test-env.json` 注入隔离数据库环境，运行 `.venv-server/bin/python -m pytest -q tests/server/test_assistant_reasoning.py tests/server/test_model_services.py`：69 例通过。日志：`artifacts/spec053/rework-server.log`。
- `npm run test:web -- tests/web/dom/assistant-reasoning.test.tsx tests/web/message-submission.test.ts`：10 例通过。
- 新增后端回归覆盖无预设模型首次开放、删除／关闭原初始预设、无有效替代拒绝、报告配置失败的原子回滚、服务／用途／发送版本冲突、有效偏好保留和失效回退、已接受任务快照保持不变。
- 新增 Web 回归覆盖另一会话保存偏好与附件上传重叠、阻止无引用 POST、草稿及已上传附件保留、保存完成后不自动发送、手动重试不重复上传，以及不确定请求的原引用和幂等键重放。
- 本次改动 TS／TSX／CSS 已运行 Prettier；改动 TS／TSX 的 ESLint 与 `git diff --check` 通过。未重复运行完整功能测试、类型检查或构建。

## 待主 Agent 完成

- 定向复核管理员首次启用的浏览器保存流程与桌面／窄屏复选框布局。
- 创建新的独立验收 Agent。原 FAIL 报告和历史验证证据保留。

未提交、推送或部署，未查询远端 CI，未修改用户真实模型配置或迁移数据库。
