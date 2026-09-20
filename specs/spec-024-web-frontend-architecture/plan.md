# Web 前端重构实施计划

依据 [功能规格](spec.md)。业务实施与独立验收按现有 Spec 规则分工。

## 模块迁移

| 当前入口 | 目标职责 |
| --- | --- |
| main.tsx、App.tsx、Breadcrumbs.tsx、navigation.ts、CommandPalette.tsx | app 装配／布局／路由，pages 路由适配；纯导航工具与展示分别归属 |
| workspace.ts、session-drafts.ts、connection.tsx、mobile-viewport.ts | 基础身份上下文和网络／视口 Hook；聊天草稿的具体内容与释放留在 assistant，通过清理回调装配 |
| api.ts、paged-resource.ts、list-state.ts、diagnostics.ts | api 传输／错误／身份代次；lib 资源控制器；hooks React 接口；utils 日期与纯诊断格式化 |
| Assistant.tsx、Conversations.tsx、audio-*、files.ts、Documents.tsx、AttachmentPreview.tsx | assistant 的组件、领域 Hook、附件逻辑与 API；公共任务反馈和来源读取另行分离 |
| Records.tsx、RecordManagement.tsx、progress-edit.ts、ReportObligations.tsx | work 与 reports 分开；ProgressFields 从聊天移至 work，通用确认容器保留纯展示 |
| TeamWorkspace.tsx | team 查询／筛选／列表；工作／报告详情由页面层组合 |
| ModelServices.tsx、ModelUsage.tsx、model-service-* | model-services 的 API、服务编辑、模型目录、预设、用途与用量组件 |
| Settings.tsx、DingTalk.tsx、DesktopConnect.tsx、LoginBackground.tsx | members、settings、auth，按页面归属拆分 |
| Support.tsx、Voiceprints.tsx | feedback、voiceprints，各自管理请求与状态 |
| ui.tsx、ListControls.tsx、SearchInput.tsx、Markdown.tsx | 公共控件逐个明确导出；WorkFilters 归 work；业务状态文案归对应模块 |
| styles.css | 全局基础／公共控件与功能样式，app 入口统一安排加载次序 |

以上为职责映射，不要求一旧文件只对应一新文件。跨功能复用点先确认输入／输出，再移动调用者，禁止边迁移边产生循环。

## 修改顺序

1. **建立基线**：记录现有路由、角色入口、会话／草稿键、请求事件和样式加载次序；在日常本地环境保存关键页面的桌面／窄屏对照。已有测试结果可复用，未知基线仅执行相关 Web 检查。
2. **拆基础层**：分离 api 客户端与资源 Hook，迁移纯工具和基础 UI；保持请求身份代次为唯一来源，补路径别名及测试解析。先处理 ui → workspace／api 的隐式依赖，避免迁入新目录后继续倒置。
3. **拆应用壳与简单页面**：整理身份上下文、Provider 装配、路由／导航和布局；迁移成员、普通设置、反馈、声纹与认证页面，保留回调 URL 和桌面授权路由。
4. **拆工作、报告和团队**：先提取工作表单、任务反馈、来源展示；再拆列表与详情、报告待办及通知；最后组合团队详情，移除 Records → Assistant 的导入。
5. **拆工作助手**：会话选择与恢复、消息列表、发送状态、附件选择／预览、录音资源、转写编辑和业务卡分别处理。先声明状态所有者和清理时机，再迁移 Hook；不能靠共享可变对象掩盖两个状态来源。
6. **拆模型服务管理**：服务列表和编辑会话分离；编辑器按模型目录、模型参数、连通性检查及用途拆组件。保留未保存草稿、离开阻止、配置版本和错误恢复，禁止用重新挂载清空状态简化实现。
7. **整理样式与依赖**：先按原顺序划分样式，再迁移至职责目录；检查主题、弹层层级和响应式。移除兼容导出，配置共享层不得向上引用的 ESLint 规则，并用已安装 TypeScript 解析 import／export／动态字面量引用检查运行时循环；类型引用单独对待。
8. **整体收尾**：完成一次 Web 范围验证，独立验收核对行为与结构；在 docs/architecture.md 补目录／新增功能规则与发送链路，AGENTS.md 引用该规则，更新 constitution/tech-stack.md 中实际目录描述。Spec 只保留必要验收结论。

