# Task Handoff — 当前状态

当前任务：[Spec 006：界面层级、页面导航与会议交互](../../specs/spec-006-interface-and-navigation/spec.md)，状态 ACCEPTANCE。用户已体验并认可原型并授权实施，业务改动与定向类型／lint 检查已完成。

首轮 FAIL 的历史行轮询容量问题已返工：共享队列最多 4 条在途 IPC，100 行及 20 次快速切页定向回归通过；窄窗口引用正文增加最小可读高度。新的独立验收者 `/root/spec006_reacceptance` 已确认没有工程阻塞，等待本次双平台 CI 后形成最终结论；完整依据见本 Spec 的 implementation.md / acceptance.md。协调 Agent 已在默认数据的 npm run dev 窗口完成首轮 CUA。恢复时先读 Git HEAD 与对应 Actions，不能引用旧 SHA 宣称本次通过；继续在 main 工作。

工程基线：main 上的 fa0a285 已提交并推送，[macOS / Windows CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34565153050) 均通过，包含安装版启动、重连、退出及清理。Windows URL 编码校验、NSIS 卸载等待和安装 smoke 提前退出已修复，不作为当前未完成任务。

Spec 004、005 的历史独立验收与物理设备验证边界仍以各自报告为准，本次 CI 成功不自动将它们标记 DONE。旧 .ai/prompts/*spec*.md 仅用于追溯。

持续约束见 AGENTS.md 与 .ai/rules/。本机桌面验收使用项目 npm run dev 和用户默认数据目录，保留服务、密钥、模型与录音；UI 操作只用 CUA。不得因设计讨论发起付费请求或修改用户数据。原型可直接打开文件，当前预览地址为 http://127.0.0.1:5186/prototype.html（静态文件服务，失效时只需重新预览该文件）。
