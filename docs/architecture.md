# 技术架构

同仓库维护独立的桌面应用、公司 Web 与后端，根目录提供统一开发命令。实际版本与目录见 [技术栈](../constitution/tech-stack.md)，安装部署见[使用指南](setup.md)，迁移取舍见 [决策 0015](../.ai/decisions/0015-multi-client-repository.md)。

## 应用与服务

```text
Electron renderer ──受限 preload API──→ Electron main
                                        │ JSON Lines／stdio
                                        ▼
                              内置 Python 本地核心
                              ├─ 麦克风 → WAV
                              ├─ 本地模型 → 转写
                              ├─ 在线模型 → 纪要
                              └─ SQLite／用户数据目录

电脑／手机浏览器 ──HTTPS──→ Caddy ──/api──→ 公司 API
                            │               │
                            └─ Web 静态文件  ▼
                                      PostgreSQL ←→ worker／harness
                                      私有附件卷      │
                                                      ▼
                                               外部模型／ASR API
```

Electron 保留本地会议能力；公司 Web 与后端处理账号、员工消息、文件、工作、报告及授权团队问答。两者独立运行与发布；桌面 main 可通过 HTTPS 连接公司 API，浏览器授权后同步声纹，不自动上传会议或密钥。未来移动 App 使用公司 API，当前尚未实现。

## 桌面边界

- `apps/desktop/src/main` 管理窗口、权限、核心进程、加密服务配置及受限音频协议；`preload` 只公开类型化业务接口，renderer 不具备 Node、任意 IPC、文件或网络代理权限。
- `apps/desktop/core/src/paa_core` 负责录音、SQLite、模型下载、受管 ASR worker 和纪要任务。录音回调、有界队列、WAV 写盘、推理与网络请求分离，ASR／LLM 延迟不阻塞采集。
- 播放通过授权的 `paa-audio` Range 读取，引用跳转复用同一播放器。原始录音、模型、SQLite 及系统加密配置保存在原 userData；正式包从资源目录启动随包 Python 核心，无需系统解释器。
- 转写任务锁定模型／语言，候选完成后原子发布；纪要固定文字、使用到的发言人信息、输入模式与配置，失败保留旧结果。自动纪要有界等待会后说话人处理，识别后续完成不重复付费生成；仅姓名变化不影响纯文本纪要。见[本地转写模型](../specs/spec-013-local-model-library/spec.md)与[发言人视图及会议分析](../specs/spec-023-speaker-aware-minutes/spec.md)。
- main 加密保存公司凭证和声纹；本地核心分窗识别发言者并在会后校正，保留人工修改。模板长期离线可用，退出账号或清缓存才删除，renderer 不接触令牌或向量。

## 公司业务与 Harness

- `apps/web` 是独立的浏览器应用，通过同源 API 使用公司业务；`services/company/src/paa_server` 同时提供 API 和 worker，二者共用业务服务与数据库，没有按进程拆成多个微服务。
- API 负责会话身份、公司／成员授权、输入校验和业务事务。worker 执行可恢复任务，harness 管理授权上下文、工具、预算、checkpoint 和人工确认；模型不能凭参数更改真实身份或绕过业务权限。
- PostgreSQL 保存业务、修订、任务、文件分段及公司声纹，原件在私有卷。文档解析和声纹提取通过受管子进程进行；声纹使用独立 CPU 运行环境，图片理解／语音转写仍调用外部服务。
- 员工确认工作与提交报告，管理员查看授权业务并创建自己的督办。团队来源依赖贯穿模型输入、历史回答、恢复与确认，撤权／删除后重新校验；具体范围见 [Spec 014](../specs/spec-014-admin-business-assistant/spec.md)。
- 工作检索在服务端授权后分页，看板与明细共用期间和人员范围。worker 将受控聊天反馈写入 PostgreSQL 有界快照，API 经权限复核后通过 SSE 交付；正式结果仍来自业务记录。管理员用量按模型请求记录真实返回值，缺失数据保留未知，见 [Spec 016](../specs/spec-016-web-search-metrics-and-feedback/spec.md)。
- 公司 Key 在服务端加密保存，API 与 worker 使用同一独立私有主密钥；数据库、附件和主密钥分开备份、配对恢复。部署挂载、迁移与备份命令见[使用指南](setup.md)。

