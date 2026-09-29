# 技术架构

## 应用与服务

```text
Electron renderer → 受限 preload → main → stdio → Python 本地核心
                                                   ├─ 录音／WAV
                                                   ├─ 本地转写／说话人
                                                   ├─ 在线模型／纪要
                                                   └─ SQLite／用户目录

电脑／手机浏览器 → HTTPS → Caddy → Web 静态文件
                                └─ /api → 公司 API → PostgreSQL
                                                     ↕
                                                  worker／harness
                                                   ├─ 私有附件
                                                   └─ 外部模型／ASR
```

桌面、公司 Web 和后端独立运行与发布。桌面 main 可通过公司 API 登录、同步声纹，不自动上传会议或密钥；本地会议无需公司后端。

## 桌面边界

- `apps/desktop/src/main` 管理窗口、权限、核心进程、加密配置和音频协议；preload 只公开类型化业务接口，renderer 无 Node、任意 IPC、文件或网络代理权限。
- `apps/desktop/core/src/paa_core` 管理录音、SQLite、模型和后台任务。录音回调、写盘、推理与网络请求分离，模型延迟不阻塞采集。
- 音频通过授权的 `paa-audio` Range 读取，引用跳转复用同一播放器；数据保存在 userData，正式包从自身资源启动 Python 核心。
- 转写固定模型、语言和设备，候选成功后原子发布。纪要固定文字、所用发言人信息和配置，失败保留旧结果。
- 自动纪要有界等待会后说话人处理，不因识别稍后完成重复付费生成；仅姓名变化不影响纯文本纪要。
- main 加密保存公司凭证及声纹，renderer 不接触令牌或向量；会后校正保留人工修改，缓存按服务／公司／账号隔离。

## 公司业务与 Harness

- API 负责身份、权限、输入校验和业务事务；worker 执行可恢复任务；harness 管理业务工具、来源、checkpoint 与人工确认。
- 模型不直接读写数据库，也不能靠参数改变身份。员工访问本人资料，管理员团队问答使用已确认业务及关联来源；撤权或删除后复核历史回答和待执行操作。
- PostgreSQL 保存业务、修订、任务、附件分段和声纹；原件在私有卷。解析与声纹提取使用受管子进程，聊天、图片理解和语音转写调用外部服务。
- 检索先授权再分页，看板与明细共用统计范围。处理反馈写入数据库有界快照，API 复核权限后经 SSE 交付；正式结果仍来自业务记录。
- 用量与团队统计在 SQL 中聚合、分页；显式只读路径取得公司共享锁，写入和撤权使用同标识排他锁，禁止事务内锁升级。
- 声纹文件清理先在业务事务中登记意图，再由请求或 worker 重试；历史遗留资料仅由管理员显式清理。
- 模型用量保存真实返回值，缺失为未知。公司凭证由独立主密钥加密，API／worker 共用；数据库、附件、主密钥配对恢复。
- 会话 JSONB 保存可重建的摘要、近期消息和来源版本；新任务补入增量，任务内复用内存上下文。业务表保留原始事实，checkpoint 负责执行恢复，任务用量快照仅用于展示。
- 会话任务状态独立保存持续指令和待补事项；Job 冻结本轮来源及版本，执行、授权和答复核对共用。授权只能来自仍有效的用户输入，不能来自摘要或助手承诺；新请求、中断和来源修订限制旧任务恢复。
- 主模型通过 `finish_task` 同时交付正文和任务摘要，普通答复直接保留，不固定二次审稿。业务执行说明与用户明确要求的事实核验才走专项问题核对；摘要不授予权限，真实状态以回执和阻碍为准。收尾、补执行和正文修正共用一次持久修复额度，工具额度耗尽仍可说明已有结果与未完成范围。
- 业务回执记录真实效果，逻辑事项标识用于续接去重。工具结果区分缺信息、拒绝、参数错误和暂时故障；没有新证据时，不循环重试同一阻碍。任务展示根据回执区分完成、部分完成、等待补充／确认和处理中。
- 会话执行权限分为逐项确认、自动审核、自主执行；独立策略决定是否需要批准，实际角色、公司与来源权限仍由业务服务校验。任务保存模式快照，重试不能取得后来提高的权限；批准只对应所见操作及版本。
- 结构化问题与答案由 `modules/interactions` 持久化，操作批准复用 `BusinessAction`。等待时释放 worker，回答或批准后创建原逻辑任务的续接运行，复用已有回执；刷新和重连不丢失待回答问题。
- 主助手按实际模型窗口估算完整请求，达到 90% 时压缩历史；摘要复用仍校验权限与来源，不能代替有效授权和独立事实核对。

