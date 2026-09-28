# 实施计划

已完成会话级 JSONB 上下文、增量读取、模型容量、压缩和输入区图标；验证结果见 [验收记录](acceptance.md)。

## 改造目录

```text
apps/server/app/
├── agent/
│   ├── context_usage.py                # 新增：模型窗口、输入预留、估算与阈值判断
│   ├── compaction.py                   # 新增：摘要中间件、保留策略与恢复
│   ├── harness.py                      # 修改：替换固定阈值摘要，装配新中间件
│   ├── model.py                        # 修改：模型窗口检查及动态累计输入预算
│   ├── history.py、conversation_context.py # 修改：读取快照、增量补齐与冷启动重建
│   ├── intent.py、reply_review.py       # 修改：核对链的上下文一致性与输入边界
│   └── report_context.py               # 修改：报告引用摘要时复核来源与权限
├── integrations/models/
│   ├── capabilities.py                 # 新增：有来源的模型容量与元数据归一化
│   └── catalog.py                      # 修改：保留可验证的模型能力元数据
├── tasks/
│   ├── context.py                      # 修改：传递本次主助手上下文计量信息
│   ├── context_feedback.py             # 新增：任务用量快照、压缩状态与安全 DTO
│   ├── handlers.py                     # 修改：完成任务时幂等发布会话上下文
│   ├── lease.py                        # 修改：仅查询来源失效版本，避免反复加载 JSONB
│   ├── node_execution.py               # 修改：接入压缩节点及统一重试
│   ├── feedback.py                     # 修改：复用 SSE 推送快照
│   └── serializers.py                  # 修改：普通查询返回同一快照
├── modules/
│   ├── conversations/
│   │   ├── models.py                   # 修改：会话上下文表、JSONB 与独立版本
│   │   ├── context_store.py            # 新增：读取、增量合并、版本保护与失效
│   │   ├── context_invalidation.py     # 新增：无反向依赖的快照失效处理
│   │   ├── references.py               # 新增：消息／回执投影，供快照与 Agent 复用
│   │   ├── context_usage.py            # 新增：查询本会话最新有效任务用量
│   │   └── router.py                   # 修改：受权的只读用量接口
│   ├── messages/commands.py            # 修改：消息修订使相关上下文失效
│   ├── members/commands.py             # 修改：账号删除清理上下文快照
│   ├── operations/deletion.py          # 修改：接入已有删除／失效链，清理快照
│   └── model_services/
│       ├── schemas.py                  # 修改：可选模型容量及字段校验
│       ├── bindings.py                 # 修改：容量来源随任务配置冻结
│       └── service.py                  # 修改：模型配置读写与只读能力元数据
├── security/
│   ├── invalidation.py                 # 修改：权限变化使受影响的上下文失效
│   └── versions.py                     # 新增：公共版本校验与同任务操作推进识别
└── migrations/versions/
    └── 0017_conversation_context.py    # 新增：上下文表及唯一约束，不回填大段历史
apps/web/src/
├── features/assistant/
│   ├── api/requests.ts                 # 修改：用量查询入口
│   ├── hooks/useContextUsage.ts        # 新增：会话快照与任务更新订阅
│   └── components/
│       ├── ContextUsage.tsx            # 新增：图标、详情与压缩提示
│       ├── ContextUsage.module.css     # 新增：局部样式与手机适配
│       ├── MessageComposer.tsx         # 修改：发送按钮左侧挂载组件
│       ├── MessageComposer.module.css  # 修改：工具栏间距和触摸区域
│       ├── ConversationChat.tsx        # 修改：连接当前会话与用量状态
│       └── ChatHistory.tsx、MessageCard.tsx # 修改：复用既有任务反馈传递用量
├── features/model-services/
│   ├── components/ModelOptions.tsx     # 修改：现有高级设置中展示／覆盖容量
│   ├── api/requests.ts                 # 修改：保留模型目录能力信息
│   ├── hooks/useModelServiceController.ts # 修改：保存可写模型配置
│   ├── hooks/useServiceCheck.ts        # 修改：测试配置时剔除只读元数据
│   ├── hooks/useServiceDraftSession.ts # 修改：恢复容量草稿
│   └── utils/service-drafts.ts         # 修改：容量字段默认值、校验与保存
├── features/jobs/components/TaskNode.tsx # 修改：压缩及重试文案
├── utils/model-capacity.ts             # 新增：统一容量输入校验及配置清理
└── api/job-feedback.ts                 # 修改：解析可选快照，复用版本校验
packages/api-contracts/src/index.ts     # 修改：模型容量、ContextUsage 与任务可选字段
docs/architecture.md                   # 修改：会话上下文、checkpoint 与业务数据职责
tests/
├── server/
│   ├── test_context_usage.py           # 新增：估算、状态、会话隔离和只读接口
│   ├── test_context_compaction.py      # 新增：阈值、压缩、恢复和业务连续性
│   ├── test_context_store.py           # 新增：增量、失效、并发、迁移和查询路径
│   ├── test_boundaries.py              # 修改：原固定阈值用例适配
│   └── test_model_services.py          # 修改：模型容量配置及修订兼容
└── web/
    ├── dom/assistant-context.test.tsx  # 新增：图标、详情、通知和切换隔离
    ├── task-progress.test.ts           # 修改：压缩节点及重试展示
    └── model-service-drafts.test.ts    # 修改：容量覆盖与只读字段清理
specs/
├── README.md                           # 修改：登记规格
└── spec-033-assistant-context-usage/
    ├── spec.md                         # 新增：行为与验收要求
    ├── plan.md                         # 新增：目录与实施方案
    └── acceptance.md                   # 新增：实际验证与限制
```

