# Task Handoff — 当前状态

CI 减负配置、规则与冗余文件清理已于 `d022710` 推送至 `dev`。用户随后确认 PR 仍需双平台基础检查，并授权提交、推送本次补充；交付提供 PR 链接，由用户合并并回同步，不自动合并或等待 CI，详见 [分支规则](../rules/git-branch-workflow.md)。原 Spec 006 后续工作保持暂停。

- 上轮 CI 分层、模型取消重试与导航焦点修复已通过 [PR #1 的完整双平台 CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34578631567)，并合并到 `main`、回同步到 `dev`，共同提交为 `e91748f`。合并后的重复流水线未核对最终结果，不宣称其通过。
- 当前补充将 PR 单元／模块测试和普通构建改为 macOS / Windows 双平台，格式、Lint、类型只在 macOS 执行一次；桌面、模型与安装包仍只通过手动入口或发布标签运行。具体范围见 [README](../../README.md#ci-分层)。工作流格式化、actionlint 和 diff 检查已通过，未重跑业务测试；远端结果以本次提交实际检查为准，不引用旧结果。
- Spec 状态和历史验收以 [Spec 索引](../../specs/README.md) 及对应报告为准；不把 CI 修复视作新的独立验收。已完成任务的专用交接已删除，原文通过 Git 历史追溯。
- 当前使用长期 `dev` 分支。本机 GUI 验收仍在项目目录运行 `npm run dev`，保留用户默认数据、服务配置、录音和模型；不读取明文密钥。
