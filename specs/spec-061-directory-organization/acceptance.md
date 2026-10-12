# Acceptance

## Result

**FAIL**。目录迁移、生产行为等价与既有回归证据总体符合 Spec，但测试辅助提取引入了依赖收集顺序的导入错误，两个审计测试文件无法独立收集，需要修复后由新的独立验收 Agent 复核。

## Spec Coverage

- 迁移清单记录 285 个文件的唯一目标；Web 组件与私有 CSS、Hook、后端职责子包和测试领域归属符合 Plan，新增 Python 包入口为空。未发现本轮范围外的业务重写或旧位置转发层。
- 已复核生产 Python／Web 等价检查的实现及结果：Python 排除导入后 AST 一致，Web 只规范化可解析的文件路径，CSS 内容一致；工具注册列表与导入顺序保持不变。100 个 API 路径与 34 个工具的完整契约快照一致。入口、ORM、任务上下文、持久化完成契约及迁移版本保持原位。
- 已独立对照辅助定义与迁移测试函数的 AST 差异：除导入及资源路径适配外，提取的辅助实现保持原逻辑；进程恢复场景增加显式 `probe` 参数，替代原来修改模块 `__file__` 的定位方式。根 `conftest.py` 未修改，Redis 文件专用 fixture 保留原位，`fast_nodes` 保留显式导入，故障环境门禁与参数化保留。
- 1,695 个后端用例和 630 个 Web 用例的映射，以及 5,284 条后端断言的等价证据无缺失；但全量发现通过不足以证明独立文件入口可用，见下述导入回归。
- 审计扫描改为递归，并静态追踪 `_support` 导入，不执行支持模块、不把它们收集成测试。135 个测试文件的原 API 候选无丢失；默认审计仍选择 103 文件，排除名单未变。
- 当前架构与技术栈文档已更新；启动命令、测试命令、部署配置、数据库 schema、历史报告和用户配置未因本次整理修改。
- 浏览器几何记录与受控交互证据支持迁移后页面行为保持；本轮未另行启动浏览器或重跑已完成的子系统检查。

## Tests

本次按 S3 结构迁移验收，复用实施证据，仅对明确的导入疑点追加只收集检查。以下路径均以 `artifacts/spec061/` 为根。

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 迁移前后后端／Web 发现 | 1,695／630 个用例映射一致 | `pytest-before.txt`、`pytest-after.txt`、`web-before.json`、`web-after.json` |
| 契约与生产代码等价 | 100 个 API 路径、34 个工具契约一致；生产非路径逻辑和 CSS 无差异 | `contracts-before.json`、`contracts-after.json`、`production-python-equivalence.json`、`production-web-equivalence.json` |
| 后端断言及审计选择 | 5,284 条断言相同，默认选择及排除范围不变 | `server-assertion-equivalence.json`、`inventory-equivalence.json` |
| Web 类型、改动文件格式／Lint、构建 | 通过 | `typecheck-web.log`、`format.log`、`lint-changed.log`、`build-web.log` |
| Web 测试 | 69 文件、630 用例通过 | `web-tests.log` |
| 后端子系统测试 | **1,677 通过、16 跳过、2 失败** | `server-tests.log`、`server-tests.xml` |
| 旧源码中同一失败用例 | 两个参数变体同样失败 | `baseline-legacy-report.log` |
| 补执行 sandbox 协议 | 14 通过 | `sandbox-protocol.log` |
| Redis fixture 原位保留后的项目入口定向验证 | 3 通过、1 跳过 | `stream-fixture-project-entry.log` |
| 桌面／390px 页面布局与交互 | 真实 Vite、受控 HTTP fixture 下通过；几何记录一致 | `ui/checks.md`、`ui/before-geometry.json`、`ui/after-geometry.json`及截图 |
| 本轮追加的两个审计文件独立收集 | **2 个导入错误，未收集到用例** | `acceptance-audit-collection.log` |

追加命令：

```sh
npm run test:server -- --collect-only tests/server/audit/test_agent_audit_persona.py tests/server/audit/test_agent_audit_tool_edges.py
```

后端原有两个失败为 `test_legacy_report_binding_recovers_submission_identity_from_owned_receipt[False/True]`：用例固定报告日期 `2026-10-10`，运行发生在 `2026-10-11`，创建的当日工作不在报告期间，实际状态为 `succeeded` 而断言期望 `running`。基线 HEAD `9a0de564e868062376f805446573717021492c86` 在相同隔离环境复现同一失败，属于既存日期假设问题，不是本次迁移回归，也不能标记为通过。

16 项跳过沿用原有环境门禁：独立 Redis 故障 1 项、要求精确归属环境的审计故障／并发 8 项、真实 gVisor 3 项、旧隔离基础设施 3 项、真实 90 秒租约恢复 1 项。未启用这些场景。早先直接 pytest 定向调用缺少子进程 `PYTHONPATH` 的失败保留在 `stream-fixture-check.log`；已由项目入口定向结果区分，不视为产品通过。

未执行真实模型／ASR、完整 Electron 打包或远端 CI；UI fixture 结果不代表真实后端或模型质量。

## Issues

### P2：审计辅助模块丢失独立导入所需的路径初始化

`tests/server/_support/http/agent_audit_api.py:2` 直接执行 `from faults import evidence`，但 `faults.py` 位于 `scripts/company/web-acceptance/agent-audit/`，不在项目测试入口默认的模块搜索路径内。

原来两个调用者从 `test_agent_audit_api` 导入 `evidence` 时，会先执行该测试文件的审计脚本路径初始化。迁移后改为导入新支持模块，却未保留这个前置条件。因此 `tests/server/audit/test_agent_audit_persona.py:15` 和 `tests/server/audit/test_agent_audit_tool_edges.py:20` 在没有其他审计文件先行导入时均报 `ModuleNotFoundError: No module named 'faults'`。全量收集先加载了包含初始化的其他文件，因此掩盖了该回归。

该问题违反测试入口可解析、辅助代码独立归属及不依赖测试导入顺序的要求，需要返工。

## Regression Risks

- 当前确定的迁移风险是按文件或按 node ID 运行上述审计用例会在收集阶段失败；不能以全量通过的部分结果替代修复。
- 已有日期假设失败限制后端“全绿”结论，但基线复现支持其与此次迁移无关，应保持独立记录。
- 未启用的破坏性／真实服务场景仍保留原有运行限制；本次静态复核确认门禁与断言保留，不声称这些场景运行通过。

## Required Rework

1. 使审计 `evidence` 辅助入口能通过项目测试入口独立导入，明确承担其对审计脚本的依赖；不反向导入测试文件，不恢复旧路径转发壳，也不通过预加载其他测试掩盖顺序依赖。
2. 用上述两个文件的只收集命令验证修复；检查通过后，无需为该局部修复重跑整个后端或 Web 套件。
3. 由新的独立验收 Agent 复核修复与定向结果，更新最终验收结论。
