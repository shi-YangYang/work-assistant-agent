# 实施计划

## 范围与风险

围绕工作入口、助手引用和 Agent 上下文原位扩展，不重构无关模块。实施涉及消息持久化、公共契约与权限，按 S3 做相关子系统验证；本次规格文档为 S0，仅检查 diff、路径和需求一致性。

## 改造目录

`+` 新增，`~` 修改。没有移动或删除；文件名按实际职责落地，变化时同步此树。

```text
packages/api-contracts/src/index.ts                       ~ 工作引用 DTO
apps/web/src/components/Modal.tsx                        ~ 弹层可访问名称
apps/web/src/features/
├── work/components/WorkDetail.tsx                        ~ 让助手协助入口，仅传工作 ID
└── assistant/
    ├── api/restore-conversation.ts                       ~ 专用最近聊天恢复
    ├── api/requests.ts                                   ~ 工作引用请求与候选查询
    ├── hooks/useWorkReference.ts                         + 一次性入口、草稿引用与选择
    ├── lib/audio-capture.ts                              ~ 既有 Composer 类型加可选引用
    ├── utils/files.ts                                    ~ 请求快照包含引用
    ├── components/Conversations.tsx                      ~ 恢复会话时保留并消费工作入口
    ├── components/ConversationChat.tsx                   ~ 装配引用和草稿
    ├── components/MessageComposer.tsx                    ~ 加号菜单和引用位置
    ├── components/MessageCard.tsx                        ~ 已发送消息引用
    ├── components/WorkReferencePicker.tsx                + 搜索、分页与选择弹层
    ├── components/WorkReferenceChip.tsx                  + 草稿／已发送引用标识
    └── components/WorkReference.module.css               + 就近维护引用样式
apps/server/app/
├── migrations/versions/0021_message_work_reference.py    + 消息引用增量迁移
├── modules/conversations/
│   ├── router.py、queries.py                            ~ 最近用户消息排序选项
│   └── references.py、context_store.py                   ~ 历史引用标识与缓存兼容
├── modules/messages/
│   ├── models.py、schemas.py                             ~ 可选消息引用，不关联默认会话
│   ├── commands.py                                      ~ 发送校验与幂等
│   ├── serializers.py                                   ~ 安全展示引用及不可用状态
│   └── work_references.py                               + 共用引用校验与最小投影
├── tasks/context.py、handlers.py                         ~ 运行引用快照与重试输入版本
└── agent/
    ├── work_context.py                                  + 最新工作上下文读取与版本登记
    ├── task_context.py                                  ~ 向执行与核对提供同一引用
    ├── harness.py、policies.py                          ~ 引用进入实际模型输入、检查点与证据
    ├── reply_review.py                                 ~ 引用事实参与独立答复核对
    └── tools/work.py                                   ~ 工具接受已验证的引用 ID
tests/
├── web/dom/assistant-work-reference.test.tsx             + 两入口、草稿、菜单和账号隔离
└── server/test_work_references.py                        + 最新内容、权限、核对和兼容
specs/
├── README.md                                            ~ 索引
└── spec-037-assistant-work-reference/
    ├── spec.md                                          + 需求和验收
    ├── plan.md                                          + 实施边界和目录
    ├── implementation.md                                + 实施与验证证据
    └── acceptance.md                                    + 独立验收结果
```

## 模块边界与数据流

1. 工作详情导航至 `/assistant?workId=<id>`，URL 只传标识，不传工作正文或任意目标会话。助手入口完成恢复后把引用放入目标草稿，成功后消费该参数；网络错误时保留入口以便重试。已有 `composer:new` 不应抢走这次明确的最近聊天入口，其草稿仍原样保存。
2. 加号菜单选择器复用 `/work-items` 的搜索、分页和本人范围，使用助手 feature API 封装请求。引用状态由小型 hook 管理，不让公共 workspace 层依赖业务组件，也不让 WorkDetail 导入整套助手实现。
3. Composer 增加可选引用，`messageSubmission` 将其冻结进待确认请求。选中引用后即使文本为空也保留草稿，但不改变已有发送条件；请求未确认期间禁止更换引用。
4. 消息事务校验工作引用并保存 ID，和现有消息／任务一起提交；失败不留下空会话。消息展示仅投影可访问的名称，不在消息 API 重复返回完整工作历史。
5. Agent 在任务开始时加载工作当前内容及 revision，通过共用任务投影同时交给规划、执行和独立核对；登记已验证读取，复用现有版本及去重机制。材料不能成为授权原文。
6. 当前引用加入本轮提示与用量估算，不从 JSONB 缓存直接信任旧正文；历史上下文仅保留消息对应的 ID，按需读取当前数据。持久化摘要、检查点和重试不得把旧引用提升为新的持续指令。

