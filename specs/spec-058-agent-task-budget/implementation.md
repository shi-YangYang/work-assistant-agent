# Implementation Report

## 结果

新增内部任务预算模块，聊天每轮为 1,800 秒、64 次逻辑工具、96 次实际模型请求；预留 3 次模型请求与 120 秒收尾。策略按轮次冻结，worker 从附件准备前起算，恢复和 scope 变化不重置；主动重试保留业务回执并新开预算。

工具自动重试只计一次，模型重试、ASR、授权、内容转换、压缩及协议兼容重发逐次预占。模型用量与预算共用已有事务；图上限为 `8 × 模型次数 + 16`，节点容量为 `4 × 工具次数 + 模型次数 + 32`。总截止独立于原 60 秒静默限制，独立报告和沙盒政策不变。

每轮主模型收到最新临时尾消息，历史、checkpoint、记忆与固定 system 前缀不保存预算。收尾关闭新探索，已经接纳的工具可在探索池内完成必需子调用。实际收尾沿用“整理答复”节点；没有新增公开额度字段或 UI。软收尾可用隐藏 `remaining` 说明未完成项，服务端拒绝项不能被抹掉；硬截止仅交付来源有效的正文片段、文件、业务回执，状态为 partial／blocked。

实际文件清单见 [plan.md](plan.md)。没有修改生产配置、CD、前端、共享 API 类型、正常 API 或 worker 进程；没有提交或推送。

## 验证

S3：核心执行基础设施及持久化。以下按命令分别计数，存在重叠，不累加为唯一总数。

| 检查 | 结果 |
| --- | --- |
| `test_task_budget.py` 初版 + `test_response_delivery.py` | 50 passed |
| 预算、真实图、正文协议、重试、流期限、进度、架构定向集 | 116 passed；2 个测试适配问题随后修正复验；1 个 HEAD 既存架构失败；3 个旧协议断言排除并单独验证基线 |
| 兼容重发、手动续接、中断、工具目录、记忆、Redis 协议 | 32 passed，4 skipped；工具目录 1 个旧额度断言已适配复验；1 个人设长度断言是 HEAD 既存失败 |
| 最后边界：421s/34工具/36模型、最后模型失败与 SSE、能力发现 | 3 passed |
| Web：`task-progress`、DOM `task-progress`、`job-connection` | 37 passed |
| Chromium：1440/390 正常流、390 中断 | 3 passed；展开不折叠、无新增 GET、旧事件不复活、无横向溢出 |
| `git diff --check` | 通过 |

新预算覆盖 64/96 边界、2 个余量并发 5 个请求、93 次探索后收尾、辅助模型隔离、scope/worker/手动恢复、安全片段与过期片段、中断和其他账号并行。SSE 与普通 DTO 不暴露内部字段。Python 没有配置项目格式化器；沿用现有 Python 风格，未修改格式化器覆盖的 TS/JS 源码。

证据：`artifacts/spec058/{budget-regression,targeted-regression,final-boundaries}.log`；浏览器 `artifacts/spec058/ui/browser/`。

## 真实模型与沙盒

使用本地 admin 已保存配置，通过应用正常模型接入执行；业务、会话、记忆、checkpoint 均为 `paa_company_test` 隔离账号。HEAD 源码基线与修改版同输入、同服务、low 强度，各执行一次，不评价一般知识或字数质量。

| 旅程 | 基线总耗时 | 修改后总耗时 | 模型请求（前/后） | 工具（前/后） | 实际结果 |
| --- | --- | --- | --- | --- | --- |
| 普通问答 | 4.849s | 4.102s | 1/1 | 0/0 | 完整答复 |
| 三个官方网页研究 | 16.654s | 19.746s | 3/3 | 3/3 | 网页来源和答复 |
| 创建工作后给建议 | 24.659s | 15.314s | 4/4 | 1/1 | 一条工作和建议 |
| 生成 Excel | 15.279s | 12.362s | 3/3 | 1/1 | 实际沙盒文件下载 200；甲100、乙200、合计300 |

普通问答 worker SQL 为 650→658；其余为 1691→1660、1609→1612、1441→1409。没有新增模型往返或逐 token 预算写入。首个候选正文时间为服务端观测，不等同浏览器首字；单次模型波动不能证明稳定提速。

证据：`artifacts/spec058/real-{baseline,after}.jsonl`，包含回复、节点、用量、计时和 Excel 回读。未进行真实 30 分钟等待或付费撞上限，受控图与注入时钟负责边界。

## 既存失败与限制

以下均用冻结 HEAD 代码复现，未扩大修复：

- `test_task_retry.py` 三个旧用例期待普通文字强制进入 `finish_task` 并共调用三次；现有正文直出只调用一次。
- `test_tool_catalog.py::test_ordinary_prose_has_only_catalog_once_and_keeps_clock_role_mode` 期待固定 system 少于 1800 字符，现有人设为 2914；本次预算只追加临时尾消息。
- `test_architecture.py::test_dependencies_are_acyclic_and_do_not_import_entrypoints` 的 `reply_stream ↔ publisher` 既存循环。

证据：`baseline-existing-failures.log`（预先导入归档 app 包以防 fixture 改写路径）、`baseline-architecture.txt`。Redis 跨进程／重启 4 项 opt-in 测试未启用；本次未改 Redis 协议。没有重跑完整 Web/API 套件或完整混合多轮破坏性旅程。

临时浏览器服务、schema、凭据和 HEAD 源码归档已清理；保留精简 JSON、日志与截图。测试前还定向清理了专用测试库中一个遗留受控租户 `受控测试公司 e6d3ac2c`，其旧加密密钥导致其他 fixture 启动校验失败；没有清库或触碰日常公司数据。独立验收由新的验收 Agent 执行，本报告不声明验收 PASS。
