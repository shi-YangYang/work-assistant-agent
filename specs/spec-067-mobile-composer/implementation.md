# Implementation Report

## Summary

手机输入栏收为语音、文字和“＋”，有草稿或任务状态时显示发送／中断／重试。图片、文件、引用工作、上下文、强度和执行权限移入下方功能面板；桌面布局与业务请求保持原有语义。

保留单个文本框、录音按钮、设置控件实例。面板收起后内部控件不可聚焦，键盘与面板互斥，内层浮层先于面板响应 Esc，切换会话和断点关闭面板；录音点击及长按仍复用现有控制器。输入区增高不再让历史阅读位置出现虚假的“新回复”。

## Files Changed

- `apps/web/src/features/assistant/components/composer/MessageComposer.tsx`、对应 CSS：主栏布局、主操作可见性、草稿预览和入口协调。
- 新增同目录 `MobileComposerPanel.tsx`、CSS：带名称功能入口和设置行；`ComposerAttachmentMenu.tsx`：提取已有桌面附件菜单。
- 新增 `apps/web/src/features/assistant/hooks/composer/useMobileComposerPanel.ts`：局部显示状态、焦点／键盘／断点协调和菜单可视区域定位。
- `composer/controls/{ContextUsage,ReasoningEffortPicker,ExecutionModePicker}.tsx`、CSS：手机面板形态、当前值与内层菜单互斥；保留自主执行确认。
- `composer/controls/VoiceRecordButton.tsx`：开始录音前关闭功能面板，手势和业务控制器未改。
- `components/conversation/ConversationChat.tsx`：消息高度观察排除输入区底部留白变化。
- 新增 `tests/web/dom/assistant/mobile-composer.test.tsx`：10 项手机交互用例；更新 `assistant-reasoning.test.tsx` 的控件顺序断言以适配网格容器，继续验证顺序及单实例。

## Tests

S2，按输入区子系统验证，无真实模型调用、API 重启或全量构建。

- 首轮定向执行六文件（mobile-composer、composer-attachments、voice-recording、assistant-context、assistant-reasoning、assistant-work-reference）：54 通过、2 失败。分别为新测试缺少原生 dialog 模拟、隐藏手机入口与旧桌面文字查询重复。
- 补充原生 dialog 模拟并仅在手机挂载手机入口后，复跑 mobile-composer、assistant-work-reference：18 通过。
- 设置浮层关闭与 ESLint 修复后，复跑 mobile-composer、assistant-context、assistant-reasoning：32 通过。
- 最后补充 Context 双次 Esc 与手机长按单次发送回归，复跑 mobile-composer、assistant-context：24 通过。
- 六文件最终有效结果合计 **57 项通过**；仅对修改或失败涉及的用例复跑。命令均为 `npm run test:web -- tests/web/dom/assistant/<上述文件>.test.tsx`。
- 已对本次源码与测试执行项目 Prettier；改动 TS／TSX 的定向 ESLint 通过，最后仅复查之后变化的 ContextUsage、useMobileComposerPanel、mobile-composer 三文件，通过。
- `git diff --check` 通过。
- `npm run typecheck:web` **未通过**：本次测试类型错误已修复，末次结果仅剩既存 `tests/web/dom/notifications/notifications.test.tsx:129`：`getByRole` 的 `ByRoleOptions` 不支持 `exact` 属性。未修改该无关文件，不把整体类型检查表述为通过。

## Known Limitations

协调 Agent 已在本地隔离 fixture 执行手机／桌面浏览器视觉检查，证据在 `artifacts/spec067/`；由其与独立验收 Agent 汇总结论。当前报告不是独立验收。

iOS／Android／钉钉的真实软键盘、麦克风权限及系统选择器未在真机验收。自动测试使用固定事件和模拟媒体设备；不代表所有 WebView 真机行为已验证。

## Remaining Questions

无产品决策待定；等待独立验收。未 commit 或 push。
