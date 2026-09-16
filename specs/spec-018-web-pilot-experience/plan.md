# Plan — Web 试点使用体验

## 对应 Spec 与状态

[Spec 018](spec.md) · ACCEPTANCE。实现与本地独立验收已通过，真机待实测；结果见 [Acceptance](acceptance.md)，实施及返工证据见 [Implementation](implementation.md)。

## 模块与修改顺序

1. **共用请求边界**：扩展 `apps/web/src/api.ts` 的错误对象和响应解析，保留已有调用约定；补齐取消／超时分类、状态与安全诊断。复核 `useResource`、分页读取、`job-feedback.ts` 的恢复触发，避免同时存在多个恢复循环。
2. **会话及发送恢复**：在 `App.tsx` 的身份边界暂存必要聊天输入，授权组件与私有已读数据在失效时卸载；同身份重新登录后重新读取权限并恢复可用输入。`Assistant.tsx`／`files.ts` 固定提交快照和键，迟到结果不能影响新输入；不将草稿序列化到浏览器存储。
3. **首次入口**：复用 `Assistant.tsx` 的空会话组件与 `Conversations.tsx` 首次发送流程，补用户示例、加载状态和已有输入保护；不创建新的引导后端。
4. **反馈与定位**：复用错误对象，增加统一入口与可复制摘要。站内反馈使用独立页面及服务模块，避免与现有 `feedback.py`（模型任务实时反馈）混为一处；补最小请求日志关联。接口具体契约见下节。
5. **手机操作**：在既有 `styles.css`／`ui.tsx` 和 `audio-capture.ts` 上修复实际发现的问题，必要时用可视视口信息补键盘遮挡；不整体重写页面或为浏览器型号另建 UI。

相关位置还包括 `packages/api-contracts/`、公司 `api.py`／`models.py`／`schemas.py`、必要迁移和对应 Web／服务端测试。文件名按现有职责细化，不提前搭建冗余平台。

## 数据流与接口

- 失败响应 → 安全错误对象（分类／状态／requestId／可重试提示）→ 页面提示／反馈表单；请求 ID 优先读取合法响应字段或 `X-Request-ID`，代理／断网未提供时为空。
- 反馈表单 → 用户审阅并提交 → `POST /api/v1/support-feedback`，使用同一逻辑提交的幂等键；成功才清空表单。
- `GET /api/v1/support-feedback` 与 `GET /api/v1/support-feedback/{id}`：员工仅本人，管理员本公司；分页与待处理／已处理筛选在服务端完成。角色、公司、owner 从会话派生。
- `PATCH /api/v1/support-feedback/{id}`：本公司管理员更新状态与处理说明，携带 revision，冲突重新加载，不允许凭客户端诊断字段定位或修改任意业务对象。
- 新表仅保存归属、用户描述、安全诊断白名单、状态、处理说明、时间和 revision；不挂到工作消息／报告／Agent 记忆。提交长度／频率有界，禁止自动收集业务内容。
- 首版不含截图上传；反馈通知与删除规则不由实施 Agent 自行扩展。

实施分工：公司反馈 API／迁移／契约与 Web 请求／会话／界面互不修改对方文件，按上述接口并行；后端先确定共享类型，Web 随后集成。`PATCH` 沿用现有字段名 `expectedRevision`。协调 Agent 负责文档及环境准备，实施结束后由新 Agent 独立验收。

## 验证计划

文档阶段为 **S0**，只检查 diff、引用、需求与待确认项，不为文档运行测试或构建。

实施涉及共享请求及登录边界，站内反馈还涉及授权和 schema，按 **S3** 识别风险，但检查仍限定到相关 Web／公司模块：

- Web 定向覆盖网络／非 JSON／超时／主动取消、401 单次处理、回包丢失及原键重试、晚到结果、示例填入与中文输入确认。优先扩展 `tests/web/api.test.ts`、`files.test.ts`、`list-feedback.test.ts`、`audio-capture.test.ts`，必要的身份／反馈用例单独补充。
- 站内方案的服务测试验证员工／管理员／跨公司访问、提交去重、处理状态冲突和受限诊断字段；在测试库验证新增迁移，不对日常资料注入故障或清理。
- 对改动源码使用项目格式化器；运行 Web 定向类型检查、相关 Lint。仅当新增路由／构建信息等确实影响产物时做一次普通 Web 构建，不执行 Electron 或安装包检查。
- 界面在日常 `npm run dev:company` 检查电脑及 360～430 CSS px 窄屏，沿用 Electron 的浅深主题。网络故障通过可控测试响应／测试服务复现，不能为了验证中断用户真实在途工作或额外调用付费模型。
- 手机按最终确认的设备／浏览器，用可用的有效 HTTPS 测试地址操作软键盘、权限、录音试听、文件选择、切后台和横竖屏，再完成工作确认与报告提交。桌面模拟与实体手机结果分别记录；缺少设备／地址时列出限制，不伪造完成。
- 实施完成后由新的独立验收 Agent 核对 Spec 与证据，复用已通过且未变化的检查；真机需要用户协助时将具体操作集中交接。

## 风险与迁移

- 401 恢复容易保留错误身份的数据：只暂存聊天输入，失效立即隐藏授权内容；新身份核验成功前不能恢复，模型密钥表单始终销毁。
- 超时／取消不代表写入撤销：沿用业务幂等及修订规则，不做全局写请求自动重试；上传成功回包丢失时不冒称附件一定未保存，恢复处理遵循现有附件生命周期。
- 网络状态不能仅依靠 `navigator.onLine`，浏览器会采用不同网络启发式。依据：[MDN onLine](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/onLine)、[Fetch 响应与错误](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch)。
- 手机麦克风依赖安全上下文、权限及设备，需以实际操作为准。依据：[MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)。
- 站内反馈采用新的 Alembic 增量迁移；不重建现有表、不迁移或清理业务数据。上线前按既有指南备份，回退应用版本时保留新增反馈表。本 Spec 不执行生产部署。
