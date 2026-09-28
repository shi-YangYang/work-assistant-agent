# 实施计划

对应[三级执行权限与临时回答框](spec.md)。方案已确定，可进入实施。文档按 S0 检查；实现涉及授权、迁移和公共 API，按 S3 验证相关后端与 Web。

## 改造目录

`+` 新增，`~` 原位修改；组合名称指同目录文件。不迁移现有目录，最终文件按职责拆分，不能把全部逻辑堆进 harness 或 ConversationChat。

```text
apps/server/app/
├── modules/conversations/
│   ├── models.py、schemas.py、router.py、serializers.py ~ 会话模式及版本
│   └── task_state.py                                  ~ 问答与原任务续接
├── modules/interactions/                              + 用户问题生命周期
│   ├── models.py、schemas.py                          + 问题、答案、来源、版本
│   ├── service.py                                    + 创建、回答、取消、幂等
│   ├── queries.py、serializers.py                     + 授权读取及安全投影
│   └── router.py                                     + 当前问题与回答接口
├── modules/operations/
│   ├── execution_policy.py                           + 统一执行确认策略
│   ├── models.py                                     ~ 批准模式与续接记录
│   ├── service.py、commands.py                        ~ 通用批准及续接
│   ├── targets.py、receipts.py                        ~ 变更预览和动作按钮
│   ├── writes.py、deletion.py                         ~ 写入与关联等待项失效
│   └── report_completion.py                          + 报告完成后按授权交接
├── modules/reports/results.py                        ~ 在完成事务中交接报告操作
├── modules/work/progress.py                           ~ 建议应用与批准一致性
├── modules/messages/
│   ├── schemas.py、commands.py                        ~ 模式冻结、自然语言回答
│   └── serializers.py                                ~ 问答摘要
├── modules/members/commands.py                        ~ 删除账号清理等待项
├── agent/
│   ├── execution_mode.py                             + 模式的模型提示
│   ├── interactions.py                               + 提问与批准等待的运行接入
│   ├── tools/questions.py                            + 结构化提问工具
│   ├── tools/registry.py、tools/actions.py、policies.py ~ 工具注册及行为边界
│   ├── intent.py、operations.py、reports.py            ~ 意图与批准分离
│   ├── task_context.py                               ~ 问题与批准证据
│   └── harness.py、middleware.py、tool_nodes.py        ~ 等待时结束本轮执行
├── tasks/
│   ├── interactions.py                               + 关联续接的排队与去重
│   ├── waiting.py                                    + 回答、批准和失效后的等待状态收敛
│   ├── context.py、handlers.py、feedback.py            ~ 模式快照、等待及交互投影
│   └── cancellation.py                               ~ 取消关联问题
├── security/versions.py                              ~ 仅接受同任务成功回执的版本推进
├── http/routers.py、db/registry.py                    ~ 注册问题接口及模型
└── migrations/versions/0019_assistant_interactions.py + 增量迁移
packages/api-contracts/src/index.ts                    ~ 模式、问题、答案和批准 DTO
apps/web/src/
├── api/job-feedback.ts                               ~ 交互状态 SSE 契约
└── features/assistant/
    ├── api/interactions.ts                           + 回答请求与续接契约
    ├── api/requests.ts                               ~ 消息模式快照
    ├── hooks/useExecutionMode.ts                     + 会话模式、空会话选择
    ├── hooks/useAssistantInteraction.ts               + 回答草稿、提交与恢复
    ├── hooks/useConversationPersona.ts               ~ 模式与发送并发互斥
    ├── utils/interactions.ts                         + HTTP／SSE 交互合并
    ├── utils/files.ts、lib/audio-capture.ts           ~ 模式快照与录音时长
    └── components/
        ├── ExecutionModePicker.tsx、.module.css       + 执行模式菜单
        ├── QuestionPanel.tsx、.module.css             + 临时回答面板及问答记录
        ├── ConversationChat.tsx、Conversations.tsx    ~ 装配模式与面板
        ├── ChatHistory.tsx、MessageCard.tsx           ~ 问答历史
        ├── MessageComposer.tsx、.module.css           ~ 工具栏左右分组、录音状态
        └── BusinessActionCard.tsx、.module.css        ~ 通用批准与自动续接
tests/
├── server/test_execution_permissions.py              + 模式策略、批准与角色
├── server/test_assistant_interactions.py              + 问答、恢复与并发
├── web/dom/assistant-interactions.test.tsx            + 模式与回答交互
├── web/dom/assistant-task.test.tsx                    ~ 工具栏与录音状态
└── web/dom/business-action-card.test.tsx              + 通用批准按钮与恢复
scripts/benchmarks/
├── agent-permission-cases.json                        + 冻结的三级模式场景
└── agent-permissions-evaluation.py                    + 真实模型及隔离业务 fixture
constitution/mission.md、docs/architecture.md          ~ 模式、真实权限与问答边界
```