## 接口与数据

- `POST /api/v1/messages` 增加可选 `workReference: { workId: string }`；省略时不改变旧幂等摘要。修改引用必须生成新请求快照，不能复用旧幂等键。
- `Message` 增加 `work_reference` JSONB 字段，默认空对象，保存引用 ID。与成果引用分开，不复用权限字段或附件字段，不新增绑定表。
- `WorkMessage` 增加可选只读引用投影，例如 `{ workId, title, unavailable }`；标题由服务端授权读取，不接受客户端提供。工作不可访问时不返回标题和内容。
- 会话列表增加可选 `order=last_message`，按当前用户未删除消息的最近发送时间降序，并以 ID 稳定排序；没有消息的会话排在后面，按原更新时间排序。默认列表排序和分页保持兼容，新排序使用一致的游标语义。工作入口使用此选项，普通助手入口不变。
- 候选工作沿用现有接口，不新增可绕过归属检查的查询；第一版限制本人工作。已存在的真实访问限制继续生效。
- 工作删除不级联删除聊天消息，引用以不可用状态保留；不改动原有工作删除和消息留存策略。

## 实施顺序

1. 先实现消息契约、迁移、最近聊天查询与引用校验，确定单项引用和旧请求兼容。
2. 接入共用 Agent 工作上下文、读取版本及历史引用；先验证同名工作、旧任务干扰和材料不授权。
3. 实现引用选择器和工作入口，接入草稿、发送快照及历史消息展示，保持既有输入区布局。
4. 完成定向验证和截图，由新的独立验收 Agent 审查。边界耦合较强，由一个实施 Agent 串行开发，避免前后端各自定义引用语义。

## 验证计划

- 后端定向覆盖：最近发消息排序与账号隔离；发送前改名／更新、排队期间变更、删除、伪造 ID、同名对象；缺省字段旧幂等、重复提交、新会话事务回滚、重试去重；上下文压缩／恢复后仍按权限读取。
- Agent 场景覆盖：旧会话讨论 A，本轮引用 B 做分析；引用同名 B 修改指定字段；工作描述含操作指令但用户只要分析；旧持续指令不得误作用于新工作；三种模式下引用对象的执行与核对一致。
- Web 定向覆盖两个入口、非第一页搜索、空会话首次发送、选择／替换／移除、发送成功清空、失败保留、冻结请求、已有文字附件保留、快速重复点击、切换账号／会话与慢请求返回。
- 使用相关 `tests/server` 和 `tests/web` 文件及既有发送、执行权限、上下文测试，运行 `npm run typecheck:web` 与改动文件的 ESLint。源码按项目配置格式化；不默认运行整个仓库、Electron 或打包测试。
- 在隔离数据库检查迁移升级、旧消息读取和降级；不改用户日常工作数据，不访问生产环境。
- 桌面／手机宽度各检查浅色和深色：选择弹层、长标题、空结果、失败状态、引用移除、发送／中断和临时回答框并存。截图放 `artifacts/`，不新增全站视觉验收。
- 实施后若有可用的已授权模型配置，使用隔离账号和工作做 3 个真实场景：引用分析、明确局部更新、同名工作定位；核对实际记录和未变字段。无法运行时明确记录未执行，不用模拟结果冒充真实验证。
- 必要检查通过且无相关未解决问题后停止，不为文档运行测试，不重复未受新修改影响的已通过检查。

## 迁移与回滚

- 新增字段默认空对象，不从旧聊天猜测并回填工作引用，不改变工作表或既有会话关系。
- 上线顺序为数据库迁移、后端、前端。旧客户端可继续发送无引用消息，新前端需要支持新字段的后端。
- 回滚应用前先处理带引用的在途任务，避免旧 worker 忽略引用后误选对象；降级迁移会丢弃新增引用元数据，不能宣称无损回滚。业务工作数据不随引用删除。
