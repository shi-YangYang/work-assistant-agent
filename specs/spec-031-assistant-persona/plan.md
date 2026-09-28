# 实施计划

两种人设共用业务规则，按钮选择决定组合哪份表达提示。按会话保存选择，新会话默认大包，已有会话和历史消息默认专业。

## 改造目录

```text
apps/server/app/
├── core/personas.py                       # 新增：跨模块使用的固定标识和默认值
├── agent/
│   ├── persona.py                         # 新增：两种聊天人设提示
│   ├── policies.py                        # 修改：自然交流与公共业务规则边界
│   ├── harness.py                         # 修改：按消息快照组合 prompt、区分 checkpoint
│   ├── history.py                         # 修改：区分历史对话意图与附件参考，保留操作授权边界
│   └── reply_review.py                    # 修改：范围与事实分别核对、段落依赖筛选、缓存版本
├── modules/conversations/
│   ├── models.py                         # 修改：会话人设
│   ├── schemas.py                        # 修改：创建、部分更新与白名单校验
│   ├── serializers.py                    # 修改：返回当前人设
│   ├── service.py                        # 修改：旧客户端默认会话入口的人设初始化
│   └── router.py                         # 修改：保存选择，保留归属与版本校验
├── modules/messages/
│   ├── models.py                         # 修改：消息人设快照
│   ├── schemas.py                        # 修改：可选 personaId，兼容旧请求
│   └── commands.py                       # 修改：幂等发送、原子新建会话与快照
├── tasks/
│   ├── context.py                        # 修改：本轮人设上下文
│   └── handlers.py                       # 修改：从消息恢复人设，重试保持一致
└── migrations/versions/
    └── 0015_assistant_persona.py          # 新增：会话／消息字段和历史兼容默认值
apps/web/src/features/assistant/
├── api/requests.ts                       # 修改：会话选择与消息契约
├── components/
│   ├── PersonaPicker.tsx                 # 新增：人设选择按钮／菜单
│   ├── PersonaPicker.module.css          # 新增：局部样式与手机布局
│   ├── Conversations.tsx                 # 修改：入口、当前会话与新会话选择
│   ├── Conversations.module.css          # 修改：顶部布局
│   ├── ConversationChat.tsx              # 修改：将人设传给发送流程
│   └── MessageComposer.tsx               # 修改：保存／上传期间禁止冲突发送
├── hooks/
│   ├── useConversationPersona.ts         # 新增：保存、版本冲突、身份／会话隔离
│   └── useMessageSubmission.ts           # 修改：上传／发送期间固定人设
├── lib/audio-capture.ts                  # 修改：草稿／待发送结构的类型（不改录音逻辑）
└── utils/files.ts                        # 修改：冻结消息请求与幂等键
packages/api-contracts/src/index.ts       # 修改：PersonaId 与 Conversation 类型
scripts/benchmarks/agent-evaluation.py     # 修改：双人设用例入口、快照及重试证据
tests/
├── server/
│   ├── test_assistant_persona.py          # 新增：迁移、权限、快照、核对与回执兼容
│   ├── fakes.py                          # 修改：固定模型输出遵循核对契约
│   ├── test_business_actions.py          # 修改：核对、回执、Markdown 与事实边界
│   ├── test_freeform_actions.py          # 修改：自由任务的核对模拟
│   ├── test_agent_audit_regressions.py    # 修改：回归模型的核对模拟
│   ├── test_agent_capabilities.py        # 修改：能力测试的核对契约
│   ├── test_agent_task_integrity.py      # 修改：遗漏操作测试的核对契约
│   ├── test_model_services.py            # 修改：真实请求路径的核对模拟
│   ├── test_search_metrics_feedback.py   # 修改：消息反馈的核对模拟
│   ├── test_task_retry.py                # 修改：核对重试模拟
│   ├── agent_eval_cases.py                # 修改：双人设真实对话用例
│   └── agent_eval_grading.py              # 修改：评分包含实际可见回执，保持证据校验
└── web/
    ├── dom/assistant-persona.test.tsx     # 新增：菜单、切换、失败、异步与发送测试
    ├── audio-capture.test.ts              # 修改：新增录音使新请求重新采用当前人设
    └── message-submission.test.ts         # 修改：发送请求增加人设快照
specs/
├── README.md                             # 修改：登记规格
└── spec-031-assistant-persona/
    ├── spec.md                           # 修改：两种人设、选择与持久化
    ├── plan.md                           # 修改：前后端目录和验证范围
    └── acceptance.md                     # 新增：验收结果与验证限制
```

