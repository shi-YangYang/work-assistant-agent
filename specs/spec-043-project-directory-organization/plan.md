# 实施计划

## 范围

按[规格](spec.md)整理 Web 前端、公司后端及 Electron 渲染层／本地核心，不改变功能。

## 改造后的目录

`[移]` 表示迁移既有文件或文件组，`[改]` 表示原位更新引用／说明，`[留]` 表示保留路径。`{A,B}` 表示所列文件；新增 Python 子包仅补必要的空 `__init__.py`。

```text
apps/web/src/
├── app/
│   ├── {App,AppRoutes,route-page}.tsx                  [改] 入口、路由与失败恢复引用
│   └── layout/                                      [移] Shell、Sidebar、Topbar、Breadcrumbs
│       ├── *.tsx + 对应 *.module.css                       原组件和私有样式
│       └── {navigation-items,useNavigationDrawer}.ts       导航配置与抽屉逻辑
├── pages/*.tsx                                      [改] 保留轻量路由入口，更新导入
├── components/
│   ├── actions/                                     [移] Actions、BusyButton、Pagination 及私有样式
│   ├── forms/                                       [移] FormField、TimeField、PeriodFilter、
│   │                                                      AutoTextarea、SearchInput、ConflictRecovery
│   ├── feedback/                                    [移] ErrorNotice、ErrorNoticeScope、
│   │                                                      Empty、PageLoading、Status
│   ├── overlays/                                    [移] Modal、CommandPalette
│   └── content/                                     [移] Markdown、PanelSection、RecordEmpty
├── styles/
│   └── patterns/                                    [移] 多组件／跨业务共享样式
│       ├── {AuthLayout,FormField,Modal,Notice}.module.css
│       └── {RecordDetail,RecordLayout,SearchInput,Status}.module.css
└── features/
    ├── assistant/components/
    │   ├── conversation/                            [移] 会话容器、选择、人设和顶部提示
    │   ├── composer/                                [移] 输入、附件预览、录音预览、
    │   │                                                  执行模式、上下文用量和快捷建议
    │   ├── messages/                                [移] 历史、消息卡片、语音文字与修正
    │   ├── interactions/                            [移] 业务确认、临时回答框
    │   ├── attachments/                             [移] 文档、图片和 PDF 预览
    │   ├── deliverables/                            [移] 成果正文、详情与生成文件
    │   └── work-reference/                          [移] 引用工作标签与选择器
    ├── model-services/components/
    │   ├── {ModelServices,Routing}.tsx               [改] 组合入口
    │   ├── service/                                 [移] 服务列表、连接、编辑和离开／删除弹窗
    │   ├── catalog/                                 [移] 模型选择、选项和推理预设
    │   ├── testing/                                 [移] 模型测试输入与结果
    │   └── usage/                                   [移] 模型用量页及样式
    ├── work/components/
    │   ├── overview/                                [移] 工作列表、筛选与页面组合
    │   ├── detail/                                  [移] 工作详情、修订历史与样式
    │   └── editor/                                  [移] 创建、编辑、进展编辑和表单字段
    ├── reports/components/
    │   ├── overview/                                [移] 报告列表、汇报待办和操作
    │   ├── detail/                                  [移] 报告详情、正文、来源与样式
    │   └── notifications/                           [移] 汇报通知及样式
    ├── auth/components/
    │   ├── login/                                   [移] 登录表单、书本、背景和钉钉入口
    │   ├── configuration/                           [移] 登录方式与钉钉配置
    │   ├── desktop-connect/                         [移] 桌面授权页及样式
    │   └── DingTalkResult.tsx                        [改] 业务内共用的授权结果
    └── settings/components/
        ├── account/                                 [移] 账户页、密码表单与样式
        ├── appearance/                              [移] 外观页及样式
        └── rules/                                   [移] 汇报规则页及样式

apps/desktop/src/renderer/
├── {App,main}.tsx                                    [改] 保留入口，更新导入
├── components/navigation/                           [移] Navigation.tsx
├── features/
│   ├── meetings/
│   │   ├── library/                                 [移] MeetingLibraryList、meeting-library-query
│   │   ├── workspace/                               [移] MeetingWorkspace、MeetingDetailHeader、
│   │   │                                                  MeetingActions、MeetingProcessingState
│   │   ├── transcript/                              [移] Transcription、TranscriptionToolbar、SpeakerPanel
│   │   ├── minutes/                                 [移] MeetingMinutes、MinutesAnalysis
│   │   ├── playback/AudioPlayer.tsx                 [移] 会议音频播放
│   │   └── lib/meeting-processing-queue.ts           [移] 会议处理队列
│   └── settings/
│       ├── company/CompanySettings.tsx              [移] 公司连接与声纹同步
│       └── models/                                  [移] ModelSettings、LocalModelSettings、useModelSettings

apps/server/app/
├── {main,worker,cli}.py                              [改] 入口原位，按需更新导入
├── agent/
│   ├── {harness,reports}.py                         [改] 图编排与报告生成入口
│   ├── context/                                    [移] 历史、上下文、压缩、用量与 checkpoint
│   ├── runtime/                                    [移] 模型调用、中间件与工具节点适配
│   ├── prompts/                                    [移] 人设、角色能力与执行模式提示词
│   ├── actions/                                    [移] 意图授权、操作、建议、提问与事项关联
│   ├── completion/                                 [移] 结果核对、交付、修正与查询兜底
│   └── tools/                                      [改] 保留按工具领域组织，更新导入
├── tasks/
│   ├── {context,lease,models,router,serializers}.py  [改] 公共契约、租约与接口原位
│   ├── runtime/                                    [移] 队列、worker 槽位、中断与续接
│   ├── processing/                                 [移] 消息、语音、文档与声纹处理器
│   ├── feedback/                                   [移] SSE、节点外反馈、用量、事项与结果状态
│   ├── nodes/                                      [移] 节点执行、状态与失败分类
│   ├── maintenance/                                [移] 定期调度与清理
│   └── retry/                                      [留] 独立可复用重试机制
├── modules/
│   ├── conversations/
│   │   ├── context/                                [移] JSONB 上下文、用量与失效
│   │   └── task/                                   [移] 持续任务状态与输入结构
│   ├── reports/scheduling/                         [移] 汇报安排、待办与规则接口
│   ├── operations/
│   │   ├── mutations/                              [移] 写入、删除、发布与报告完成
│   │   └── policy/                                 [移] 执行策略与操作规则
│   └── model_services/usage/                       [移] 用量记录、查询与接口
├── http/                                            [改] 仅更新受影响的路由／依赖引用
└── {core,db,security,integrations,migrations,assets}/ [留] 原职责与路径，按需修正导入

apps/desktop/core/src/paa_core/
├── {__main__,protocol,runtime_check}.py              [改] 入口与协议原位，更新导入
├── {repository,meeting_library}.py                  [留] 公共仓储与会议查询／导出
├── audio/                                          [移] recorder、audio_store
├── asr/                                            [移] asr_worker、transcription、transcript_store
├── speakers/                                       [移] speaker_worker、speaker_store、speakers、voiceprints
├── models/                                         [移] inference_device、model_catalog、model_manager
└── minutes/                                        [移] llm_provider、meeting_summary、summary_store

tests/web/                                           [改] 模块导入、mock、结构检查中的路径
tests/desktop/                                       [改] 受影响的导入与源码定位
tests/core/                                          [改] Python 导入、patch、子进程和资源引用
tests/server/                                        [改] 导入、monkeypatch、架构检查及恢复场景路径
tests/e2e/desktop/                                   [改] 仅在存在旧源码路径引用时更新
scripts/{company,desktop,benchmarks}/                 [改] 仅修正引用迁移模块的脚本
docs/architecture.md                                 [改] 新目录规则、样式归属与阅读路径
constitution/tech-stack.md                           [改] 补充组件分组约定
```

