# Plan — Spec 008

## 状态与范围

ACCEPTANCE；[Spec](spec.md) 的实施与定向返工已有独立工程 [PASS](acceptance.md)。选型见 [决策 0011](../../.ai/decisions/0011-company-agent-direction.md)，当前版本／命令见 [技术栈](../../constitution/tech-stack.md)。本计划保留模块与关键契约；结果仅在实施／验收报告维护。保留 Electron，不迁移本地会议或密钥。

## 模块与工程入口

| 模块 | 位置与职责 |
| --- | --- |
| Web／纯 UI | `src/web/` 浏览器路由、独立构建；`src/ui/` 共用语义主题与纯控件，不复制桌面业务 |
| HTTP 契约 | `src/shared/company-contracts.ts`；服务端 Pydantic／OpenAPI 为接口依据，与桌面 IPC 分开 |
| API／worker | `src/python/paa_server/`，共用业务服务、权限和仓储；`agent/` 承接 harness |
| 数据 | PostgreSQL 业务表与 checkpoint，Alembic 迁移；私有附件卷 |
| 依赖／部署 | 独立 `requirements-server.in`／`.lock`、`.venv-server`；`deploy/company/` 放 Compose、Caddy、Dockerfile |
| 检查 | `tests/server/`、`tests/web/`，不将服务端依赖放进桌面安装包 |

Web 沿用 React／TypeScript／Vite，不引入 SSR。浏览器路由在 Spec 009 调整为 data router 以保护未保存密钥。服务端单独锁定依赖与 FFmpeg，不包含 sounddevice 或本地推理模型。

## 数据流与权限

上传／文字 → 同事务保存消息并入队 → worker 识别媒体与查询上下文 → 回复／进展草稿 → 员工确认 → 工作修订 → 报告草稿 → 员工提交 → 老板看板。处理不依赖浏览器持续打开。

