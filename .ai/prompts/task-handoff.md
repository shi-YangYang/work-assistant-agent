# Task Handoff — 当前状态

2026-09-12 · [Spec 009：公司级模型服务管理](../../specs/spec-009-company-model-services/spec.md) 独立工程复验已通过。用户随后要求直接修复 Web 控件／提示并授权真实文字与报告联调，主 Agent 已完成，无新 Spec／子 Agent；增量缺陷修复、5 项定向回归与最终真实 PASS 见 [实施摘要](../../specs/spec-009-company-model-services/implementation.md)，旧独立结论范围见 [验收报告](../../specs/spec-009-company-model-services/acceptance.md)。

## 下一步与交付边界

- 用户本次明确授权使用 Electron 已配置的基元律动，只测试文字与报告。`glm-5.3-flash` 流式实际完成上报、人工确认／纠正、补充关联、两版历史与周报来源；含排错累计文字 23 次、报告 4 次，原始证据在忽略的 `artifacts/spec009/real-integration*.json`。临时凭证已撤销并恢复原环境配置来源，测试资料保留；后续不能自行扩大这次授权。
- 用户已确认的产品与协议决策见 [决策 0012](../decisions/0012-company-model-services.md)，不重复询问。已有 Electron 配置与资料保持独立；Web 风格继续遵循 [决策 0009](../decisions/0009-interface-design-direction.md)。
- 继续遵守 [Spec 工作规则](../rules/spec-decision-workflow.md)：Spec 决策由主 Agent 完成，业务实施／独立验收分工；直接修改不派子 Agent；问题使用普通文本集中提出。

## Git

本次交付基于 `7441f62`，包括 Spec 009 与用户验收后的直接修复，用户已要求提交并推送 dev。实际提交号和远端状态以 Git 与对应 CI 记录为准。按 [固定 dev 规则](../rules/git-branch-workflow.md) 提供 dev → main 的 PR 链接，由用户合并；不自动合并或回同步，不重复已经通过且内容未变的检查。

## 本机运行与验证

- 日常 Web：`npm run dev:company`，主 Agent 会话 42538；Web http://127.0.0.1:5174，API 8000。API／worker 已重启加载最终事务修复；CUA tab 4 保留管理员登录，打开真实周报 http://127.0.0.1:5174/reports/416d2587-0b7e-44dd-986d-2bbf57e99797 ，浅色、默认 viewport。
- PostgreSQL 17 容器 `paa-company-postgres`；开发库 `paa_company` 已先备份再迁移至 `0002_model_services`，原实体数量保持；自动测试只使用 `paa_company_test`。开发迁移证据与备份在忽略的 `artifacts/spec009/`。
- `.env.company`、`data/company/postgres.env` 和 `data/company/review-access.txt` 为私有本机文件，不得打印。模型主密钥已在默认忽略路径初始化，权限 0600，未读取内容。服务端使用 `.venv-server`；FFmpeg 指向 `artifacts/spec008/tools/ffmpeg`。
- 正常 Web 已验证目录、图文／工具、文件 ASR、密钥保护、用途及深浅／宽窄布局。固定网关已停止，临时源站放行已撤销；仅本轮建立的验收服务和空用途已清理，恢复原环境配置来源。证据在忽略的 `artifacts/spec009/web-verification.json`。
- Electron 沿用项目目录 `npm run dev` 和默认用户资料。本次经用户授权，通过 safeStorage 在内存解密指定基元律动配置用于临时真实测试，未输出密钥或修改 Electron 原配置；未读取会议／录音，未运行桌面或安装包检查。

真实图片／ASR、长期业务质量、生产部署／恢复／容量及实体手机仍待外部验证。单个合成业务场景不代表普遍准确率。其他历史 Spec 状态见 [索引](../../specs/README.md)，本轮未自动恢复旧暂停项。
