# Task Handoff — 当前状态

2026-09-13 · 冗余文件清理与 Spec／Decision 精简已完成，主 Agent 按 S0 检查差异与引用；未开新 Spec、未改业务代码、未执行测试或 CI。用户已授权提交并推送本次整理，结果以 Git 实际记录为准。

- Spec 010 已完成独立工程验收及用户指定的内容宽度返工，用户审查认可；实现已提交并推送 `dev`：`236a9c4`。最后查询该 SHA 无开放 PR、无远端检查记录，不代表 CI 通过。
- 本次整理保留需求、关键技术契约、验收历史与未验边界，原文和被归档原型在固定 Git 快照中；归档入口与当前 Spec 状态见 [索引](../../specs/README.md)。不恢复旧报告中的等待／重测任务。
- 曾建议下一步做公司试点上线与真实业务验证，用户尚未确认开 Spec 011，也未授权部署；按下一条用户指令继续。
- 提交与合并遵循 [长期 dev 规则](../rules/git-branch-workflow.md)，不自动合并／回同步或持续等待 CI；已通过且未变的检查不重复执行。

## 日常环境

公司入口 `npm run dev:company`：Web 5174、API 8000 和 worker；状态需实际查询，不沿用历史进程／浏览器 tab ID。开发 PostgreSQL 容器 `paa-company-postgres`、库 `paa_company`，schema `0002_model_services`；测试库独立为 `paa_company_test`，Python `.venv-server`。本机 FFmpeg 曾放在 `artifacts/spec008/tools/ffmpeg`，不要将整个 artifacts 目录视作可删除缓存。

`.env.company`、`data/company/` 的凭证／数据库、模型主密钥及本地截图不打印或上传。Spec 009 的真实文字／周报联调使用范围见其 [实施记录](../../specs/spec-009-company-model-services/implementation.md#用户直接修复与真实联调2026-09-12)，授权不自动扩展到其他真实调用。Electron 仍以 `npm run dev` 使用默认日常资料。
