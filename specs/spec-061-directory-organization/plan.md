# 目录归类实施计划

## 对应 Spec

[项目目录归类与边界整理](spec.md)。已按本计划完成；结果与限制见[最终验收](acceptance-final.md)。

## 涉及模块

沿用现有应用与分层，只整理已经混合多种职责的子目录。目录树标明目标归属，下表列明当前文件到目标位置的对应关系；未列出的业务模块保留位置，仅在引用受影响时修改导入。

### Web 迁移清单

以下路径以 `apps/web/src/features/assistant/` 为根，表中组件均包含已有同名私有 `*.module.css`，不创建不存在的样式文件。

| 当前位置/文件 | 目标位置 | 职责 |
| --- | --- | --- |
| `components/composer/ComposerAttachments`、`ComposerAudioPreview` | `components/composer/attachments/` | 附件条与语音预览 |
| `components/composer/ContextUsage`、`ExecutionModePicker` | `components/composer/controls/` | 输入框底部控制项 |
| `components/composer/reasoning/ReasoningEffortPicker` | `components/composer/controls/` | 思考强度选择；迁移完成后删除空 reasoning 目录 |
| `components/conversation/ConversationPicker`、`PersonaPicker` | `components/conversation/controls/` | 会话与人设选择 |
| `components/messages/MessageTranscript`、`TranscriptEditor.tsx` | `components/messages/transcript/` | 语音文字展示与更正 |
| `hooks/useAssistantTask.ts`、`useAssistantInteraction.ts`、`useConversationRefresh.ts`、`useConversationSearch.ts` | `hooks/conversation/` | 会话任务、临时问答和恢复 |
| `hooks/useMessageSubmission.ts`、`useRecording.ts`、`useWorkReference.ts`、`useContextUsage.ts` | `hooks/composer/` | 当前输入、录音、工作引用和上下文显示 |
| `hooks/useConversationPersona.ts`、`useExecutionMode.ts`、`useReasoningEffort.ts` | `hooks/preferences/` | 人设、执行权限和思考强度偏好 |
| `hooks/useDeliverable.ts`、`useGeneratedFile.ts` | `hooks/deliverables/` | 成果及文件读取 |

`MessageComposer`、`AssistantSuggestions`、会话主体、消息主体和已有 reply 分组保持原位。`api/`、`lib/`、`utils/` 的请求与纯函数边界不变，避免为了靠近组件而形成反向依赖。公共媒体组件继续由工作与聊天共用。

### 服务端迁移清单

以下路径以 `apps/server/app/` 为根。默认保留原文件名；表中新增 Python 子包补空 `__init__.py`。

| 当前目录/文件 | 目标目录 | 职责 |
| --- | --- | --- |
| `agent/tools/{actions,work,work_records,reports,team}.py` | `agent/tools/business/` | 公司业务查询和操作工具 |
| `agent/tools/{documents,web,messages,deliverables}.py` | `agent/tools/resources/` | 文档、公开资料、消息和私人成果工具 |
| `agent/tools/{completion,task_context,questions}.py` | `agent/tools/control/` | 收尾、任务解释和提问工具 |
| `agent/tools/execution.py` | `agent/tools/sandbox/` | 自由代码执行与内置沙盒工具同属一处 |
| `agent/context/{conversation_context,deliverable_context,image_context,report_context,work_context}.py` | `agent/context/references/` | 引用素材的读取与上下文构建 |
| `agent/completion/{evidence_consistency,work_receipts}.py` | `agent/completion/evidence/` | 工具与工作回执证据 |
| `agent/completion/{fact_review,quantitative_review,reply_review}.py` | `agent/completion/review/` | 现有可选核对与评测支持 |
| `agent/completion/{budget,query_fallback,response_repair}.py` | `agent/completion/recovery/` | 停止、降级交付与有界修复 |
| `modules/work/{progress,draft_receipts}.py` | `modules/work/drafts/` | 进展草稿确认与回执 |
| `modules/work/{record_commands,record_schemas}.py` | `modules/work/records/` | 工作正文、属性和材料的统一变更契约 |
| `modules/work/{agent_commands,projection}.py` | `modules/work/agent/` | 工具侧的业务适配和工作投影 |
| `modules/messages/{audio,input_text}.py` | `modules/messages/input/` | 多段语音和消息输入文本 |
| `modules/messages/{web_sources,work_references}.py` | `modules/messages/references/` | 网页来源和工作引用 |
| `modules/reports/{parsing,sources,results}.py` | `modules/reports/generation/` | 报告解析、事实来源与结果保存 |

