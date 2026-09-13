# Task Handoff — 当前状态

2026-09-13 · [Spec 011：Web 功能管理与交互完善](../../specs/spec-011-web-function-management/spec.md) 已实施并通过返工后的[独立验收](../../specs/spec-011-web-function-management/acceptance.md)，用户已审查，并授权 commit／push。实施 `/root/impl_spec011`、首轮验收 `/root/accept_spec011`（FAIL）、返工 `/root/rework_spec011`、最终验收 `/root/accept_spec011_final`（PASS）均已完成。

- 行为、已关闭问题及实际验证分别见 Spec、实施摘要和验收记录，不在此复制；管理员跨员工问答／Agent 督办不属于本轮已实现能力。
- 日常数据库已备份并升级，原数据摘要一致；开发服务已重启，Web 5174、API 8000 和 worker 已启动。两个空交互测试会话已清理，原消息／配置保留。员工 UI 切换等未实测项见验收记录，不扩写为全端全部通过。
- 本次在 `dev` 提交 Spec 011 及搜索图标居中修复，用户通过 PR 链接决定合并；提交／推送及对应 CI 状态以实际 Git 和远端结果为准。开发基线 `c21462c`；提交合并流程见 [Git 规则](../rules/git-branch-workflow.md)，不自动合并或回同步。

## 日常环境

公司入口 `npm run dev:company`：Web 5174、API 8000 和 worker；状态需实际查询，不沿用历史进程／浏览器 tab ID。开发 PostgreSQL 容器 `paa-company-postgres`、库 `paa_company`，schema `0003_conversations`（已备份升级，16 张原业务表摘要不变，证据见 Spec 实施摘要）；测试库独立为 `paa_company_test`，Python `.venv-server`。本机 FFmpeg 曾放在 `artifacts/spec008/tools/ffmpeg`，不要将整个 artifacts 目录视作可删除缓存。

`.env.company`、`data/company/` 的凭证／数据库、模型主密钥及本地截图不打印或上传。Spec 009 的真实文字／周报联调使用范围见其 [实施记录](../../specs/spec-009-company-model-services/implementation.md#用户直接修复与真实联调2026-09-12)，授权不自动扩展到其他真实调用。Electron 仍以 `npm run dev` 使用默认日常资料。