## 公司服务端组织

`apps/server/app` 同时提供 API 和 worker，共用业务模块：

```text
main.py / worker.py / cli.py  HTTP、任务进程、运维入口
http/                       请求依赖、中间件、错误和路由注册
core/                       设置、资源路径、基础输入和版本规则
db/                         连接、公共 Base、ORM 模型登记
modules/                    认证、成员、消息、工作、报告等业务
security/                   公司范围、所有权、来源授权和凭证保护
tasks/                      上下文、租约、队列、处理器和调度
agent/                      提示词、模型、工具、核对和图编排
integrations/               模型／钉钉协议、媒体和解析进程
migrations/ / assets/       数据库迁移、包内资源
```

- 业务模块按需组织 router、schemas、models、commands、service、queries、serializers，不强制建齐。
- router 处理 HTTP 参数与依赖，commands 编排写入，service 保存复用规则，queries 管理复杂查询；HTTP 和 Agent 调用同一套业务能力。
- ORM 定义归业务模块，共用 `db` 的 Base；模型登记只负责完整加载，不作为实体的统一导出入口。
- HTTP 和后台任务各自持有 AsyncSession；配置、ORM、上下文和租约不反向依赖 API、worker 或 harness 装配。
- Python 入口为 `app.main:app`、`python -m app.worker`、`python -m app.cli`，模块根为 `apps/server`。
- 单文件超过约 400 个非空行时检查职责，不靠压缩代码或空层达标。

发送消息的服务端路径：

1. `modules/messages/router.py` → `commands.py:submit_message`，校验幂等键、会话和附件，保存消息与 Job。
2. `http/dependencies.py` 提交请求事务，失败回滚。
3. `tasks/queue.py` 领取任务，`tasks/handlers.py:process_job` 调用 `agent/harness.py`。
4. `agent/tools/` 调用授权业务服务；工作进展确认进入 `modules/work/progress.py:confirm_drafts`，检查版本后保存。

`tests/server/test_architecture.py` 检查反向依赖、循环、ORM 登记和应用实例隔离。

## Web 前端组织

`apps/web/src` 按业务组织：

```text
app/          身份、Provider、路由和应用布局
pages/        路由参数、跨业务页面组合
features/     assistant、work、reports、team、members 等业务
api/          唯一请求客户端、会话代次和错误处理
components/   无业务查询的公共 UI
hooks/        跨业务 React 逻辑
lib/          上下文、非 React 资源控制器
utils/        无请求副作用的通用纯函数
styles/       本端基础 CSS、公共布局和控件 Module
```

- 业务组件、Hook、API 和工具就近放在 feature；服务端 DTO 使用 `packages/api-contracts`，组件 props 和内部状态就近定义。
- 依赖方向为 `app → pages → features → 基础层`。跨业务组合在 pages；基础层不能导入业务，纯工具不依赖 React、网络或工作空间。
- 使用 `@web/` 别名和具体模块导入，不建立汇总整个应用的 barrel。
- 页面不拼请求路径，业务 API 统一经过请求客户端处理身份、CSRF、超时、取消和错误。
- 身份、跨页草稿、服务端数据、URL 筛选和局部弹窗各有明确状态所有者；Hook 负责完整流程，避免重复持有状态。
- 工作助手通过 `features/assistant/api/queries.ts` 显式共享读取，键包含身份代次、公司／成员／角色和完整路径参数；`lib/query-resource.ts` 管理请求、订阅和有限内存生命周期，实际 HTTP 仍由 `api/client.ts` 发出。未接入的页面保持原有策略。
- 会话详情由标题、面包屑和恢复入口共享；消息保留已展开分页。被动刷新只加入正在执行的读取，写入或终态使数据失效时补读一次；完整写入响应直接更新资源。
- `useConversationRefresh` 合并在线／可见恢复，不监听窗口 focus、不轮询。SSE 为实时更新来源，断开后等待明确恢复；身份变化清空资源并忽略旧响应。
- 通用提交 Hook 管理提交快照，会话分页与模型配置控制器分别归所属 feature；异步写回核对账号、记录及执行代次。
- 路由延迟加载，加载与失败恢复留在路由区域，不重置整个应用。
- 业务 TSX 超过约 350 个非空行时检查职责，不机械拆碎。