保留的关键文件：

- `agent/tools/{registry,catalog,common,memory}.py` 与既有 sandbox 注册入口；registry 更新导入，不改变工具注册顺序。
- `agent/context/{checkpoints,compaction,context_usage,history,request_clock,task_context}.py`；基础上下文和任务身份继续保留稳定位置。
- `agent/completion/{completion,delivery,prose,answer_length}.py`；尤其保留历史完成元数据的契约文件，不因名字像旧功能而删除。
- 各业务模块的 `models.py`、HTTP 入口和通用保存/查询文件；工作既有 `content/`、`materials/`、`updates/`，报告既有 `scheduling/`。
- `core/`、`security/`、`tasks/`、模型协议适配等已有分层；本次不按文件数强行拆分。

移动前检查被迁移类型是否参与模块全名序列化；若存在此类依赖，保留对应契约定义原位并在迁移表记录具体原因，不建立旧路径转发包。

### 测试目录与辅助代码

保留 `tests/server/` 与 `tests/web/` 作为测试入口。下表按被测职责归组，前缀仅辅助定位；跨领域测试按主要断言归属，不自动按文件名机械分配。

| 目标位置 | 收纳范围 |
| --- | --- |
| `tests/server/agent/{tools,execution,completion,context,memory,streaming}/` | 工具发现/循环，授权与操作，答案交付，上下文，记忆，流式行为 |
| `tests/server/modules/{auth,members,work,reports,team,conversations,materials,model_services,support}/` | 各业务模块的 HTTP 与服务行为；materials 覆盖文档、附件解析及来源 |
| `tests/server/tasks/` | 任务预算、租约、取消、重试、回执恢复和进程恢复 |
| `tests/server/integrations/{models,sandbox,voiceprints}/` | 模型传输、沙盒执行、声纹与桌面服务集成 |
| `tests/server/contracts/` | API 清单、请求参数、配置路径和输入边界 |
| `tests/server/scenarios/` | 综合业务流程、完整系统与故障注入场景 |
| `tests/server/audit/` | `test_agent_audit*.py` 等审计脚本专用用例 |
| `tests/server/_support/{agent,http,materials,work}/` | 已被多处引用的受控模型、数据工厂、请求辅助与样本；内部按实际需要保留有名文件 |
| `tests/server/probes/` | `full_system_worker_probe.py`、`sandbox_worker_probe.py` 等测试子进程入口 |
| `tests/web/{assistant,forms,model-services,navigation,resources,requests}/` | 非 DOM 测试按聊天、表单、模型服务、导航、资源状态和请求归组 |
| `tests/web/dom/{assistant,auth,work,members,settings,feedback,shell}/` | DOM 用例按用户功能归组 |

保留 `tests/server/conftest.py`、`tests/server/test_architecture.py`、`tests/web/setup.ts`、`tests/web/architecture.test.ts`、`tests/web/dom/helpers.tsx` 在共同入口。不新增同名 fixture 遮蔽父目录，也不让每个子目录重复安装全局 setup。

实施前生成逐文件迁移清单，覆盖两个测试入口下所有待整理文件，确保每个文件只有一个目标。对于 `test_company.py`、`test_business_actions.py`、`test_response_delivery.py` 等兼具测试和公共辅助代码的文件，只提取被复用的辅助定义，原测试与断言保持完整。`fakes.py`、样本与评测数据归入相应 `_support` 子目录，不能搬到生产模块。

## 改造后的目录树

标记：`[新增]` 为新容器或文件，`[移动]` 为已有实现迁入，`[修改]` 为原位更新引用/规则，`[保留]` 为相关稳定边界，`[删除]` 只删除迁移后空目录。花括号表示多个同级名称，`*` 表示迁移清单中已有文件，不代表新增功能。

