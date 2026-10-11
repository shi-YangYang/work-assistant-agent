# Final Acceptance

## Result

**PASS**。首次验收发现的审计辅助模块独立导入回归已消除；本次目录迁移范围内没有未解决的返工项。后端既存的两个日期假设失败仍然存在，本结论不表示后端全套测试全绿。

## Scope

- 本轮由新的独立验收 Agent 复核，未修改业务、测试或脚本源码。原结构迁移按 S3 验证；本轮 S1 返工仅补足审计支持模块的依赖初始化，复用已完成的定向收集结果，不重复运行全量检查。
- 已读取 Spec、Plan、实施报告、首次验收、返工要求及返工报告。首次验收对 285 个文件迁移、108 个辅助定义提取、生产行为／契约等价、fixture 门禁、扫描范围和当前文档的复核继续适用；本轮未重新执行该整套验收。
- `tests/server/_support/http/agent_audit_api.py` 的 `Path(__file__).resolve().parents[4]` 正确定位仓库根目录，随后只加入实际依赖的 `scripts/company/web-acceptance/agent-audit`。初始化位于 `from faults import evidence` 之前，已有路径不会重复加入。
- 对照迁移前的 `test_agent_audit_api.py`，该初始化补回原导入链的前置条件；`evidence` 继续使用 `faults.py` 的原函数，没有复制证据写入逻辑、反向导入测试文件、注入业务子目录或恢复旧路径转发层。两个调用者、测试断言、fixture 和故障门禁不因本轮返工改变。
- 首次 [FAIL 报告](acceptance.md) 与失败日志保留，作为原回归证据。

## Tests

本轮只核对源码及已有日志，未新增测试执行。返工报告记录两个项目入口进程分别清除继承的 `PYTHONPATH`；独立日志均显示正常收集并以 0 退出。

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 人设审计文件独立收集 | **通过：4 个用例收集成功**；未执行正文 | [收集日志](../../artifacts/spec061/rework-audit-persona-collection.log) |
| 工具边界审计文件独立收集 | **通过：8 个用例收集成功**；未执行正文 | [收集日志](../../artifacts/spec061/rework-audit-tool_edges-collection.log) |
| 首次独立收集 | **历史失败：2 个导入错误**；已由上述返工消除 | [原失败日志](../../artifacts/spec061/acceptance-audit-collection.log) |
| 迁移与等价检查 | 后端 1,695／Web 630 个用例映射一致；5,284 条断言不变；100 个 API 路径、34 个工具契约不变；生产非路径逻辑与 CSS 无差异 | [首次验收](acceptance.md)、`artifacts/spec061/` 等价检查记录 |
| Web 测试、类型、改动文件格式／Lint、构建 | **通过**；Web 69 文件、630 用例通过，本轮未重跑 | [实施报告](implementation.md)、[Web 日志](../../artifacts/spec061/web-tests.log) |
| 后端子系统测试 | **1,677 通过、16 跳过、2 失败**；本轮未重跑 | [后端日志](../../artifacts/spec061/server-tests.log) |
| HEAD 旧源码同用例复验 | **2 个参数变体同样失败**，支持其为既存问题 | [基线日志](../../artifacts/spec061/baseline-legacy-report.log) |
| Sandbox 协议／流式 fixture 定向检查 | **14 通过／3 通过、1 跳过**；本轮未重跑 | [协议日志](../../artifacts/spec061/sandbox-protocol.log)、[流式日志](../../artifacts/spec061/stream-fixture-project-entry.log) |
| 桌面／390px 布局与交互 | 真实 Vite、受控 HTTP fixture 下通过；几何记录一致，本轮未重跑 | [浏览器记录](../../artifacts/spec061/ui/checks.md) |

16 项后端跳过沿用原有环境门禁，包括独立 Redis 故障、审计故障／并发、真实 gVisor、旧隔离基础设施和真实租约恢复；这些用例没有执行，不计为通过。真实模型／ASR、完整 Electron 打包及远端 CI 未执行。未 commit／push。

## Issues

- 原 P2 导入问题已关闭：两个文件可各自独立收集，不再依赖其他审计测试先加载。
- `test_legacy_report_binding_recovers_submission_identity_from_owned_receipt[False/True]` 仍失败：固定日报日期为 `2026-10-10`，验证时在 `2026-10-11` 创建当日工作，实际状态为 `succeeded`，断言期望 `running`。同环境旧源码复现相同失败，属于既存日期假设问题，未扩大本次范围修复。
- 受控 UI 证据不代表真实后端或模型质量；未启用的故障场景保留原有验收限制。

## Required Rework

无本次目录迁移范围内的必要返工。已通过检查不再重复执行，两个既存失败继续如实保留。