### Web 样式边界

- 组件样式放在就近的 `*.module.css`；同业务组合样式放 `features/*/styles/`，断点和状态一起维护，不强制创建空样式文件。
- `styles/index.css` 仅导入 `theme.css`、`select.css`、`base.css`；全局类仅保留 `sr-only`、`keyboard-open`，不放页面布局。
- 公共布局与控件使用 `styles/{layout,controls,utilities}.module.css`；工作／报告呈现由 `components/RecordLayout.module.css`、`RecordDetail.module.css` 维护。
- 组件通过 className 插槽、变体或限定用途的变量提供定制；调用者不依赖内层私有选择器，业务不互相导入私有 CSS。
- 不用跨文件 `@value`／`composes`；显式组合 Module 类，基础 CSS 先加载，公共 Module 先于局部 Module 导入。
- 交互状态使用 ARIA／`data-*`；保留 `data-scroll-container`、`data-chat-content`，不在 JS 拼生成类名。`:global(.keyboard-open)` 仅用于手机键盘避让。
- Web 与 Electron 各自维护主题和样式，共享品牌图片。路由切换不得改变层叠结果。

发送消息的前端路径：`app/AppRoutes.tsx` → `features/assistant/components/Conversations.tsx` → `ConversationChat.tsx`／`MessageComposer.tsx` → `hooks/useMessageSubmission.ts` → `api/requests.ts` → `apps/web/src/api/client.ts`。消息和反馈由 `ChatHistory.tsx`／`MessageCard.tsx` 展示，录音由 `hooks/useRecording.ts` 管理。

`lib/session-drafts.ts` 管理账号代次，聊天 feature 的 `lib/composer-drafts.ts` 管理附件清理。`tests/web/architecture.test.ts` 检查依赖方向、请求入口、循环和 CSS 归属。

## 共享代码与工程边界

| 包                  | 职责                                   |
| ------------------- | -------------------------------------- |
| `api-contracts`     | 公司 HTTP 的 TypeScript 类型           |
| `model-config`      | 两端的纯模型参数校验                   |
| `ui-web`            | 品牌图片与 favicon，不导出 CSS         |
| `voiceprint-engine` | 登记和匹配共用的模型、预处理及模板协议 |

共享包不导入应用，桌面 IPC 契约留在桌面。Node 使用 npm workspaces 和根锁文件；Python 核心与公司服务独立锁定依赖。测试集中在 `tests/`，按对象分区，React 交互回归放在 `tests/web/dom/`。

### 声纹引擎

- `packages/voiceprint-engine` 使用固定 WeSpeaker 权重及 16 kHz 单声道 PCM；模板最多 12 个归一化 256 维向量，`MODEL_ID` 标记权重与预处理版本。相似度不是识别准确率。
- 只加载本地权重并校验 SHA256，可用 `PAA_VOICEPRINT_MODEL` 指定路径；不在线下载。生产 CPU 依赖由 `scripts/company/install-voiceprints.py` 安装。
- 固定公共权重统一保存在 `packages/voiceprint-engine/resources/models/speaker-community-1/`。桌面冻结核心打包完整说话人资源，公司 worker 仅打包声纹 embedding；API 和 Web 不携带推理权重。
- 输入为 6 秒至 3 分钟规范 WAV，声音不足时拒绝生成；调用者负责上传校验、单人授权和进程资源限制。
- 成功输出 JSON，失败返回 exit 2 和 `{error:{code,message}}`。员工录音、账号关联和模板属于私有业务数据，不入包或 Git；模型署名随权重保留。

提取命令（Python 3.12，已安装引擎运行依赖）：

```sh
python -m paa_voiceprints enrollment.wav --model packages/voiceprint-engine/resources/models/speaker-community-1/embedding/pytorch_model.bin
```

本地包可用 `pip install './packages/voiceprint-engine[runtime]'` 安装；公开语音验证入口为 `scripts/benchmarks/company-voiceprints.py`。