```text
apps/web/src/features/assistant/
├── components/
│   ├── composer/
│   │   ├── MessageComposer.{tsx,module.css}       [修改] 输入主体，更新引用
│   │   ├── AssistantSuggestions.{tsx,module.css} [保留]
│   │   ├── attachments/                         [新增] 附件组合
│   │   │   ├── ComposerAttachments.*            [移动]
│   │   │   └── ComposerAudioPreview.*           [移动]
│   │   ├── controls/                            [新增] 底部控制项
│   │   │   ├── ContextUsage.*                   [移动]
│   │   │   ├── ExecutionModePicker.*            [移动]
│   │   │   └── ReasoningEffortPicker.*           [移动]
│   │   └── reasoning/                           [删除] 迁空后删除
│   ├── conversation/
│   │   ├── {ConversationChat,Conversations}.*   [修改] 更新导入
│   │   └── controls/                            [新增]
│   │       └── {ConversationPicker,PersonaPicker}.* [移动]
│   └── messages/
│       ├── {ChatHistory,MessageCard}.*          [修改] 更新导入
│       ├── transcript/                          [新增]
│       │   ├── MessageTranscript.*              [移动]
│       │   └── TranscriptEditor.tsx             [移动]
│       └── reply/                               [保留] 流式正文与来源
└── hooks/
    ├── conversation/                            [新增/移动] 4 个现有 Hook
    ├── composer/                                [新增/移动] 4 个现有 Hook
    ├── preferences/                             [新增/移动] 3 个现有 Hook
    └── deliverables/                            [新增/移动] 2 个现有 Hook

apps/server/app/
├── agent/
│   ├── harness.py                               [修改] 装配路径，流程不变
│   ├── tools/
│   │   ├── {registry,catalog,common,memory}.py  [保留/修改] 公共注册和辅助
│   │   ├── business/                            [新增/移动] actions、work、work_records、reports、team
│   │   ├── resources/                           [新增/移动] documents、web、messages、deliverables
│   │   ├── control/                             [新增/移动] completion、task_context、questions
│   │   └── sandbox/execution.py                 [移动] 归入已有沙盒目录
│   ├── context/
│   │   └── references/                          [新增/移动] 5 类引用上下文
│   └── completion/
│       ├── {completion,delivery,prose,answer_length}.py [保留/修改]
│       ├── evidence/                            [新增/移动] 证据与回执
│       ├── review/                              [新增/移动] 现有可选核对
│       └── recovery/                            [新增/移动] 有界恢复与降级交付
└── modules/
    ├── work/
    │   ├── drafts/{progress,draft_receipts}.py   [新增目录/移动文件]
    │   ├── records/{record_commands,record_schemas}.py [新增目录/移动文件]
    │   ├── agent/{agent_commands,projection}.py  [新增目录/移动文件]
    │   └── {router,schemas,commands,queries,service}.py [修改] 更新引用
    ├── messages/
    │   ├── input/{audio,input_text}.py           [新增目录/移动文件]
    │   └── references/{web_sources,work_references}.py [新增目录/移动文件]
    └── reports/
        └── generation/{parsing,sources,results}.py [新增目录/移动文件]

tests/
├── server/
│   ├── conftest.py                              [保留/必要修改] 全局 fixture 作用域
│   ├── test_architecture.py                     [修改] 覆盖新目录，约束不放宽
│   ├── _support/{agent,http,materials,work}/    [新增/移动] 共享辅助与固定样本
│   ├── agent/{tools,execution,completion,context,memory,streaming}/ [新增/移动]
│   ├── modules/{auth,members,work,reports,team,conversations,materials,model_services,support}/ [新增/移动]
│   ├── tasks/                                   [新增/移动] 生命周期与恢复
│   ├── integrations/{models,sandbox,voiceprints}/ [新增/移动]
│   ├── contracts/                               [新增/移动] 请求与配置契约
│   ├── scenarios/                               [新增/移动] 跨领域场景
│   ├── audit/                                   [新增/移动] 专项审计用例
│   └── probes/                                  [新增/移动] 测试进程入口
└── web/
    ├── {setup.ts,architecture.test.ts}           [保留/必要修改] 共用入口与边界
    ├── {assistant,forms,model-services,navigation,resources,requests}/ [新增/移动]
    └── dom/
        ├── helpers.tsx                          [保留] 共用 DOM 辅助
        └── {assistant,auth,work,members,settings,feedback,shell}/ [新增/移动]

scripts/company/
├── test-server.py                               [保留] npm 测试入口与 sandbox 分进程
└── web-acceptance/
    ├── inventory.py                             [修改] 递归发现测试，更新工具导入
    └── agent-audit/
        ├── fixed.py                             [修改] 发现规则，保留默认排除范围
        └── faults.py                            [修改] 显式测试路径，保留隔离保护
docs/architecture.md                             [修改] 当前目录、调用路径与放置规则
constitution/tech-stack.md                       [修改] 同步实际模块路径
specs/
├── README.md                                    [修改] Spec 索引
└── spec-061-directory-organization/
    ├── spec.md                                  [新增] 本次需求与边界
    └── plan.md                                  [新增] 本计划
```

