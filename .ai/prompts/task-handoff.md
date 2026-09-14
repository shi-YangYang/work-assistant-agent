# Task Handoff — 当前状态

2026-09-14 · [Spec 012：工作助手文件发送与解析](../../specs/spec-012-assistant-documents/spec.md) 已完成，来源删除竞态返工后通过新的独立验收。日常 Web 及原资料保留，测试样本已清理；实施与验证边界见其 [验收记录](../../specs/spec-012-assistant-documents/acceptance.md)。用户已授权将本轮改动 commit／push 到 `dev`；实际提交与远端检查状态以 Git／GitHub 为准，无运行中的子 Agent。

- 用户确认 PDF、DOCX、PPTX、TXT、JSON、MD、CSV 均在首版；不做扫描件 OCR；用途为会话内总结／问答／待确认工作信息；存储采用私有磁盘＋PostgreSQL，并将“语音文件”入口改为“文件”。无待确认问题，不重复询问。
- 选型理由见[决策 0013](../decisions/0013-document-ingestion.md)，模块与验证安排见 [Plan](../../specs/spec-012-assistant-documents/plan.md)。决策由主 Agent 独立完成，业务按多 Agent 流程实施；未来 OCR 配置不提前加入。
- 前一轮 Spec 011 及搜索图标修复已提交推送 `dev`：`1deeb7f`；原资料与配置保留，验收边界见其[记录](../../specs/spec-011-web-function-management/acceptance.md)。不把文件解析扩展为公司级知识库、跨员工 Agent 问答或 Electron 功能。
- 本轮已按 S3／S2 完成相关定向验证，专用测试库与日常资料分离，迁移前备份。未运行 CI 或真实付费模型；Windows 仅有资源限制接口替身检查，未做实机验证。CI 测试库名称已与专用库保护统一。Git 合并与回同步由用户决定，见[规则](../rules/git-branch-workflow.md)。

## 日常环境

公司入口 `npm run dev:company`：Web 5174、API 8000 和 worker；状态需实际查询，不沿用历史进程／浏览器 tab ID。开发 PostgreSQL 容器 `paa-company-postgres`、库 `paa_company`，schema `0004_documents`（升级前已备份，19 张原业务表旧字段摘要不变，见 Spec 012 实施摘要）；测试库独立为 `paa_company_test`，Python `.venv-server`。本机 FFmpeg 曾放在 `artifacts/spec008/tools/ffmpeg`，不要将整个 artifacts 目录视作可删除缓存。

`.env.company`、`data/company/` 的凭证／数据库、模型主密钥及本地截图不打印或上传。Spec 009 的真实文字／周报联调使用范围见其 [实施记录](../../specs/spec-009-company-model-services/implementation.md#用户直接修复与真实联调2026-09-12)，授权不自动扩展到其他真实调用。Electron 仍以 `npm run dev` 使用默认日常资料。