保留现有真实评测脚本及 `--ids` 选例入口；结果放本地 `artifacts/spec031/`。无文件移动，不引入新组件库，Web 与 Electron 样式仍独立。

## 实施顺序

1. 补齐共享类型、服务端固定标识校验与迁移。`core/personas.py` 提供固定标识和默认值，不让任务上下文反向依赖 Agent；`agent/persona.py` 只维护表达提示。
2. 会话 PATCH 支持部分更新，修改人设不能清空标题；沿用 `expectedRevision`，不存在字段不替换为默认值。旧的仅重命名请求仍有效。
3. 消息发送时冻结 `personaId`，同请求保存消息快照；新会话以该选择初始化。省略字段时读取会话值，旧消息使用专业人设。兼容默认会话入口及已保存幂等摘要。
4. worker 将消息人设放入上下文，主图组合公共业务规则和选中人设；报告、摘要、授权、核对模型不加聊天人设。复用回执快捷路径和节点重试。
5. Web 添加按钮和独立 hook，服务端值为已有会话的依据；空会话选择绑定当前身份和草稿生命周期。保存失败、切换会话及过期响应不清空草稿、不串人设。
6. 完成相称回归与双人设真实对照，再由新的独立 Agent 验收。

数据流：选择按钮 → 会话保存 → 发送时冻结人设 → 消息落库 → worker 恢复快照 → 公共规则＋人设 → 原有工具／核对／回执 → 展示。选择不调用模型；用户明确的内容和语气要求仍优先于默认人设。

## 验证

实施为 S3：跨前后端契约和持久化迁移，覆盖相关接口、状态与任务链路；本轮文档仍按 S0，仅检查 diff 和一致性。

- 服务端：两种角色与两种人设组合、迁移旧会话／消息、只改人设不改标题、未知值拒绝、跨用户修改拒绝、版本冲突、重复发送、旧客户端重放、快照及自动／手动重试。验证报告／授权／核对模型不带人设，回执快捷路径无新增调用。
- 前端：真实 DOM 验证菜单焦点、空会话选择不创建记录、保存失败恢复、刷新值恢复、身份和会话切换、发送前选择冻结、上传时防止冲突操作、失败重发复用请求。检查电脑／手机黑白灰布局。
- 运行 Web 类型检查、相关 DOM 测试与服务端助手／会话相关测试；迁移和公共契约的影响范围内补充已有回归，不叠加桌面模型推理或打包。
- 真实评测选 12 组输入，在同一模型、相同参数和相同初始业务数据上分别运行两种人设：问候、吐槽、接梗、多轮转严肃、随机新建、编辑并查询、正式报告、幽默示例、歧义澄清、删除确认、权限拒绝、失败重试。外部失败与风格失败分开，失败只定向复测，不默认重跑全部历史评测。
- 使用已授权的真实模型配置，密钥不进日志；业务写入采用评测样例，不修改用户真实工作和报告。选人设不会发送任何测试消息。
- 任务成功看数据库、回执和最终显示正文；独立阅读自然度、风格差异及情境适配，不以固定口头禅判分。记录耗时与各节点调用次数，不新增风格专属调用，不以小样本保证延迟或跨模型效果。
- 表达修复按 S2 验证核对格式、缓存、事实与段落依赖，并复测真实失败及保护场景；保留详解、明确索取来源、具体风险和正常业务操作，不重复无关前端或桌面检查。

## 风险与迁移

- 大包提示不应干扰正式业务，专业提示不能导致任务信息被过度压缩；用相同任务对照结果。
- 核对器保留自然比喻但仍剔除虚构事实，规则变化更新缓存版本，不跳过证据核对。
- 发布先迁移再启用新代码；历史选择／消息默认专业，仅新增字段，不改历史正文、不重新执行任务。新会话的应用默认值与旧数据回填值分开。专业任务沿用旧输入摘要和 checkpoint 地址，大包单独区分。
- 运行中任务和重试从消息快照恢复，不能读取后来切换的人设；发布不主动重做操作。
- 回滚应用时可保留新增字段；降级迁移会丢失人设选择及快照，须备份且停用新代码后再执行。