树中未逐个展示的调用者、测试与基准脚本，只允许修改被迁移模块的导入或路径。实施时在逐文件清单中补齐，不能据此扩展成业务重构。当前生效的 README/其他指引若含失效路径，原位更正；历史报告不改。

## 修改顺序

1. **冻结基线**：检查工作区；记录源码文件清单、测试收集结果、API Schema、工具契约与注册顺序，列出所有字符串路径和现有跳过条件。测试比较使用旧路径→新路径映射，不能直接比较含路径的 node ID。
2. **整理 Web 聊天模块**：逐组移动组件及样式，再归组 Hook，同批更新所有调用方；保留原 CSS 导入顺序和相对资源含义。
3. **整理后端 Agent**：先工具，再上下文和完成处理；每组更新全部引用，包括 harness、业务适配、测试和脚本。保留对外工具与持久化身份。
4. **整理后端业务子域**：工作、消息、报告依次迁移；原位入口调用同一套函数，不新增第二条写入通道。
5. **整理测试**：先提取现有公共辅助定义，再移动测试；最后更新测试发现、probes 和验收脚本。共享 fixture 不改作用域。
6. **同步当前文档并验收**：记录最终路径与必要例外，执行相称检查；由新的独立验收 Agent 对照本 Spec 审查。

各批内部是耦合迁移，由一个实施 Agent 串行完成；不安排多名实施者同时修改导入和测试路径。

## 数据流与接口变化

数据流不变：Web 组件 → 所属 feature Hook/API → 唯一请求客户端 → HTTP router → 业务服务；后台任务 → 现有 harness → 统一工具注册 → 同一业务服务。

只改变内部源码路径。API URL、DTO、权限、幂等键、数据库事务、工具名称/Schema/说明、流式事件、模型输入和任务状态均不变。规范化契约快照应忽略确属文件定位的内部元数据，但不能忽略用户或模型可见的字段差异。

## 测试计划

本次**写 Spec 为 S0**，只检查文档 diff、范围一致性与引用，不运行测试、构建或 lint。

未来实施涉及跨模块导入、工具注册、持久化恢复及测试发现，按 **S3 的结构迁移风险**验证。全面指受影响的 Web/服务端子系统，不自动扩展为完整桌面打包、真实 ASR 或付费模型评测。

| 检查 | 范围与证据 |
| --- | --- |
| 迁移和静态路径 | 检查重命名 diff、新旧路径引用、大小写、动态导入、mock 路径、子进程和相对资源；使用项目格式化器整理修改的源码 |
| 用例发现 | 迁移前后使用项目测试环境记录 pytest 收集结果、Web 测试列表；按映射比对函数及参数用例，确认无遗漏/重复，检查审计脚本排除条件 |
| 契约一致性 | 对照规范化 OpenAPI 与工具集合/名称/Schema/描述/顺序；检查模型提示与默认调用路径未改。复用现有架构、工具目录与契约测试 |
| Web 子系统 | `npm run typecheck:web`、`npm run test:web`、`npm run build:web`；覆盖新导入、CSS、懒加载及已迁移的 DOM 用例 |
| 公司后端子系统 | `npm run test:server`，使用专用测试数据库与受控模型；该命令含原有隔离的 sandbox 协议测试，不混用两个 app 包 |
| 用户流程 | 复用受控用例验证普通聊天逐步输出、资料/搜索工具、工作创建/更新/材料、临时问答、记忆、报告及执行取消/重试恢复；确认没有额外调用或重复写入 |
| 页面检查 | 在桌面与窄屏核对聊天、附件预览、权限/上下文/强度选择、转写编辑、会话/人设切换；只验证迁移影响，不重新全量截图审美评审 |
| 历史兼容 | 使用受控的既有会话、任务状态和 checkpoint 样本验证读取/恢复；若迁移清单涉及被序列化类型，必须保留身份并做对应回归 |
| CI | 原有工作流继续覆盖平台与集成；只有在显式路径失效时改必要引用，不新增重复任务、真实模型调用或延长总超时 |