## 实现边界

- `modules/operations/execution_policy.py` 以服务端确认的模式、动作类别和意图核对结果为输入，返回 `allow/ask/deny`。规则可单独测试，不依赖 React、HTTP 或模型实例；HTTP 与 Agent 共用。
- `intent.py` 保留用户来源、任务范围和追加增量语义的核对，移除散落的“某模式必须重复批准”判断。不得用简单关键词识别授权，也不得因自主执行关闭真实访问控制。
- 批准沿用 `BusinessAction`，新增模式／批准原因及版本快照等最小元数据。`modules/interactions` 只持久化问题与答案；不复制业务回执或完整聊天，批准面板仍读取原操作记录。
- `tasks/interactions.py` 管理续接排队、幂等键与逻辑任务关联；不能让底层 ORM／配置／租约反向依赖 harness。HTTP 与工具共用业务用例。
- 新工具用明确结构提出问题，不从助手自然语言中的问号推断弹框。服务端只投影经过验证的对象候选，普通偏好选项作为文本保存。
- 新交互入口复用唯一 API／身份处理；CSS 只在 Web 功能目录维护。

## 数据与接口

1. `Conversation` 增加执行模式，沿用会话 revision；创建／修改 DTO 接受枚举，首次发送的新会话同时携带模式。Job 冻结模式版本，重试提升权限不得静默继承。
2. 新问题记录含公司／所有者／会话／逻辑任务、来源消息版本、缺失项标识、问题及选项、答案、状态、revision 和已创建的续接标识。去重键由服务端确定，不接受模型伪造的可信状态。
3. 拟定 `GET /api/v1/conversations/{id}/interactions` 读取当前等待项；`POST /api/v1/interactions/{id}/answer` 提交结构化答案；`POST /api/v1/interactions/{id}/cancel` 取消相应等待任务。回答携带 `expectedRevision` 与幂等键，返回已保存答案、交互状态及可选续接 Job。
4. 现有操作 `confirm/cancel` 接口保持入口，扩展动作支持与可选续接信息；所有确认仍校验操作预览摘要和当前来源。旧卡片不因默认模式改变而自动执行。
5. 只读当前等待投影加入消息／Job 查询与 SSE；没有交互时为空。不要向前端返回完整授权原文、隐藏资料或模型内部推理。
6. 按照既有公司→用户→会话／任务锁顺序，在同一事务中消费回答或批准并登记后续运行；数据库唯一约束兜底重复点击及多标签页。报告生成子任务继续复用现有队列。

## 执行流程

```text
收到任务 → 冻结会话模式与有效任务上下文
  → 信息足够：意图／范围核对 → 真实权限与版本检查
      → allow：执行并保存回执
      → ask：保存预览 → 等待批准
      → deny：解释具体限制
  → 信息不足：结构化问题落库 → 等待回答

用户回答／批准 → 校验来源、权限、版本及幂等
  → 保存用户输入／执行被批准的精确操作
  → 创建同一逻辑任务的续接运行
  → 只处理剩余事项 → 展示实际结果
```

