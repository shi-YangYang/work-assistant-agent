# Task Handoff — 当前状态

用户已授权直接修复 CI，不开新 Spec、不创建子 Agent。当前在长期 `dev`：日常静态、双平台单元及受控桌面检查分组运行，真实 ASR / 安装包按改动范围或发布触发；规则以 [README](../../README.md#ci-分层) 为准。先前未提交的 dev 分支约定一并保留，按 [分支规则](../rules/git-branch-workflow.md) 完成 PR 合并和回同步。

原 [Spec 006](../../specs/spec-006-interface-and-navigation/spec.md) 仍为 ACCEPTANCE，界面实施 `cb9425d` 已在 main。首轮 FAIL 的列表轮询容量和窄窗引用问题已返工，独立复验及本机日常环境 CUA 证据见其 implementation.md / acceptance.md。旧实施、验收及诊断 Agent 均已完成或暂停，本次 CI 调整由主 Agent 直接处理。

`cb9425d` 的 [macOS CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34573075617) 在模型下载取消后重试等待 ready 超时。本次通过同步信号固定清理时刻，已证明旧代码在文件清理未完成时发布 missing；修复将清理、终态发布和任务释放保持一致。相同定向测试旧代码 FAIL、修复后 PASS；不靠 sleep 或延长超时，等待失败现在可包含实际状态。

本次本地 S3 检查：47 项 TypeScript、58 项 Python 通过，typecheck / lint / format:check 通过，actionlint 1.7.11 工作流校验通过。CI 选择测试覆盖真实 Git 的完整 PR 差异、最后一次文档提交、删除/重命名和中文路径，以及缺失历史与手动模式。`2e595bc` 已推送 dev，[首轮分层 CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34575986654) 的静态、双平台单元与完整集成检查通过；双平台桌面均失败于命令面板导航后的焦点断言，汇总检查正确失败。已修复 Navigation 的命令执行顺序：先同步关闭模态框，执行导航后不再由卸载逻辑恢复旧焦点；保留原 smoke 断言，web 类型检查通过，下一轮远端桌面验证待核对。

本机 GUI 验收继续使用项目 npm run dev 和用户默认数据，不动真实密钥、模型与录音；本次不运行本机隔离桌面或物理设备测试，受控桌面及安装流程由远端 CI 执行。Spec 004、005 的历史独立验收与物理设备边界仍以各自报告为准，新 CI 通过不自动将历史 Spec 标记 DONE。
