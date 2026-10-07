# Plan：工作助手正文流式输出

对应 [Spec](spec.md)。已实施，独立验收通过。

## 方案与数据流

```text
模型 HTTP 流
  → 通用协议增量与完整响应装配
  → Agent 筛选、解码 finish_task.answer
  → 租约与范围检查、合并写入 Job.feedback.replyStream
  → 现有 /jobs/{id}/events 快照
  → 共享订阅 → 同一个回答区域的 Markdown 预览

完整响应 → 完整工具／收尾验证 → 既有答复核对、引用和回执
  → 正式 Message.reply 落库 → 终态 → 一次消息同步替换预览
```

不增加额外模型调用。保留 `finish_task` 终结协议，不能把普通模型 `content` 或整段工具 JSON 当答案。模型回调与 LangGraph 的完整工具执行分开；单改 `_astream` 或设置开关不足以完成接入。

## 模块边界

1. **协议层**：`chat` 新增可选增量回调，输出文本／工具参数分片的标准事件，保留原完整返回、用量统计和错误分类。调用方不开回调时行为不变。
2. **Agent 输出层**：独立有界解码器提取单个 `finish_task.answer`，管理候选 ID、格式异常与撤销；只在可预览任务调用中启用。与完整收尾校验使用同一字段和长度约束。
   普通正文的协议补齐允许输出 `answer`，沿用强制 `finish_task` 的工具边界；引用纠错、遗漏操作修复和内部核对保持缓冲。
3. **反馈层**：集中管理正文状态，保留 `update_feedback()` 中新增字段；节点、压缩、工具和正文互不覆盖。所有写入用既有租约检查，不跨网络等待持有事务。
4. **消费层**：`job-feedback.ts` 统一处理新字段和顺序；MessageCard 把预览／正式正文交给独立展示组件。滚动沿用已有 ResizeObserver，不让 token 更新触发消息 GET。

## 数据与接口

`Job.feedback.replyStream` 保存最新候选快照；`JobFeedback.replyStream` 和本人消息 DTO 的可选 `replyStream` 使用相同结构，供 SSE 和刷新恢复读取。取消响应的 `Job.replyStream` 只经相同授权 DTO 生成，携带新 fence 已封存的片段以跨越最终消息请求的延迟；通用 `job_dto` 不透传预览。正式历史正文仍只有 `Message.reply`。

建议结构：

```ts
type ReplyStream = {
  version: 1
  generation: number
  state: 'streaming' | 'finalizing' | 'interrupted' | 'withdrawn'
  text: string
}
```

- 输出身份由外层任务 `jobId / attempt / fence / seq` 与 `generation` 共同确定；generation 在候选替换时递增。call ID 留在服务端用于绑定实际模型调用。
- `streaming` 为当前候选；`finalizing` 只表示等待正式交付；`interrupted` 只保存按 Spec 可保留的片段；`withdrawn` 必须为空。
- 成功结果持久化后淘汰服务端候选。前端在正式消息尚未刷新到同一轮时保留已有预览，避免终态事件与 GET 之间闪空；403／404 则立即撤下。
- 公开 DTO 通过同一授权和过滤函数构建；不能直接透传原始 JSONB。其他成员消息、报告接口和失效来源不携带候选正文。
- 旧任务没有字段时使用旧交付路径；后端保留现有 `text` 契约兼容，但新前端有 `replyStream` 时不能又画一份旧预览。
- 已完成业务操作、任务卡、临时提问和待确认授权继续以已有结构交付，不放入正文流状态。

## 关键实现约束

### 增量解码

按 JSON 词法状态处理工具参数增量，不能靠正则截取 `"answer"` 后的字符或不断补括号猜 JSON。记住字符串／转义／Unicode 代理对状态；有界缓冲顶层键与 answer，跳过其他字段而不向前端泄漏。

函数名完整匹配后才进入候选。字段顺序不限；重复 answer、多个 finish_task、同批其他工具、超长参数或非法字符撤销候选。末尾仍执行完整 JSON、结束原因和 Delivery 验证；增量解析绝不调用工具。

团队资料标记按当前任务访问范围与继承证据判断，不以用户角色或关键词代替。权限核对和候选筛选在每次发布／读取生效。未验证的内部引用标记需通过专用展示过滤，不得截掉全部 Markdown 链接或代码。

成果目录、显式引用、正文、保存结果和执行记录中的成果引用都继承已授权成果的访问范围；不能依赖上一条消息成功结束才写入的范围。已用成果依赖写入现有 `Job.result.deliverableSources`，记录读取的历史版本与当时的当前版本，随预览保存并在发布／DTO 读取时重新授权和校验；目录来源记录独立于允许修改成果的 `deliverableReads`。

### 状态与竞态