保持现有目录。扩大可用历史长度，但不扩大公司、账号或会话访问范围；历史、摘要与核对链共用来源授权。

## 数据与接口

### 上下文存储与执行

- 新增 `company_conversation_context`，与会话一对一，带公司／所有者范围、独立 `revision`、来源失效版本及更新时间；与会话标题修订分开。JSONB 不随会话列表默认加载，不新建文件存储或缓存服务。
- JSONB 内容为 `schemaVersion`、`summary`、`recentMessages`、必要回执／引用、来源版本清单、增量游标及已发布任务／压缩标识。消息保留角色和稳定 ID；工具调用／结果保持配对。不存原始附件、密钥、固定系统提示或旧任务的待执行节点。
- 业务表提供原始事实；JSONB 是可重建的模型上下文；`Job.result.contextUsage` 只存展示统计；checkpoint 负责任务恢复。读取快照后动态加入当前提示、人设、工具定义和本次输入，执行时用内存上下文。
- 正常路径只读取快照、增量及必要的批量来源／权限校验；首次或失效时分页重建。游标结合消息修订与任务完成状态，不能只按创建时间忽略旧消息重试或迟到结果；按消息 ID、来源修订、操作回执去重。
- 发布采用短事务和版本比较，核对会话状态、来源版本与任务租约；冲突后重新读取并合并，不以旧完整 JSON 覆盖新快照。模型调用不占用数据库事务锁。业务记录或权限必须查询最新值时，继续走现有工具与校验。
- 压缩先提交任务 checkpoint，再幂等发布会话快照及成功反馈；不假设两个连接天然原子提交。中间崩溃时从有效 checkpoint 补完发布；来源失效则丢弃旧摘要并重建，不能重复执行业务操作或提前提示压缩成功。
- 消息纠正与删除沿现有失效链清理受影响内容，无法精确判定影响时丢弃该快照重建；读取、发布时再检查权限与来源版本。模型或人设改变只重建请求和计量，合法事实无需一律重新摘要。

### 模型容量与前端反馈

- 模型配置增加可选 `contextWindow`，服务端能力解析区分总窗口、最大输入与最大输出。目录响应保留原模型 ID 列表，能力元数据以可选映射附加；自动值带来源，管理员覆盖保存在现有服务修订 JSON 中。
- 能力匹配以服务入口、精确模型 ID／版本及可验证别名为依据。已知官方 1M 模型正确解析；未知代理别名允许手填，不默认猜成 24K 或 1M。旧任务无容量快照时可按其绑定的不可变服务修订解析，不采用后来修改的管理员覆盖值。
- 定义 `ContextUsage`：`jobId`、执行版本、快照序号、主助手模型标识、`usedTokens`、`contextWindow`、`inputLimit`、`outputReserve`、容量来源、`thresholdRatio`、`estimated`、`state`、`compactionId`、压缩前后用量与 `updatedAt`。未知容量允许为空，百分比也为空。
- `state` 区分 `ready / compacting / retry_wait / failed`；节点重试次数从现有节点状态获取，不另造重试状态机。百分比由服务端计量值计算，前端不维护第二套 token 估算。
- 用量快照保存到 `Job.result.contextUsage`，`job_dto` 与反馈 SSE 复用同一序列化器；写入必须经过租约／输入版本校验并递增反馈版本。该字段不复制会话上下文正文。
- 新增 `GET /api/v1/conversations/{id}/context-usage`：校验公司、本人会话及任务来源权限，返回最近有效任务的快照与关联任务标识。只读，不触发摘要、不读取私有摘要原文。
- 前端用该接口恢复当前会话，运行中沿用任务反馈机制；避免图标和消息卡分别创建一套相同订阅或高频轮询。利用 `jobId + attempt + fence + seq` 拒绝旧事件，额外以会话和登录身份约束缓存。
- 压缩成功反馈与已持久化的 checkpoint、会话快照对应；中断恢复不能仅凭进度状态认定完成。当前授权仍来自当前消息，事实核对仍使用有效原文与回执。

## 修改顺序