Web 每组的私有 `*.module.css` 随对应 TSX 移动；具体共享例外见下表。未列出的 feature、小目录、Web 公共 hooks／lib、Electron `index.html`／`env.d.ts`／样式入口保持原位。`AppRoutes.module.css` 保留原位。

## Web 迁移清单

下表目标为 `features/<业务>/components/<分组>/`；每项携带其现有私有样式，不新增空样式文件。

| 业务／分组 | 既有文件／组件 |
| --- | --- |
| `assistant/conversation` | Conversations、ConversationChat、ConversationPicker、PersonaPicker、AssistantNotice |
| `assistant/composer` | MessageComposer、ComposerAttachments、ContextUsage、RecordingPreview、ExecutionModePicker、AssistantSuggestions |
| `assistant/messages` | ChatHistory、MessageCard、MessageTranscript、TranscriptEditor |
| `assistant/interactions` | BusinessActionCard、QuestionPanel |
| `assistant/attachments` | Documents、ImageGallery、PdfPreview |
| `assistant/deliverables` | Deliverable、DeliverablePanel、GeneratedFiles |
| `assistant/work-reference` | WorkReferenceChip、WorkReferencePicker、WorkReference.module.css |
| `model-services/service` | ServiceEditor、ServiceConnectionFields、ServiceList、ServiceModelLibrary、EnvironmentServices、RemoveServiceDialog、UnsavedKeysDialog |
| `model-services/catalog` | ModelOptions、ModelPicker、ReasoningPresetEditor |
| `model-services/testing` | ModelCheckResult、ModelTestDialog |
| `model-services/usage` | ModelUsagePage |
| `work/overview` | WorkOverview、WorkList、WorkFilters |
| `work/detail` | WorkDetail、WorkHistory |
| `work/editor` | CreateWork、WorkEditor、ProgressEditor、ProgressFields |
| `reports/overview` | ReportsOverview、ReportObligations、ReportActions |
| `reports/detail` | ReportDetail、ReportBody、ReportSources |
| `reports/notifications` | ReportNotifications |
| `auth/login` | Login、LoginBook、LoginBackground、DingTalkLogin |
| `auth/configuration` | LoginMethods、LoginConfiguration |
| `auth/desktop-connect` | DesktopConnect |
| `settings/account` | AccountPage、PasswordForm |
| `settings/appearance` | AppearancePage |
| `settings/rules` | RulesPage |