分批开发优先最相关的现有检查；最终子系统测试覆盖后，不重复单独运行已包含的同一架构测试。检查通过且相关文件未再修改就停止，不顺便修复无关失败。独立验收优先复核已有证据，只有具体疑点或缺口才追加定向检查。

不承诺真实模型输出逐字一致；本次以固定输入、受控工具和契约保持功能、调用次数及断言等价。真实模型的文字质量和上游响应速度不作为纯路径迁移的验收目标。

## 风险

| 风险 | 处理 |
| --- | --- |
| 测试数量下降却仍全绿 | 对照迁移前后收集清单，修复非递归扫描，逐项解释选择范围差异 |
| 跨测试导入失效或 fixture 重复初始化 | 提取公共辅助到 `_support`，保持唯一父 fixture；不把所有子目录加入搜索路径 |
| 循环导入或导入时额外副作用 | 具体模块导入、空包入口，保留装配与业务依赖方向，检查工具注册唯一性 |
| 同名 Pydantic 类型改变 API/工具 Schema | 对照契约快照；必要时将契约定义原位保留，不改变对外类型标识 |
| 旧 checkpoint 或动态字符串找不到模块 | 移动前确认序列化/注册身份；稳定契约原位保留，恢复用例定向验证 |
| CSS 相对路径与先后顺序改变 | 组件与私有样式一同迁移，检查资源引用、公共样式加载与受影响交互 |
| 搬目录夹带行为重写 | 以重命名与导入 diff 为主，辅助提取不改断言，独立审查逻辑差异 |

## 迁移与回滚策略

无需数据库或业务数据迁移。每批源码移动与引用更新必须完整，不能交付半搬迁状态；旧位置无空壳实现。确认工具名、任务身份与持久化契约不变后，继续沿用既有部署流程，发布时 API 和 worker 使用同一版本。

按完整批次回退代码即可恢复旧目录，不清理会话、checkpoint、文件或数据库。Git 提交/推送由用户另行要求，不在本 Spec 编写阶段执行。

## 实施迁移记录

- 实际迁移 285 个现有文件：Web 源码 30、后端源码 39、后端测试与辅助 148、Web 测试 68。逐文件对应关系保存在 `artifacts/spec061/migration-map.json`。
- 跨测试复用的 108 个辅助定义提取到 43 个 `_support` 模块，记录在 `artifacts/spec061/helper-extractions.json`。原测试保留名称、参数化、断言与隔离标记；共用根 fixture 未移动，Redis 的文件专用 fixture 仍留在原用例文件。
- 原先直接调用其他测试的数据库、媒体、进程和 Redis 故障场景改为调用支持模块中的同一场景；原用例保留包装入口。worker probe 通过明确路径读取，审计使用临时 probe 时传入路径，取消依赖修改模块 `__file__` 的定位方式。
- 测试清单递归发现；候选 API 映射静态读取测试所导入的 `_support` 源码，避免提取请求辅助后漏掉候选。该过程不执行辅助模块、不把辅助代码当作测试，也不改变默认审计排除名单。
- 未发现需要保留旧路径的新增序列化例外。`RunContext`、Graph 节点、完成交付契约、ORM 和入口保持原位；被移动的 Pydantic 输入对象及核对结果在调用内使用，持久化结果仍为原来的 JSON／消息结构。完整 OpenAPI 与工具契约快照未变。