- 公司、成员、会话、消息、附件、工作、进展草稿／修订、报告／修订、规则和任务均有稳定 ID、归属、时间及必要版本；进展保存来源，报告冻结输入修订。checkpoint 不是正式事实来源。
- API、业务服务和工具都按服务端身份鉴权，客户端 owner／company 字段不能改变归属。可见范围和人工确认／发布遵守 [R1／R3](spec.md#r1--公司人员与可见范围)，原始材料、模型建议和正式修订分开。
- 会话使用随机 256 位不透明令牌，服务端存哈希；HttpOnly／Secure／SameSite=Lax cookie，默认 8 小时过期。同源写操作校验 Origin／CSRF，敏感响应不公共缓存，浏览器不持久存访问令牌或业务材料。
- pwdlib／Argon2id 保存密码；首位管理员交互初始化，密码不进命令行。创建成员或管理员重置后可直接使用密码登录，用户可在账户设置自行改密；停用／重置撤销会话，不能停用最后一名有效管理员。登录限流且不暴露账号存在性。
- 附件使用 UUID 私有路径，下载逐次鉴权，只能绑定本人未绑定上传；24 小时后清理未绑定文件，不清理已发送材料。登出清除客户端状态和媒体 URL。

## HTTP 契约

前缀 `/api/v1`，JSON 使用稳定 ID、UTC 时间和 revision；分页默认 50、最多 100 条，使用游标。模型凭证由服务端管理，不返回浏览器或自动读取 Electron；公司配置扩展见 Spec 009。

| 操作 | 接口 |
| --- | --- |
| 登录与身份 | POST `/auth/login`、`/auth/logout`、`/auth/password`；GET `/auth/me` |
| 成员管理 | 管理员 GET／POST `/members`；PATCH `/members/{id}` 停用或启用；POST `/members/{id}/reset-password` |
| 上传与发送 | POST `/uploads`；GET `/uploads/{id}/content`；GET／POST `/messages`，发送返回 202、messageId 和 jobId |
| 处理状态 | GET `/jobs/{id}`；POST `/jobs/{id}/retry`，只允许本人对可重试任务操作 |
| 工作进展 | GET `/work-items`、`/work-items/{id}`；PATCH `/progress-drafts/{id}`；POST `/progress-drafts/confirm` 或 `/progress-drafts/ignore`；POST `/work-items/{id}/progress` 更正正式记录 |
| 报告 | GET `/reports`、`/reports/{id}`；POST `/reports/generate`；PATCH `/reports/{id}` 保存本人草稿；POST `/reports/{id}/submit` |
| 看板与来源 | 管理员 GET `/team`、`/team/members/{id}/messages`、`/team/members/{id}/work`、`/team/members/{id}/reports`；本人／授权管理员 GET `/messages/{id}` |
| 汇报安排 | GET `/settings/report-rules`，员工只读；管理员 PUT `/settings/report-rules` |

- 消息写入成功即可显示“已发送”，处理进度单独显示。上传失败不生成空消息，识别失败仍保留已发送原材料。
- 发送、进展确认、生成与提交使用 `Idempotency-Key`；同一身份／动作／键重复请求返回原结果，键与不同请求内容复用返回 409。关键去重记录随业务对象保留。
- 草稿编辑、进展确认、规则修改带 expectedRevision；过期返回 409，并允许读取最新版本后明确合并。批量确认上限 20 项，事务内全部成功或返回冲突项，不部分提交后假称整批成功。
- 错误统一为 `{error:{code,message,requestId,fields?}}`；区分 401、403／不可访问对象 404、409、413、415、422、429、503。响应不含密钥、内部路径或堆栈。ASR 转写修正以有版本的派生文本保存，原音频不改写。
- Web 在处理页每 2 秒读取任务，后台页降频；团队可见页每 30 秒刷新并保留手动刷新。请求失败显示最后更新时间，页面卸载取消客户端订阅，不引入 WebSocket 基础设施。

## 输入与模型接入

| 输入 | 首期限制与处理 |
| --- | --- |
| 文字 | 每条最多 8,000 字符；空文本允许附带图片或语音，不允许完全空消息 |
| 图片 | JPEG／PNG／WebP，每条最多 4 张、每张 5 MiB、总计 20 MiB；Pillow 解码校验、单图最多 2,000 万像素，生成去 EXIF、最长边 2,048 px 的模型输入，保留原图 |
| 短语音 | 每条一段、最长 180 秒、原文件最多 20 MiB；接收 WebM／Opus、MP4／AAC、WAV，按浏览器支持选择 MediaRecorder 格式；不承诺锁屏采集 |
| 服务端转换 | FFmpeg 固定参数、无 shell 拼接、单任务单线程、60 秒超时；转换成 16 kHz 单声道 PCM16 WAV，校验解码后的实际时长，派生临时文件处理后清理 |

接口总请求上限 25 MiB；首版一条消息可带文字＋图片或文字＋语音，不同时混传图片和语音。超限／不支持格式在发送前提示，服务端再次验证；HEIC 等不支持图片给出转换说明，不能只凭扩展名接受。180 秒规范 WAV 约 5.76 MB，Base64 后约 7.68 MB，低于参考 ASR 的 10 MB 编码输入上限。

模型参考接入及选型理由见 [决策 0011](../../.ai/decisions/0011-company-agent-direction.md)，后续多服务／用途／语音协议以 [Spec 009 Plan](../spec-009-company-model-services/plan.md) 为准。实际联调分别核对文字、图片、工具和 ASR，兼容接口不等于能力相同。SDK 禁止隐式付费重试，日志仅记录任务、阶段、耗时和用量；缺配置时保留消息并明确失败，不伪造回复。

## Harness 与任务恢复

- 用 Deep Agents 组织工具循环、摘要与恢复，LangGraph 的 AsyncPostgresSaver 持久 checkpoint；初始化表放在部署迁移阶段。[持久记忆接口](https://docs.langchain.com/oss/python/langgraph/add-memory)。
- 固定工具集合为 `find_work_items`、`get_work_item`、`get_message_context`、`propose_progress`、`draft_report`，外加线程内虚拟上下文的 `read_file`。业务写工具只生成草稿，按 job／toolCall ID 幂等；正式业务写入仍通过上面的员工 API。
- 使用 StateBackend，保留框架必需的中间件，通过 HarnessProfile.excluded_tools 排除其余内置工具，关闭 GeneralPurposeSubagentProfile 且不配置同步／异步子 Agent。启动时验证最终工具名称集合，禁止宿主文件系统、命令执行、任意网络工具与用户自定义技能加载；不能用删除框架必需中间件的方式绕过工具注入。
- 公司规则由服务端版本化模板提供，身份注入可信 runtime context；checkpoint thread ID 由服务端生成并绑定公司／员工／job；消息和同一报告的不同生成任务也不共用可执行状态。工具再次按身份过滤数据库，不能相信模型传入的员工 ID。产品提示词与开发仓库 AGENTS.md 分离。
- 首次运行从业务消息表重建有限历史文本／回复，按目标消息的时间截断，不包含后续消息；显式 reply_to 优先进入上下文。历史不携带其他 job 的工具调用，最多 10k 字符并按当前合法文字／图片输入缩减，为工具保留空间。消息 checkpoint 额外绑定实际消费的转写 revision 与输入内容摘要；同 job 同输入继续 pending steps，已完成 graph 直接复用答复。转写纠正后的重试从新输入开始，不执行旧 pending tools 或复用旧完成结果；旧共享及未绑定输入版本的消息 thread 不作为恢复入口。
- ASR 写回在消息锁内选定生效文字和 revision，迟到识别不能覆盖人工纠正。工具与最终答复在租约事务内按 Job → Message 顺序加锁并校验源 revision；处理中纠正后拒绝迟到写入，保存明确错误和手动重试入口。已落库的原始建议与人工确认修订保持，业务工具继续按同 job／内容去重；报告仍使用本 job 的已确认修订快照。
- 模型上下文包含当前输入、有限历史、已确认工作和必要来源。单次输入上下文目标上限 24k tokens，工具输出最多 6,000 字符；历史摘要为派生数据，不能抹掉人工修订，完整依据仍可授权查询。
- 每任务默认最多 8 次模型调用、16 次工具调用、180 秒，总输入／输出预算 64k／8k tokens；单次输出上限 4k。发起调用前核对剩余预算，SDK 自动重试设为 0；超过预算或需要澄清时保存状态并退出，不占住进程等待用户。额度可由部署配置调整，另设每日调用额度。
- PostgreSQL 任务表与消息同事务入队，初期一个 worker、并发 1；用短事务 `FOR UPDATE SKIP LOCKED` 领取，90 秒租约、15 秒心跳及 fencing token 防止旧进程迟到写入。同一员工会话串行，网络调用期间不持有数据库事务。[队列表锁语义](https://www.postgresql.org/docs/17/sql-select.html)。
- 状态包括 queued、running、awaiting_input、succeeded、failed、awaiting_retry。阶段结果先持久化再推进；租约过期可恢复无副作用步骤，确认外部请求是否已发出。请求已发出但结果未知时进入 awaiting_retry，明确告知可能重复计费，由员工重试；不能声称 checkpoint 保证外部请求恰好一次。
- 进展确认、工具副作用及报告保存使用事务、版本与幂等键。生成期间有新人工编辑时保留候选结果供选择，绝不覆盖新版本；任务崩溃不撤销已经确认的工作。待澄清的回答作为下一条消息关联原任务和事项，继续处理。

## 报告调度与历史

用户行为与可见规则见 [R4](spec.md#r4--日报与周报)，调度实现遵守：

- 公司时区默认 Asia/Shanghai、接受 IANA 时区；日报为当地自然日，周报周一至周日，报告固定创建时的时区／周期。日报默认每天，周报默认周五；生成与截止初始不启用，保存后才调度。同日截止不得早于生成，不支持跨日截止。
- worker 独立调度每分钟计算触发，网络任务执行时仍运行；员工＋报告类型＋周期唯一，手动和自动生成共用对象。规则变更只影响后续，不回补旧周期；停机仅补当前周期已到期且未生成的一次任务，停用期间不补。
- 无有效确认输入时保存空状态、不调用模型；自动处理仅生成草稿。已提交修订不可变，更正形成私有草稿再提交，管理员仍可读取原版本；来源变化不重写历史。

## 开发、部署与兼容

启动、环境、迁移与备份操作统一见 [README](../../README.md#公司工作助手-webspec-008)。Web 开发代理 `/api` 到 API；跨平台 Node 启动脚本选项目 Python 并管理退出，Electron 入口保持独立。

单机 Caddy 提供同源 Web／HTTPS／API，API 单进程、worker 单并发、PostgreSQL 独立实例；API／worker 共用服务镜像，生产不装 Node 开发依赖。数据库不暴露公网，数据库、附件和 Caddy 状态独立持久化。起始 shared_buffers 64 MB、max_connections 20、应用小连接池；容量以实测为准。

手机录音需要有效 HTTPS，不能沿用本机 localhost 例外；域名、DNS、模型账户与服务器由部署方准备。迁移先备份，Alembic／checkpoint 初始化失败即停止升级。维护窗口备份需停写／停止领取、等待任务安全停下，保存数据库与附件，恢复后继续；保留 7 份，异机位置由部署方配置。恢复使用对应镜像和备份，不默认破坏性降级或购买云资源。

## 交互原型与当前检查

用户于 2026-09-12 认可静态原型并授权实施。原型只用于页面和交互审查，模拟身份、媒体和 AI，不能作为权限／模型／手机验收；已归档到 [Git 快照](https://github.com/shi-YangYang/work-assistant-agent/blob/236a9c4e32785e4d35b0673e2165e237cbe16b2c/specs/spec-008-meeting-followup/prototype.html)。正式 UI 及响应式维护以 Spec 008～010 为准。

## 实施与验证顺序

先建立入口、迁移和身份，打通文字→确认→报告→看板，再接图片／语音、持久任务、调度与移动交互。实施者与独立验收者分开；当前执行结果见 [实施摘要](implementation.md)、[验收](acceptance.md)。

本轮认证、API、持久化按 S3，Web 按 S2 定向验证：权限／草稿边界、工具白名单、任务恢复、幂等、版本冲突、人工纠正和周期调度；PostgreSQL 行为使用真实 PostgreSQL，外部模型使用固定响应。仅运行相关服务端／Web 检查，共享 UI 变化才定向观察 Electron。

真实服务使用公开或授权样本，设备范围明确区分 Chrome／Edge、Safari 与实体 iOS／Android；视口模拟不代替手机录音。轻量 CI、费用授权、停止和提交流程遵循 AGENTS.md，不在每个 Plan 重抄；文档本身按 S0。