共享样式处理：

- 当前 `components/{AuthLayout,FormField,Modal,Notice,RecordDetail,RecordLayout,SearchInput,Status}.module.css` → `styles/patterns/`，文件名和内容保持；同步所有调用方。
- Conversations／AssistantNotice、Deliverable／DeliverablePanel、WorkDetail／WorkHistory、WorkReferenceChip／WorkReferencePicker 共用的样式随所在组移动，不复制。
- 助手附件、登录、模型服务、团队及声纹的 feature 级共享样式保持原位。
- TaskProgress／TaskNode 及其共用样式只有四个相关文件，其他小型业务目录同样不强行拆层。

## 公司后端迁移清单

下表文件均为既有 `.py`，文件名保持；目标路径相对 `apps/server/app/`。

| 旧目录 | 目标子目录 | 迁移文件 |
| --- | --- | --- |
| `agent/` | `agent/context/` | checkpoints、compaction、context_usage、conversation_context、deliverable_context、history、image_context、report_context、task_context、work_context |
| `agent/` | `agent/runtime/` | model、middleware、tool_nodes |
| `agent/` | `agent/prompts/` | persona、policies、execution_mode |
| `agent/` | `agent/actions/` | intent、operations、suggestions、interactions、task_items、task_outcomes |
| `agent/` | `agent/completion/` | completion、delivery、reply_review、response_repair、query_fallback |
| `tasks/` | `tasks/runtime/` | queue、runner、cancellation、conversation_activity、interactions、waiting |
| `tasks/` | `tasks/processing/` | handlers、asr、documents、voiceprints |
| `tasks/` | `tasks/feedback/` | feedback、feedback_state、context_feedback、items、outcomes |
| `tasks/` | `tasks/nodes/` | node_execution、node_failures、node_state |
| `tasks/` | `tasks/maintenance/` | maintenance、scheduling、cleanup |
| `modules/conversations/` | `modules/conversations/context/` | context_store、context_usage、context_invalidation |
| `modules/conversations/` | `modules/conversations/task/` | task_schemas、task_state |
| `modules/reports/` | `modules/reports/scheduling/` | schedule、obligations_router、rules_router |
| `modules/operations/` | `modules/operations/mutations/` | writes、deletion、publication、report_completion |
| `modules/operations/` | `modules/operations/policy/` | execution_policy、rules |
| `modules/model_services/` | `modules/model_services/usage/` | usage、usage_router |

- `tasks/context.py`、`lease.py` 和各业务 `models.py` 保持原位，降低公共类型、租约和 ORM 路径变化的风险。
- `operations/targets.py` 包含目标查询和操作预览，保留业务根目录，不误归为纯策略；`reports/periods.py` 同时服务普通报告与安排，保留原位。
- 消息、工作、认证、成员等已有明确 router／service／queries 分工的目录不按文件数机械拆层。沙盒控制服务只有六个职责明确的文件，保留结构。
- 后端架构测试中存在具体模块路径规则；迁移时更新目标并保留反向依赖、循环、ORM 和入口隔离断言，不能仅让旧检查因路径变化而失效。

## 桌面核心与运行路径

本地核心迁移文件已逐项列在目录树，公共仓储、协议、包名和 `__main__.py` 入口保留；桌面 main／preload 不迁移。

- 更新 `protocol.py`、各功能之间的相对导入，及测试／基准脚本中的 `paa_core.*` 引用。
- 更新 `scripts/desktop/build-core.mjs` 对说话人模块的导入，保留 PyInstaller 入口和资源打包位置。
- 修正 `speaker_worker.py` 移动后的开发态权重定位；冻结模式继续使用原资源位置。检查 spawn 子进程导入与懒加载，不能提前加载推理库。
- SQLite 表、迁移函数、用户目录、模型目录、录音文件路径、运行参数和 JSON Lines 协议保持不变。