1. 核对已安装 LangChain 中间件的异步摘要、工具配对、checkpoint 更新和内置重试行为。固定一种摘要入口，避免框架重试与项目节点重试叠加。
2. 新增上下文表与 `context_store`，实现冷启动重建、增量、幂等发布和失效；接入历史组装及任务完成路径，保持 checkpoint 按任务隔离。
3. 接入模型容量解析与高级设置，冻结到任务配置；统一请求估算，取消主助手固定 24K 输入和 256K 累计预算，按模型输入容量及既有调用次数推导累计保护。图片、system／tools 等均计入，辅助请求不覆盖主助手指标。
4. 按容量组装快照及增量，解除固定 12 条／12K 截断；主助手、授权及答复核对同步调整。实现 90% 触发和分块摘要，保留当前完整要求、工具配对与独立证据，失败不覆盖有效上下文。
5. 复用 `execute_node`、租约与 checkpoint 保存压缩结果并发布到会话快照。幂等身份包含任务输入／配置范围与被压缩内容版本，覆盖中断恢复与并发冲突。
6. 接入用量快照、受权查询及现有 SSE。下一任务／重试／切换模型重新计算，不直接沿用旧百分比。
7. 添加图标与轻量详情、任务进度文案。保持发送／停止／录音／附件／人设交互，手机避免横向溢出；成功提示按压缩事件去重。
8. 相关验证通过后交独立验收；失败按具体问题定向返工，不默认追加整仓测试。

## 验证

文档阶段为 S0，只检查需求、diff 和引用。实施涉及 Agent 上下文、持久化恢复及 HTTP 契约，按 S3 覆盖受影响子系统。

- 服务端：不同模型容量与 90% 边界，包含官方 1M、超过 24K 输入及 256K 累计输入、历史超过 12 条；元数据缺失、手动覆盖、输出预留、最大输入与模型切换。验证完整计量、图片估算、辅助请求隔离、工具配对、摘要复用与压缩后下降；超限、无可压缩内容、摘要失败、租约丢失和 checkpoint 恢复。
- 会话安全：跨公司／员工拒绝读取；删除、权限变化、旧任务事件、历史无快照正常处理；刷新查询不产生模型调用。
- 存储：旧会话首次构建，压缩后跨任务复用；纠正、删除、迟到结果、重试不遗漏或重复。模拟并发版本冲突、checkpoint 已提交但快照未发布时中断，确认恢复不覆盖新状态。验证迁移、会话／账号删除清理。
- 查询路径：同一固定会话比较首次构建与后续增量读取，记录 SQL 次数和上下文准备耗时；确认正常路径无历史逐条关联查询、同任务多轮无完整重读、列表无 JSONB 正文加载。不把模型网络耗时算成数据库优化收益。
- 连续任务：读取材料 → 制定计划 → 用户纠正 → 创建指定工作 → 多次工具调用触发压缩 → 指代修改第二项 → 查询核实。压缩前后核对对象 ID、版本、事实来源与写入次数，授权／核对链不降级。
- 前端：定向 DOM 与任务进度测试、Web 类型检查。格式化仅修改文件；浏览器检查浅／深色、桌面／手机、空会话、压缩中、完成、失败和刷新恢复。
- 使用现有授权模型做真实长上下文与压缩后的连续任务验证，报告实际模型、输入规模及触发阈值；测试用缩小阈值只能证明压缩链路，不能宣称完成了 1M 满窗口验收。大规模窗口边界先用固定响应验证，不擅自批量发送百万 token 请求；真实验证不加入默认 CI，证据放 `artifacts/spec033/`。

## 风险与迁移

- 估算不是服务商精确分词，展示需标注；优先使用可用的模型分词／用量信息校准。真实容量按供应商和模型版本解析，未知时不能编造百分比或自动压缩保证。
- 摘要可能丢失细节。原始资料可回读，关键指代／修正／授权／回执需回归验证，不声称压缩完全无损。
- 长窗口增加数据库读取、序列化与请求时长。历史分页、复用摘要、取消和有界调用必须保留，避免一次无界加载整个会话；用量反映实际输入而非聊天总长度。
- 增加一张会话上下文表，旧业务表和 checkpoint 保留。旧会话按需构建，迁移不调用模型、不批量回填历史；降级停用新读写路径即可继续从原始记录组装。上下文格式带版本，无法兼容时重建，不把旧格式当有效数据。
- JSONB 写入仍有序列化与整值更新成本；只在任务完成／压缩等检查点发布，不逐 token 写数据库。限制快照内容和分页载入，不复制完整历史；内部资源超限如实处理，不能伪称模型窗口已满。

## 技术依据

[LangChain 摘要中间件](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization) 支持按阈值摘要并保留近期消息；本项目需要补齐完整请求计量、可见进度和现有重试边界，实施以已安装依赖为准。

[百炼原厂模型](https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash)为 1,000,000，[Vanchin 版本](https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash-by-vanchin)为 1,048,576。能力表需注明服务入口和精确模型 ID，不能把官方接口数值无条件套给同名第三方模型。