每步形成可理解的改动边界，保持应用可运行；提交仍需要用户指令，不擅自 commit／push。共享入口与聊天高度耦合，优先一个实施 Agent 串行负责，不让多个实施 Agent 同时改路由、公共 Hook 或全局样式。

## 数据流与接口

```text
app：身份／Provider／路由／布局
  → pages：路由参数与跨业务组合
    → feature components + hooks：用户交互、业务状态
      → feature api：明确端点／参数／DTO
        → api client：身份、超时、取消、错误
          → 现有公司 HTTP API
```

HTTP 地址、方法、请求体、响应 DTO 和错误分类均不变，无数据库迁移。页面中的 useResource 调用可使用业务 API 提供的有类型资源描述或读函数；采用最小必要接口，避免为迁移重新设计整个数据请求框架。

应用根维持身份生命周期；领域状态不因组件拆分而提到全局。弹窗获取焦点、Portal 定位、对象 URL 释放、MediaRecorder 停止、监听器／轮询取消都由明确的单一所有者处理。旧会话键和权限校验不改变，纯机械移动不改请求重试策略。

## 验证范围

决策文档按 **S0**：只检查 diff、引用及需求一致性。正式实施属于 **S3**，依据是 Web 全应用重构、共享请求／身份状态和构建解析受到影响；验证覆盖 Web 子系统，不默认运行桌面打包、真实 ASR、全部后端测试或远端 CI。

- 每阶段格式化实际修改的 TS／TSX／CSS／配置，运行受影响的最小测试；阶段后相关代码未变，不重复已通过的检查。
- Web 最终集成运行全量 `npm run test:web`、`npm run typecheck:web`、`npm run build:web`，以及全部 Web／相关测试和配置的 ESLint、改动文件 Prettier 检查；补足关键组件与路由交互回归。阶段中已在最终代码上完成的同一检查不再重复。
- 复用已有 api、use-resource、session-drafts、assistant-session、audio-capture、job-connection、model-service-drafts、navigation、business-actions 等行为测试；同步导入，不删除有效断言迁就重构。只补拆分暴露出的身份／生命周期／职责边界缺口。
- 用本地正常环境核对管理员与员工页面；窄屏检查不冒充手机实机。基线与新页面按相同状态对照，空／有数据、浅／深主题、弹层和焦点至少覆盖改动到的组件。通过 UI 工具验证，测试记录只使用可识别的测试内容，不修改或删除真实业务资料，不自动消耗真实模型配额。
- 架构检查验证共享层反向引用、运行时循环及旧路径残留；不能只靠行数／文件数量宣称重构完成。若 shared package 或根配置实际影响 Electron，追加对应类型／构建兼容检查，不扩大为完整桌面验收。

关键回归场景：

| 范围 | 核对内容 |
| --- | --- |
| 登录／身份 | 密码与钉钉回调、退出／失效、切换账号、旧请求与旧草稿不回流、桌面授权页 |
| 聊天／附件 | 空会话首条消息、会话恢复、中文输入与 Enter、重复发送防护、断网草稿、上传／录音／预览清理、SSE／轮询取消 |
| 工作／报告／团队 | 筛选与分页、详情返回、进展确认、编辑冲突、报告草稿与已提交版本、删除／提交确认、来源失效 |
| 模型与其他设置 | 草稿离开保护、模型列表／手动添加、参数预设、连通性状态、用途配置、成员管理、反馈与声纹页面 |

## 风险与恢复

- 优先移动与职责提取，再调整重复逻辑；避免在同一批 diff 同时改变产品规则。路由／状态和 CSS 是主要回归点，保留行为基线。
- 旧源码入口可暂时重导出以保持每步可运行，最终必须清除；不把新目录包在旧大文件外面就交付。
- 无数据迁移，回退以本次有边界的代码改动为单位；不覆盖任务开始前已有的用户修改，不操作生产部署或数据。
- 验收报告区分固定输入测试、本地实际操作与未覆盖的第三方／实体设备场景。