- 普通阶段更新保持正文；仅新候选、自动重试、人工重试、授权失效或最终交付可以显式重置。
- 区分同一任务的不同模型调用，核对模型或工具参数不能覆盖正在展示的正文。
- 自动重试与答复修正复用既有节点执行身份，调用返回缓存时不伪造逐字事件。
- 取消先封存可保留片段并标记中断，再使旧租约失效；迟到回调不得续写。失败与 worker 失联也在服务端统一完成状态转移。
- 终态刷新使用现有单次请求；历史消息未就绪时保留最后前缀，不能循环请求到成功。重新打开页面从受权消息 DTO 恢复未完成展示。
- 只有正式正文进入上下文／压缩；跨会话记忆不得根据未确认输出更新。

### 展示

复用 Markdown 解析、安全链接和最终引用组件。增加 assistant 私有的 `reply/` 组件处理状态和渲染选择；仅在现有 Markdown 无法安全处理未闭合语法时调整公共解析器，并验证其既有用例。新到达的正文以小段文字合并到绘制帧，按积压量调整速度、限制显示滞后；完成、中断和安全撤销立即同步，历史恢复不重播，减少动态效果时跳过动画。

沿用已有聊天滚动观察器；确认代码块、表格逐步展开时不会横向撑破页面、重置任务折叠状态或把向上阅读的用户拉回底部。

## 实施顺序

1. 建立可选契约、增量解码和受控供应商分片测试。
2. 接入模型回调、独立正文快照与节流，处理节点更新、租约、权限和候选撤销。
3. 接入完成、失败、取消、重试、刷新恢复，验证业务执行仍只在完整响应后发生。
4. 接入前端共享订阅、正文组件、Markdown 与最终消息交接；复用错误和任务提示。
5. 执行相关后端、Web 模块检查和浏览器流程，通过代理检查实时传输；实施 Agent 完成后由新的独立 Agent 验收。

## 改造目录

`+` 新增，`~` 原位修改，`·` 复用／验证。只列相关文件，实施中如确需调整同步此树。

```text
apps/server/app/
├── integrations/models/
│   ├── chat.py                              ~ 增量回调、完整响应及明确截断标记
│   ├── transport.py                         ~ 保留供应商输出受限的错误属性
│   └── stream_events.py                     + 通用事件与有界分片装配
├── agent/
│   ├── runtime/
│   │   ├── model.py                         ~ 绑定本次回答输出与既有预算
│   │   └── reply_stream.py                  + 收尾 answer 解码、候选选择
│   ├── completion/
│   │   ├── delivery.py                      ~ 共用收尾字段约束
│   │   └── reply_review.py                  ~ 核对预览边界、截断后有界重试及恢复
│   ├── context/
│   │   ├── deliverable_context.py           ~ 目录／显式引用保留成果来源范围
│   │   └── history.py                       ~ 将成果目录来源绑定当前任务
│   ├── actions/intent.py                   ~ 共享目录入口保留来源约束
│   └── tools/
│       ├── deliverables.py                 ~ 目录／正文读取登记来源
│       └── completion.py                   · 保持终结工具行为
├── tasks/
│   ├── feedback/
│   │   ├── reply_stream.py                  + 正文发布、读取和状态转移
│   │   ├── feedback.py                      ~ SSE 快照与权限
│   │   └── feedback_state.py                ~ 阶段更新保留正文字段
│   ├── context.py                          · 复用已有调用范围与来源版本
│   ├── nodes/node_execution.py             ~ 自动重试的候选生命周期
│   ├── processing/handlers.py              ~ 正式结果与预览交接
│   ├── runtime/
│   │   ├── waiting.py                      · 既有人工决策终态
│   │   ├── queue.py                        ~ 失联 worker 封存与 fence 隔离
│   │   └── cancellation.py                 ~ 中断封存与旧租约失效
│   └── router.py                           ~ 人工重试与已有接口兼容
└── modules/
    ├── messages/serializers.py              ~ 本人刷新读取安全预览
    ├── deliverables/
    │   ├── queries.py                      ~ 来源登记与成果版本／权限复核
    │   └── service.py                      ~ 保存／重放结果保留来源
    └── executions/
        ├── files.py                        ~ 成果文件输入登记依赖
        └── queries.py                      ~ 历史执行成果引用登记依赖
apps/web/src/
├── api/job-feedback.ts                      ~ 顺序、去重、终态衔接
├── hooks/useJobFeedback.ts                  ~ 预览在终态交接期间的可见性
└── features/assistant/components/
    ├── conversation/ConversationChat.tsx    · 复用结果同步与 ResizeObserver
    └── messages/
        ├── MessageCard.tsx                 ~ 交给正文组件展示
        └── reply/
            ├── AssistantReply.tsx          + 预览、未完成和正式正文
            ├── useStreamingText.ts         + 真实新增前缀的有界平滑显示
            └── AssistantReply.module.css   + 局部状态与流式布局
packages/api-contracts/src/index.ts          ~ 可选正文快照契约
tests/
├── server/
│   ├── test_assistant_reply_stream.py       + 增量解码与完整生命周期
│   ├── test_deliverable_reply_stream.py     + 未完成团队成果继承与预览失效回归
│   ├── test_reply_review_limits.py          + 截断重试、恢复和严格核对边界
│   ├── test_deliverables.py                 · 成果读取／修改／历史版本兼容
│   ├── test_execution_history.py            · 执行成果引用兼容
│   ├── test_sandbox_execution.py            · 成果文件输入与保存幂等兼容
│   ├── test_model_stream_errors.py          ~ 完整参数重复键与非流式兼容
│   ├── test_feedback_connections.py         · SSE 权限和连接边界
│   ├── test_message_interrupt.py            · 中断与迟到分片
│   ├── test_operation_recovery.py           · 回执幂等与重试
│   ├── test_response_delivery.py            · 收尾与答复修正
│   └── test_task_retry.py                   · 节点重试与缓存恢复
└── web/
    ├── dom/assistant-streaming.test.tsx     + 渲染、竞态、正式消息交接
    ├── dom/assistant-task.test.tsx          · 既有会话任务与取消
    └── list-feedback.test.ts                ~ 快照去重和连接数量
deploy/company/Caddyfile.app                 · 代理刷新与实际流式到达
```

