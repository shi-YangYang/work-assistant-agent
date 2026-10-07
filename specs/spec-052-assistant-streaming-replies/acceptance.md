# Acceptance

## Result

PASS。新的独立验收已核对长文核对截断修复，原失败候选通过真实专项核对并完成交付。此前成果来源返工的通过结论与有效证据保留。

## Spec Coverage

- 首轮已独立审查协议回调、词法解析、租约、快照代际、取消与正式回复交接，以及共享 SSE／Markdown 展示。本人／公司隔离、重试、旧 fence、普通故障保留、协议失败撤下、非流式和旧消息兼容有定向证据；预览不执行工具、不进入正式历史、不增加逐片段 GET。此次未重复审查无关范围。
- 成果目录、历史上下文、显式引用、正文读取、保存结果重放、执行记录成果引用和成果文件输入，均在授权后登记成果范围及所读版本。`Job.result.deliverableSources` 独立于修改授权使用的 `deliverableReads`，不依赖原消息完成时才写入的 `Message.access`。
- 预览发布和公开 DTO 读取都重新校验成果归属、会话、访问范围、当前版本、已读历史版本及生成文件来源。团队来源缓冲到正式核对，失效来源撤下；个人历史版本、连续保存和幂等恢复仍可流式，授权成果仍可正常读取和正式交付。
- 注销沿用后台任务语义：旧 session 不再读取或显示预览，不新增注销取消。失败任务的业务回执卡与正文预览仍各自按既有规则交付。
- 只有明确的 `finish_reason=length` 触发核对恢复；同一候选与证据指纹的 `outputLimited` 随任务保存，下一次既有重试关闭已知模型的额外推理。新候选与配置／数据 scope 不继承旧标记，合法 verdict 才能缓存。未知供应商参数不变，完整结束、JSON、证据、权限与租约校验继续生效，重试次数、超时、输出上限及调用用量记录未放宽。

## Tests

- 复核返工源码、正式回归及原始日志：`test_deliverable_reply_stream.py` 新增 14 例，其中取消／失败 × 历史目录／工具目录／正文／显式引用共 8 例明确断言新任务继承 `team=true`，反馈和消息 DTO 均无候选正文；另 5 例覆盖版本、归属、团队范围、历史版本删除和文件来源失效，1 例覆盖个人历史版本、连续保存与幂等恢复。
- 返工定向命令覆盖上述文件及 `test_deliverables.py`、`test_execution_history.py`、`test_sandbox_execution.py`，累计 **40 个唯一用例通过**。日志为 [39 passed／1 failed](../../artifacts/spec052/rework-results.log) 后 [失败单例 1 passed](../../artifacts/spec052/rework-final-delivery.log)。唯一失败是将纯回答终态误写为 `succeeded`；修正为既有 `awaiting_input` 后仍要求 `taskOutcome.completed` 和正式正文，未降低业务断言。
- 复核 [实施检查摘要](../../artifacts/spec052/implementation-checks.json)：此前累计 162 个唯一后端用例、29 个唯一 Web 用例通过，Web typecheck、涉及文件 ESLint／格式化通过。首轮 8 个失败经修复或迁移到隔离数据库后定向通过。
- 复核 [浏览器证据](../../artifacts/spec052/browser-check.json)：1440／390 宽度，200 ms 快照节奏下无横向溢出，底部跟随与向上阅读、折叠状态、输入与中断按钮稳定；共享单条 SSE，正文更新未增加 GET。不推定任意高频更新均通过。
- 复核真实 `deepseek-v4.1-flash`／Caddy 证据：[普通流程](../../artifacts/spec052/real-streaming.json)、[长回答](../../artifacts/spec052/real-streaming-long.json)。999 字创作长回答完成，19 个不同前缀早于完整模型响应；公开搜索和追问分别有 8／3 个前缀并完成；工作更新 revision 只增加一次，该业务回执路径没有流式正文。受控供应商测试与真实模型结果分开记录。
- 长文修复按 S2 核对相关模块。复核 `test_reply_review_limits.py` 的 13 个新增用例及 [56 passed in 13.71s 原始结果](../../artifacts/spec052/review-recovery-tests.log)，范围包括相关既有数值、事实与协议测试。新增用例覆盖流式／非流式、完整外观但截断的 JSON、真实数值矛盾仍被指出、坏 JSON／内容拦截／其他结束原因、重试上限、任务重入与新候选隔离、未知网关、失败用量与合法缓存；没有重跑已通过测试。
- 复核 [原候选预算探测](../../artifacts/spec052/review-budget-probe.json) 和 [固定原候选的真实核对](../../artifacts/spec052/real-review-frozen-candidate.json)：1,829 字原失败正文首次核对耗尽 2,000 token，全部为推理、正文为零；同一节点第二次调用关闭推理，输出上限仍为 2,000，返回有效核对结果。review 节点 `attempts=2`、`retries=1`、`succeeded`，正式正文保存且 `taskOutcome=completed`，耗时 28.24 秒。复核执行脚本确认只重放草稿，专项核对使用真实供应商，再经 worker、PostgreSQL、API／Caddy 完成交付；此样本没有实时正文前缀，不作为真实生成流式证据。
- [原请求完整真实重跑](../../artifacts/spec052/real-review-recovery.json) 在 17.80 秒完成，19 个不同前缀在完整模型响应前到达。该次新生成正文没有触发专项数值核对，只证明完整实时生成与交付，不代替上述恢复分支证据。
- 本次独立验收复核修复源码、测试与真实执行证据，保留此前范围的验收结论；数据库测试使用临时 PostgreSQL 17 专用库与隔离租户。未运行无关桌面、语音、打包或全仓测试；未提交／推送，远端 CI 未触发。