- 等待时不挂起活跃 worker。问题工具使本轮有明确的等待结果；等待不经过普通“失败→自动重试”路径，不消耗节点失败重试次数。
- 提问与写入同批调用、多个问题并发、批准后尚有依赖步骤都要明确协调；不得先执行依赖未知答案的写入。
- 明确拒绝保存为原事项的终止结果；普通问答、其他批准和更高模式不能复活它。需用户新的明确要求才建立新操作。
- 取消、来源变化与任务替换统一失效等待项。原消息自然语言答复与结构化答复走同一消费逻辑；不同请求不能各创建一次续接。
- 模型只写出必要问题而未调用提问工具时，正文依旧可读并可自然语言承接；不能伪造一个成功的结构化问题。定向真实评测检查工具使用与实际续接。

## 修改顺序

1. 按确定的三级矩阵、默认范围、提交／删除行为及面板形式，固定验收案例。
2. 实现纯策略、模式存储、问题模型及增量迁移，先验证旧会话／旧卡片兼容。
3. 泛化业务批准，接入写入入口、报告生成、建议应用及续接排队；保持原回执幂等。
4. 接入结构化提问、普通答复关联、等待退出和任务恢复，同步所有权限、来源及取消路径。
5. 在输入框下方添加模式菜单：左侧按添加文件、执行权限排列；将现有左侧录音控件移至右侧，按上下文、麦克风、发送／中断排列。人设保留在会话顶部。接入临时回答面板，统一 HTTP/SSE/刷新及账号切换恢复。
6. 完成相称验证后由新的独立验收 Agent 审查；相关机制缺陷未解决不能宣布完成。

## 验证与停止条件

规格阶段仅检查 diff、引用和需求一致性，不运行测试。实施阶段：

- 确定性后端覆盖三级×动作类别矩阵、不可越权、旧卡片兼容、模式升降与旧重试、预览变化、来源失效、同批问答／写入、刷新恢复、重复答案、多标签页、取消、批准后继续及报告交接。
- 相关 Web 测试覆盖模式保存、自然语言／结构化回答、自由输入、提交失败保留、收起／恢复、切换账号、通用批准按钮、发送／中断及节点展开稳定性。
- 迁移在隔离数据库验证升级、旧数据读取及回滚；不对生产或用户日常数据做故障注入。
- 使用现有真实评测脚本，冻结 9 个场景：三种模式各 3 个，覆盖常规写入、提交／删除与缺信息续接。每模式保留 1 个变体，不用于调整提示。人工交互由测试客户端提交，模型、核对和业务持久化均真实执行。
- 场景同时断言业务数据、未变字段、回执、等待／完成状态及可见问题，避免只凭模型评分。保留首次失败；仅在相关修改后重跑受影响场景。保留样本被用于修复时补等价未见样本。
- 桌面和手机宽度各检查浅／深色的模式菜单、问题面板、批准及长内容；核对工具栏左右分组、按钮顺序及录音／发送切换时的稳定性。不扩展到全站截图、Electron 或完整发布流程。
- 实施命令沿用 `npm run test:server -- <定向文件>`、`npm run test:web -- <定向文件>`、`npm run typecheck:web`；变更的 TS/CSS 执行项目格式化与定向 ESLint。测试隔离配置及真实评测入口复用现有脚本。
- 矩阵、恢复与 UI 的必要检查通过，真实场景达到约定结果、无已知相关阻塞后立即停止；不重复已通过且未受新修改影响的检查，不修改默认 CI。

## 迁移与风险

- 模式默认 `auto`，新增问题表与批准元数据；不从历史正文补建问题。已有操作继续按原预览确认。
- 回滚旧程序前停止接收新交互并处理或取消待办，保留增量表。旧程序不理解新模式及普通操作确认，不能声称可无损热回滚。
- 主要风险是模式被当成角色权限、参数变更复用旧批准、等待占用 worker、回答串到旧任务、前后端重复提交。分别通过服务端权限、预览版本、持久等待、来源绑定和事务幂等处理。
- 自动审核的“审核”必须沿用既有意图核对及确定性规则，不新增冗余的第二个审批模型。自主执行的范围说明必须与最终矩阵一致。