## 修改顺序

1. 记录受影响文件的旧→新路径、CSS 共享调用方和持久类型路径，读取现有测试／脚本中的路径依赖。
2. 迁移 Web 公共组件和共享样式，统一更新使用方；随后迁移布局和各业务组件组。
3. 迁移公司后端的业务子域、任务文件组和 Agent 文件组，逐组修正普通／延迟导入及架构测试中的路径；保留模型定义与入口。
4. 按导航、设置、会议迁移 renderer，再整理本地核心；修正相对 `shared/`、资源路径、子进程与构建脚本导入。
5. 同步测试 mock、动态 import、路径扫描及当前架构说明；检查文件唯一去向与旧路径残留。
6. 按下列范围验证，实施 Agent 返回结果；新的独立验收 Agent 审查目录、依赖、行为保持和验证证据。

同一应用内的引用高度关联，由同一实施 Agent 顺序处理。Web、公司后端、Electron 分属三个实施 Agent，分别独占对应应用及测试目录；协议不变，跨应用脚本引用与文档由主 Agent 汇总，完成后统一独立验收。

## 数据流与接口

数据流、对外接口和数据持久化均不变，只调整内部模块路径。组件名、导出名、请求函数、IPC、路由、工具／图节点名、提示词和样式声明保持。测试与业务代码一次更新到新路径，不保留旧路径转发层。涉及持久化限定类型名时保留定义原位，不迁移历史数据。

## 验证计划

当前 Spec 文档为 S0，只检查 diff、需求与引用。正式实施属于跨模块目录重构，按 S3 验证受影响的前后端范围：

- Web：`npm run test:web`、`npm run typecheck:web`、`npm run build:web`；其中现有架构测试继续覆盖循环、分层及 CSS 归属。
- 公司后端：`npm run test:server`，覆盖全量现有服务端测试及独立进程的沙盒协议测试。检查迁移前后 OpenAPI 路径／方法和注册工具名称不变，权限与幂等断言保留。
- Electron：`npm run test:unit`、`npm run test:python`、`npm run typecheck`、`npm run build`；固定输入覆盖录音、转写、纪要、模型与声纹逻辑，不下载模型或做真实推理。
- 格式化和 ESLint 仅覆盖移动／修改的源码；目录迁移不得通过删断言、放宽依赖约束或删除测试来通过。
- 复核动态加载、资源路径、大小写及 CSS 导入顺序。当前文档和测试引用必须修正，历史 Spec 中的旧路径不算遗漏。
- 视觉检查覆盖迁移所涉及的 Web 页面入口及公共弹窗／表单，至少包括登录、助手、我的工作／报告、团队、模型服务、账户和设置；重点核对错误提示、附件、窄屏布局和 CSS 加载。
- Electron 使用现有日常环境检查会议列表／详情、播放器／转写／纪要及设置页；不触发付费生成、不录制新会议、不修改用户资料。不能运行的环境如实记录。
- 使用隔离测试数据库／临时用户目录做 API、worker、本地核心启动与停止检查。通过既有受控模型与固定输入覆盖发送→工具执行→完成、重试、中断、待回答／确认后的续接、报告生成及既存会话／会议读取；不能通过删除旧 checkpoint 或清空数据库来通过。
- 源码和冻结资源路径、spawn 入口需定向验证；若引用分析或检查暴露冻结模块遗漏，再执行本机 `npm run build:core`，不默认叠加双平台安装包与安装卸载测试。

不运行真实付费模型、硬件推理和沙盒破坏性套件。已有完整模块测试覆盖的场景不再另起一轮重复测试；检查通过且相关文件未再变动，不重复执行。

## 风险与回退

- 深层相对导入、测试 mock 和动态 import 容易漏改：使用完整路径映射，并由类型检查、现有测试及构建覆盖。
- 同名 CSS 不等于私有样式：先确认使用方再归档，保持声明和导入顺序，避免层叠变化。
- 大量移动掩盖逻辑修改：按功能组审查重命名 diff，除路径修正外的变更必须说明必要性。
- Python 包与同名旧模块切换可能产生残留引用，延迟导入／monkeypatch 也需要迁移；保持既有加载时机，避免引入循环与重复模块身份。
- 后端持久状态与桌面冻结资源不能按普通导入迁移推定兼容；保持类型定义、图节点标识与模型位置，针对恢复和路径定位检查。
- 无数据库迁移。回退仅恢复代码路径和引用，不回滚数据、不清理缓存，不覆盖用户已有修改。