## Issues

无未解决的本次实现问题。首轮发现的“团队查询→保存成果→中断→下一轮读取”来源丢失已修复；原消息没有团队范围时，新任务仍从成果本身继承限制并缓冲正文。保留首轮 [最小复现](../../artifacts/spec052/test_acceptance_team_deliverable.py) 与 [失败输出](../../artifacts/spec052/acceptance-team-deliverable.txt)；其中 `assert not job.access.team` 用于证明旧断点，修复后的正式回归已改为正向继承断言，未原样重跑旧复现。

原真实长文的核对截断已由固定同一正文、真实核对与正式交付证据闭环；旧失败工件保留，不将旧样本改写为成功。

## Regression Risks

- 恢复策略仍可能遇到供应商持续截断或格式错误，达到原重试上限后继续阻止交付并撤下候选；通过原失败样本不表示任意模型与输入都能恢复。未知供应商不推测参数。
- 团队来源继续不支持提前流式展示，这是规格保留的完整权限／引用核对边界；未扩大其授权或更改数据库结构。

## Required Rework

无。

## 实时正文平滑展示

PASS。按 S1 独立审查 `useStreamingText`、`AssistantReply` 集成及相关测试。仅新收到的实时前缀按字素边界展开，积压时加速；已有快照直接恢复，完成／中断立即追平，撤回、权限失效和轮次变化清除旧队列，减少动态效果时直接显示。未改变后端、请求或滚动机制。

- 实施 Agent 的定向命令 `npm run test:web -- tests/web/dom/assistant-streaming.test.tsx` 为 **25 passed**；覆盖中间帧、突发追平、组合字符、恢复、终态、身份切换、撤回、卸载与动态效果偏好。本次验收未重复执行已通过检查。
- 复核 [浏览器结果](../../artifacts/spec052/browser-smoothing.json) 与脚本、桌面／手机截图：真实 Chromium 在 1440／390 宽度分别出现 31／30 个中间长度，约 516／504 ms 追平；无横向溢出，底部跟随、上翻保持、步骤展开、输入与中断按钮稳定。两者均为单条 SSE，正文更新期间请求数 8→8，浏览器错误为空。该检查使用受控 SSE 输入与真实页面渲染，不重复调用模型。
- 无需返工；未提交／推送，未触发远端 CI。

## 普通正文协议补齐的实时输出

PASS。独立核对 `allows_reply_stream` 与模型调用入口：仅首轮将非空普通正文包装为强制、唯一 `finish_task` 时开放 `answer` 增量；引用纠错、遗漏操作修复、修复后的再次模型交互、内部专项核对及团队来源仍缓冲。既有工具执行、完整响应校验、来源授权与正式交付流程保持不变。

- 复核定向测试与原始日志：[首轮 9 passed／1 failed](../../artifacts/spec052/protocol-stream-focused-tests.log)、[团队单例复测 1 passed](../../artifacts/spec052/protocol-stream-team-test.log)，累计 10 个唯一用例通过。普通正文和公开搜索后正文两条路径均在供应商暂停结束时收到两个递增前缀，正式正文仍为空；协议补齐保持既有请求次数、搜索只执行一次且无业务操作。8 个边界用例核对纠错／私有调用不提前发布。首轮团队用例只改内存范围，被租约加载的数据库状态覆盖；改为持久化团队范围后单例通过，未降低断言。
- 复核 [真实协议补齐结果](../../artifacts/spec052/real-protocol-stream.json) 与 [执行脚本](../../artifacts/spec052/real_protocol_stream.py)：首轮重放用户原请求的 1,473 字已保存正文，以固定命中普通正文补齐路径；随后由已配置真实模型生成 `finish_task`，经 worker、PostgreSQL 和 Uvicorn HTTP SSE 传输。首段在 5.576 秒可见，补齐调用在 15.108 秒返回之前已收到 18 个不同长度的正文前缀，最终正文持久化且任务完成。此证据仅将补齐阶段视为真实模型生成，不声称首轮正文重新生成，也不将该次 Uvicorn 链路称为代理复测。
- 本次验收只读业务代码并复核上述证据，未重复已通过测试或无关检查。无需返工；未提交／推送，未触发远端 CI。
