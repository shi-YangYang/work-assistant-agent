# Implementation Report

## Summary

完成计划内目录归类、导入适配、测试辅助提取、扫描脚本及当前架构文档更新。未修改产品行为、样式内容、模型提示词、工具契约、执行策略、数据库 schema 或用户配置；未 commit／push。

实施基线为 `9a0de564e868062376f805446573717021492c86`。以下为实施验证记录，不代替独立验收。

## Files Changed

| 范围 | 现有文件迁移数 | 目标归属 |
| --- | ---: | --- |
| Web 源码 | 30 | 输入附件与控制项、会话控制项、转写、四类 Hook |
| 后端源码 | 39 | 业务／资料／流程／沙盒工具、引用、交付辅助、工作／消息／报告子域 |
| 后端测试与辅助 | 148 | Agent、业务、任务、集成、契约、场景、审计、支持模块和 probes |
| Web 测试 | 68 | 普通测试与 DOM 测试分别按功能归组 |

共迁移 285 个文件，旧位置没有转发壳或重复实现。具体文件对应关系见 `artifacts/spec061/migration-map.json`。

另从原测试文件提取 108 个共享辅助定义至 43 个 `_support` 模块，清单为 `artifacts/spec061/helper-extractions.json`。新增 Python 子包使用空 `__init__.py`；静态／动态导入、mock 路径、相对路径、基准脚本的 node ID 均已适配。

更新 `scripts/company/web-acceptance/{inventory.py,agent-audit/fixed.py,agent-audit/faults.py}`、相关基准脚本、`docs/architecture.md` 和 `constitution/tech-stack.md`。历史 Spec、历史验收证据未改。

## Important Decisions

- 同组件的 TSX 与私有 CSS 一起迁移。共享样式和加载顺序保持不变。
- 保留根 `conftest.py`、架构检查、Web setup／DOM helpers。已有文件专用 fixture 保留作用域；抽取的 `fast_nodes` 仍由原用例显式导入，未变成全局自动 fixture。
- 复用故障场景从测试文件移到支持模块，原测试保留参数化和跳过标记。进程测试的临时 probe 通过显式参数传入；所有数据库／容器归属保护及业务断言保持原样。
- 候选测试扫描除递归发现外，静态读取 `_support` 依赖，避免请求辅助移出测试后丢失 API 候选；此扫描不执行模块，不增加默认测试范围。
- 入口、ORM、任务上下文及持久化完成契约原位保留。不存在新增的旧路径兼容层，不需要数据迁移。

## Tests

验证使用自建、仅绑定本机回环地址的 PostgreSQL／Redis；数据库名为 `paa_company_test`。没有连接真实模型、真实麦克风或用户业务库。

| 检查／命令 | 结果 | 证据（均在 `artifacts/spec061/`） |
| --- | --- | --- |
| 迁移前后 `pytest --collect-only`，按路径映射比较 | 1,695 个用例 ID／参数变体一致 | `pytest-before.txt`、`pytest-after.txt` |
| 迁移前后 `vitest list` | 630 个用例一致 | `web-before.json`、`web-after.json` |
| OpenAPI 与工具快照 | 100 个 API 路径、34 个工具的名称／Schema／说明／顺序逐字节一致 | `contracts-before.json`、`contracts-after.json` |
| 生产 Python AST 对照 | 除导入外无变化 | `production-python-equivalence.json` |
| Web AST／CSS 对照 | 仅路径／格式变化，CSS 内容相同 | `production-web-equivalence.json` |
| 测试断言 AST 对照 | 5,284 条断言逐项相同 | `server-assertion-equivalence.json` |
| 测试发现及候选映射 | 135 个测试文件、默认审计 103 文件；原候选无丢失，排除名单不变 | `inventory-equivalence.json` |
| `npm run typecheck:web` | 通过 | `typecheck-web.log` |
| 本次修改文件的 Prettier 与 ESLint | 完成／通过 | `format.log`、`formatted-files.txt`、`lint-changed.log` |
| `npm run test:web` | 69 文件、630 用例通过 | `web-tests.log` |
| `npm run build:web` | 通过 | `build-web.log` |
| `npm run test:server` | **1,677 通过、16 跳过、2 失败**，490.86 秒 | `server-tests.log`、`server-tests.xml` |
| HEAD 旧源码单独复验相同失败用例 | 两个参数变体同样失败，确认不是迁移引入 | `baseline-legacy-report.log`、`baseline/` |
| `npm run test:server -- --sandbox-protocol` | 14 通过；补执行完整命令被前段失败阻止的协议段 | `sandbox-protocol.log` |
| `npm run test:server -- tests/server/agent/streaming/test_reply_stream_transport.py` | 文件专用 fixture 保留原位后的定向验证：3 通过、1 跳过 | `stream-fixture-project-entry.log` |
| 桌面／390px 浏览器核对 | 受控 HTTP fixture 下的布局及交互正常，迁移前后 geometry 一致 | `ui/checks.md`、`ui/` 截图 |
| 路径／支持模块检查、diff 检查 | 285 个目标唯一、旧文件不存在、当前路径无残留；支持模块不反向导入测试，diff 无空白错误 | 迁移清单及检查脚本 |

最初直接调用 pytest 的流式定向复验缺少项目入口为子进程设置的 `PYTHONPATH`，出现 `ModuleNotFoundError: app`；未改代码，改用项目 `npm run test:server` 入口后通过。该次命令错误保留在 `stream-fixture-check.log`，不当作业务失败或通过。

16 项跳过沿用已有条件：1 项独立 Redis 破坏性场景、8 项要求精确归属环境的 Agent 审计故障／并发场景、3 项真实 gVisor 场景、3 项旧隔离基础设施场景、1 项真实 90 秒租约进程恢复。未启用这些手动故障环境，未修改门禁以获得通过。

## Known Limitations

后端全量检查未全绿：`test_legacy_report_binding_recovers_submission_identity_from_owned_receipt[False/True]` 用例固定生成 `2026-10-10` 日报，却使用真实当前日期创建工作。本次运行日期为 `2026-10-11`，期间没有对应工作时得到空报告的 `succeeded`，与用例预期的 `running` 不同。相同 HEAD 旧源码、相同隔离环境得到完全相同失败。按本次纯结构整理范围记录，未修改日期、断言或业务。

浏览器验证使用真实 Vite 和隔离的内存 HTTP fixture，未声称验证真实后端／模型质量。没有执行完整 Electron 打包、真实模型质量／性能评测或远端 CI。

## Test Environment Handoff

最终独立验收结束后，已按记录核对容器 ID 并删除下述两个自建容器。临时 UI 页面与服务器也已关闭；以下保留验证环境归属记录。

供独立验收复用的配置在 `artifacts/spec061/test.env`（仅本地、权限 `0600`）；容器 ID、镜像和端口归属在 `artifacts/spec061/test-environment.json`：

- `noria-spec061-postgres`：`127.0.0.1:25432`，专用 `paa_company_test`。
- `noria-spec061-redis`：`127.0.0.1:26379`。

验收结束后，核对 ID 与清单一致，再删除本次自建容器：

```sh
docker rm -f noria-spec061-postgres noria-spec061-redis
```

没有启动用户 API／worker，没有更改用户本地 `.env`、密钥或数据卷。主 Agent 的隔离 UI 服务已经关闭。

## Remaining Questions

无本次迁移范围内已知待返工问题；等待新的独立 Agent 验收。上述两个既存日期假设失败与未启用的手动场景不得表述为通过。
