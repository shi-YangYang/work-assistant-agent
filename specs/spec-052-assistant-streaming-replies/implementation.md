# Implementation Report

## Summary

- 模型客户端提供可选协议增量回调，仍在完整响应、结束标记和参数校验后才返回框架消息；非流式调用不伪造增量。完整工具 JSON 和预览均拒绝重复键。
- 独立词法解析器只提取唯一 `finish_task.answer`，支持任意切块、字段乱序、转义和 Unicode，限制参数与正文长度；混合工具、重复键和损坏参数撤销候选。
- 正文通过既有 JSONB／SSE 保存最新完整前缀，独立 generation、约 200 ms 合并、首尾即时刷新。发布和读取检查归属、租约、来源版本及资料范围，团队资料保持完整核对后交付。
- 阶段与节点更新保留正文；自动／手动重试撤销旧候选。普通网络失败、中断与 worker 失联封存片段；内容拦截、无效参数和资料失效撤下。正式消息事务完成后发布终态。
- 前端复用共享 SSE 与 Markdown；完成事件先到、单次消息同步失败或延迟时保留前缀。取消 POST 携带服务端封存的授权片段，避免新 fence 先到造成空白。权限失效立即撤下，旧轮结果不覆盖新轮。

## Files Changed

实际目录及职责见 [Plan 改造目录](plan.md#改造目录)。未修改数据库 schema、部署配置或聊天滚动器；复用现有 `RunContext` 来源状态、`ResizeObserver` 和订阅连接。

## Important Decisions

- 模型内容与工具执行保持独立；增量回调从不调用工具，不写 `Message.reply`、历史上下文或记忆。
- 正文快照的私有来源版本与 call ID 留在服务端；所有公开读取经统一授权 DTO 过滤。仅取消响应可在 `Job` 上带授权预览，通用任务 DTO 不透传 JSONB。
- 内部专项核对／修复不外显；普通核对网络失败可保留此前候选，审核拦截或无效核对格式撤下。
- 注销保持既有后台任务语义，不增加取消任务或跨登录会话绑定。注销验证证明旧 session 不能继续订阅／读取／显示预览，不证明后台任务停止写入受保护状态。

## Tests

验证级别 S3，限定共享模型传输、任务反馈／持久化、权限和 Web 助手子系统。命令、退出状态及工具输出摘录保存在 [implementation-checks.json](../../artifacts/spec052/implementation-checks.json)，这是已执行输出的摘要记录，不是完整原始 traceback。

- 后端首轮为 145 通过／8 失败；8 个失败修复或排除环境阻碍后，连同 4 个新故障场景定向运行 12 个通过，再新增 5 个协议场景通过。取消响应修改后单独重跑 1 个用例通过，不重复累计。因此累计 162 个唯一用例通过：`test_assistant_reply_stream.py`、`test_model_stream_errors.py`、`test_feedback_connections.py`、`test_message_interrupt.py`、`test_operation_recovery.py`、`test_response_delivery.py`、`test_task_retry.py`。按失败与后续变更范围分批运行，不重复整组已通过用例。
- 新增受控 HTTP 字节流可暂停供应商结束：普通／公开检索／本人材料三种路径均验证 SSE 出现至少两个递增前缀、首段读取小于 1 秒、供应商未结束时正式正文为空，结束后才持久化与交付。
- 覆盖随机／单字符分片、emoji 与转义、重复键／混合工具／长度限制、普通故障与内容拦截、自动和手动重试、取消与旧 fence、worker 失联、资料与权限变更、团队分片写入节流、非流式兼容和既有回执幂等。
- Web 累计 29 个唯一用例通过：`dom/assistant-streaming.test.tsx`、`list-feedback.test.ts`、`dom/assistant-task.test.tsx`。覆盖安全 Markdown、快照顺序、最终同步延迟／失败、取消 POST 先到、撤销、共享连接及无逐片段请求。
- `npm run typecheck:web` 和涉及源码／测试文件的 ESLint 通过；覆盖范围内文件已用项目 Prettier 格式化。

后端使用专用 `paa_company_test` 和隔离租户 fixture。已有测试库的全库密钥 witness 与临时 fixture 密钥冲突导致模型配置场景失败，未清理原库；改在临时 PostgreSQL 17 容器完成迁移并复测通过。另修复旧模型替身不带 `streaming` 字段的兼容性，未调整重试次数或降低断言。

## Known Limitations

- 上述供应商测试为受控协议验证，不代替真实模型。协调 Agent 的 [浏览器证据](../../artifacts/spec052/browser-check.json) 已覆盖 1440／390 宽度、真实 ResizeObserver、底部跟随／向上阅读保持、步骤展开与按钮 DOM 稳定、共享连接及无逐片段 GET。
- 协调 Agent 的真实模型／Caddy 检查已见公开检索 8 个前缀、追问 3 个前缀在模型返回前到达并完成交付；工作更新只增加一次 revision。修复前的长文章见 28 个真实前缀，但后续核对连续截断，未完成交付；该根因及修复验证见下方“长文核对截断修复”。证据见 [真实模型与代理](../../artifacts/spec052/real-streaming.json)。追加的纯创作长回答在 17.249 秒完成，19 个不同前缀均早于 `finish_task` 响应，正式回复持久化且任务 completed，见 [长回答证据](../../artifacts/spec052/real-streaming-long.json)。
- 未运行无关桌面、语音、模型下载、打包或全库测试；未提交或推送，未触发远端 CI。

## 团队成果来源返工

- 修复独立验收发现的断点：成果目录（含历史上下文和授权核对）、显式引用、正文读取、保存结果重放、执行记录中的成果引用和成果文件输入，均将已授权成果的访问范围及版本依赖保留到当前任务。不再依赖原任务成功结束时写入的 `Message.access`。
- 来源依赖保存在既有 `Job.result.deliverableSources`，与用于修改授权的正文读取记录分开。预览快照携带服务端私有依赖，发布和公开 DTO 读取均重新核对归属、会话、访问范围、当前版本、已读历史版本及生成文件来源；团队内容继续缓冲，普通个人成果的历史读取和连续修改仍可流式。不新增 schema、模型调用或前端行为。
- 正式回归新增 14 例，覆盖取消／失败 × 历史目录／工具目录／正文／显式引用，明确断言新任务继承 `team=true`；另覆盖成果版本、归属、团队范围和文件来源失效时反馈／消息 DTO 撤下正文，以及个人历史版本、连续保存和幂等恢复。团队成果仍可授权读取，真实 worker 配合受控模型能完成正式回复交付。
- 定向命令：`.venv-server/bin/python -m pytest tests/server/test_deliverable_reply_stream.py tests/server/test_deliverables.py tests/server/test_execution_history.py tests/server/test_sandbox_execution.py -q --tb=short`。在原临时 PostgreSQL 专用测试库执行，首轮 **39 passed / 1 failed**；唯一失败是新增测试误将无业务操作的纯回答终态断言为 `succeeded`，已按既有行为改为 `awaiting_input`，并核对 `taskOutcome.completed` 与正式正文，仅复测该例 **1 passed**，累计 **40 个唯一用例通过**。原始日志：[首轮](../../artifacts/spec052/rework-results.log)、[单例复测](../../artifacts/spec052/rework-final-delivery.log)。原验收 FAIL 工件保留。
- 项目格式化脚本不覆盖 Python 源码与 Markdown；沿用文件既有格式并检查改动 diff。未重复此前 162 个后端／29 个 Web 用例、真实模型或整仓构建，未提交／推送；此返工报告不替代新的独立验收。

## Remaining Questions

无产品决策遗留。独立验收由协调 Agent 安排；本报告不代表独立验收通过。

## 长文核对截断修复

- 原始长文候选的真实复核再次返回 `finish_reason=length`，2,000 个输出 token 全部消耗在推理，正文为零。仅保留用量与长度元数据，见 [预算证据](../../artifacts/spec052/review-budget-probe.json)。
- 模型传输仅对明确的 `length` 设置结构化标记，错误仍属于无效响应；完整外观但标记截断的 JSON 也不接受。专项核对在下一次既有节点重试中关闭已知混合模型的额外推理，保持同一提示、证据和结果验证。未知供应商保持原参数。
- 同一候选指纹的调整信息保存在既有 `replyReview`，任务恢复不重复已失败的推理模式；不同候选不继承。未提高 token、时间和重试上限，未放宽数值核对触发或权限。
- 新增 13 个回归覆盖流式／非流式与数值／事实／业务核对、真实矛盾仍被指出、截断／坏 JSON／内容拦截／未知结束原因、次数上限、恢复与新候选隔离、未知网关、计费记录和合法缓存。连同相关既有检查共 **56 passed in 13.71s**，见 [定向结果](../../artifacts/spec052/review-recovery-tests.log)。

- 原请求完整真实生成／代理流程在 17.80 秒完成，19 个前缀早于上游结束，见 [原请求复测](../../artifacts/spec052/real-review-recovery.json)。该次新文章没有触发数值核对，单独记录，不作为截断恢复命中证据。
- 固定重放原失败的 1,829 字候选，专项核对使用真实模型：首次开启推理消耗全部 2,000 token 后明确截断；下一次既有重试关闭推理，在同一 2,000 token 上限内返回有效核对 JSON，节点以 2 次尝试／1 次重试成功，正文完整入库，任务完成，共 28.24 秒。见 [固定候选真实核对](../../artifacts/spec052/real-review-frozen-candidate.json)。此流程的草稿来自原样本，只有核对是重新真实调用，不冒充全部重新生成。

## 实时正文平滑

新增 `useStreamingText` 私有 Hook，按字素边界逐帧展示实时新增内容，积压时加快、约半秒追平。首次挂载与恢复直接显示已有正文；完成、中断、撤回、换代、权限失效及减少动态效果时立即同步。仅调整 Web 展示，不改 SSE 频率、模型调用或滚动器。

S1 定向检查 `npm run test:web -- tests/web/dom/assistant-streaming.test.tsx`：25 项通过；改动源码已用项目 Prettier 整理。真实 Chromium 的 1440／390 视口分别观察到 31／30 个不同正文长度，516／504 ms 追平；底部跟随、上翻阅读保持、折叠状态、输入／中断按钮及安全 Markdown 正常，1 条 SSE、请求数 8→8、无页面错误。见 [浏览器证据](../../artifacts/spec052/browser-smoothing.json)。未重复后端、真实模型或全仓检查。