## Web 前端组织

`apps/web/src` 按业务组织，路由页面保持轻量：

```text
app/          身份初始化、Provider、路由与应用布局
pages/        路由参数和跨业务页面组合
features/     assistant、work、reports、team、members 等业务
api/          唯一请求客户端、会话代次和错误处理
components/   不主动查询业务数据的公共 UI
hooks/        跨业务复用的 React 逻辑
lib/          上下文和非 React 资源控制器
utils/        无请求副作用的通用纯函数
styles/       全局与公共控件样式
```

业务自己的组件、Hook、API 和工具放在对应 `features/<业务>/` 内，按需建目录；不为每个小函数建立文件，也不把领域逻辑统一堆入根 `hooks`／`utils`。服务端 DTO 复用 `packages/api-contracts`，组件 props 与内部状态就近定义。

依赖由 `app → pages → features → 基础层` 向下组织。跨业务页面在 pages 组合；确需复用业务能力时，直接导入职责明确的具体组件或 API，保持单向依赖。基础层不得导入 app、pages 或 features；纯工具不依赖 React、网络或工作空间。使用 Web 局部 `@web/` 别名，不建立汇总整个应用的 barrel 文件。

新增页面先选业务归属，再定义其请求与状态所有者。页面和展示组件不直接拼请求路径；传输层统一处理身份、CSRF、超时、取消和错误。用户身份、跨页面草稿、服务端资源、URL 筛选与局部弹窗状态分别管理，避免重复持有同一可变状态。拆 Hook 是为了复用或隔离一个完整流程，不是把整页搬进返回几十个字段的函数。

业务 TSX 超过约 350 个非空行时检查是否混合了列表、编辑、弹窗和异步流程；行数是审查提示，不能通过压缩代码或无意义拆碎达标。样式按全局、共享和业务划分，由入口保持确定加载顺序，路由切换不得改变层叠结果。

读“发送一条消息”时，依次看：

1. `app/AppRoutes.tsx`：找到工作助手的路由入口。
2. `features/assistant/components/Conversations.tsx`：选择与恢复会话。
3. `features/assistant/components/ConversationChat.tsx`：协调聊天内容、编辑器和发送流程；输入展示在 `MessageComposer.tsx`，录音生命周期在 `hooks/useRecording.ts`。
4. `features/assistant/hooks/useMessageSubmission.ts`：检查发送条件、依次上传附件、提交消息并处理发送结果；业务请求在 `features/assistant/api/requests.ts`，传输规则在 `api/client.ts`。
5. `features/assistant/components/ChatHistory.tsx`、`MessageCard.tsx`：查看消息、处理反馈与业务结果如何展示。

以上路径均相对 `apps/web/src`。跨页面草稿由 `lib/session-drafts.ts` 管理账号代次，聊天模块的 `lib/composer-drafts.ts` 提供附件清理策略；公共层不需要知道聊天附件的具体结构。

`npm run test:web` 包含架构依赖检查；单独检查可运行 `npm run test:web -- tests/web/architecture.test.ts`。它约束向上依赖、纯工具依赖、绕过业务 API 的请求和运行时循环，新增模块继续遵循这些边界。

## 共享代码与工程边界

`packages/api-contracts` 提供公司 HTTP 的 TypeScript 类型；`model-config` 提供两端使用的纯校验；`ui-web` 提供浏览器 CSS；`voiceprint-engine` 统一公司登记与桌面匹配的模型、预处理和模板规范。共享包不导入应用或服务端，桌面协议留在桌面。CSS 不是原生 Android／iOS UI，移动框架及原生适配尚待立项。

JS 应用由 npm workspaces 管理，各自声明依赖与构建配置；Python 核心与后端保留不同锁文件和虚拟环境。测试仍集中在 `tests`，按对象分区；CI 触发与检查范围见 [工作流](../.github/workflows/ci.yml)，具体通过与未验范围在 [各 Spec 验收](../specs/README.md)。

此前混入本页的旧 schema、协议清单和逐轮状态已归回各 Spec；整理前原文保留在 [6e83d28 快照](https://github.com/shi-YangYang/work-assistant-agent/blob/6e83d289a16a0783705ae17c879d39d1e059e839/docs/architecture.md)，不把旧 CI 结果当成当前代码的验证。