## 验证计划

实施为 S3：涉及共享模型传输、任务持久化、公开反馈契约和权限边界。验证集中在这些子系统，不默认跑桌面、ASR、真实模型下载或整库测试。

| 层次 | 必测场景 |
| --- | --- |
| 协议／解码 | 单字符和随机切块、乱序字段、转义、emoji、代码／链接、空回答、重复键、多工具、超长参数、缺失结束标记、内容拦截、非流式回退 |
| 后端链路 | token 在结束前到达 SSE；阶段更新不清空；3 次重试机会沿用；取消／旧 fence／节点缓存／worker 恢复；最终保存先于完成事件；工具和业务操作只执行一次 |
| 权限与资料 | 公司与账号隔离、本人材料与团队资料、删除会话、资料失效、角色变更、失效登录；不能读到内部参数、推理或无权正文 |
| Web | snapshot 去重／乱序、前缀替换、不同任务隔离、部分 Markdown、终态 GET 延迟／失败、重试清空、断线提示、向上阅读、任务折叠保持、按钮稳定 |
| 业务流程 | 普通问答→追问；联网搜索→总结；材料→分析；引用工作→更新→回执；工具失败→重试；临时提问→补充→继续；团队查询完整核对后交付 |
| 代理与成本 | 真实 worker/API/SSE 和 Caddy 链路下多个前缀在结束前可见；请求数不随 token 增长，无逐 token 模型调用、写库或附加 GET |

后端先准备已迁移的专用 `paa_company_test` 数据库，并设置 `DATABASE_TEST_URL`；不得指向日常开发或生产库。命令在实施时按实际涉及的测试文件执行：

```sh
.venv-server/bin/python -m pytest tests/server/test_assistant_reply_stream.py tests/server/test_model_stream_errors.py tests/server/test_feedback_connections.py tests/server/test_message_interrupt.py tests/server/test_operation_recovery.py
npm run test:web -- tests/web/dom/assistant-streaming.test.tsx tests/web/list-feedback.test.ts
npm run typecheck:web
```

测试使用隔离数据和可控制分片时间的供应商替身，断言首个前缀早于上游结束，不能仅检查最终文本。已配置真实流式模型时，用隔离会话补普通长回答、公开搜索和工作更新三条真实流程；未具备环境时如实记录，不把替身测试称为真实模型通过。不使用员工真实工作记录做破坏性测试。

源码按项目格式化范围整理；仅检查涉及文件的 Lint／格式。浏览器查看桌面和手机长回答、代码块及中断状态。定向验证通过后停止，独立验收复核证据，不机械重复全部命令。

## 风险与回退

- JSON 参数顺序、切块和无效尾部：有界增量解码只产生候选，完整校验失败必须撤下；不是用解析出的字符串执行工具。
- 已展示的普通候选可能被最终核对改写：界面标注生成中，最终原位替换；团队资料保留完整核对边界。
- 快照与正式消息竞态：以任务版本绑定，禁止空白过渡、旧轮正文复活或重复业务操作。
- 频繁写 JSONB：限制正文长度、合并频率，只存最新前缀；在受控并发场景核对写入和连接数量。
- 无表结构迁移；旧数据／缓存降级为整段回复。可停止绑定增量发布回调恢复原交付流程，不回滚已经执行的业务操作。
