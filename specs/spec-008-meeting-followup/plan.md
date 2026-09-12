# Plan — Spec 008

## 状态与范围

ACCEPTANCE · 2026-09-12 业务实施与定向返工已完成，独立工程验收 [PASS](acceptance.md)；用户已认可方案与[交互原型](prototype.html)，对应[员工工作助手与汇报看板](spec.md)。技术依据统一见[决策 0011](../../.ai/decisions/0011-company-agent-direction.md)，实现与相称验证由实施 Agent 完成，再交新的独立验收 Agent；不提交推送或触发远端 CI。

同仓库维护各端，各自运行、构建与部署。保留现有 Electron 和目录；原会议跟进计划已由本计划替换，本轮不迁移会议数据或同步桌面密钥。

## 模块与工程入口

| 内容 | 位置与选择 |
| --- | --- |
| Web | `src/web/`，React／TypeScript／Vite 沿用现有版本，React Router 7 浏览器路由；独立 HTML、Vite 配置与输出 `out/web/` |
| 共用界面 | 按需扩展 `src/ui/`，提取语义主题和纯组件；以现有 styles.css、Navigation.tsx、MeetingActions.tsx 为依据，不复制整套 CSS，不引入另一套 UI 库 |
| 客户端契约 | `src/shared/company-contracts.ts`，公司业务 DTO 与桌面 IPC 契约分开；服务端 Pydantic／OpenAPI 是 HTTP 契约依据 |
| API 与任务 | `src/python/paa_server/`，Python 3.12、FastAPI／Uvicorn；API 与 worker 使用同一套业务服务、权限和仓储 |
| 数据 | PostgreSQL 17、SQLAlchemy 2 async＋psycopg 3、Alembic；业务表与 LangGraph checkpoint 分区管理；附件为私有持久卷 |
| Harness | `paa_server/agent/`，Deep Agents＋LangGraph＋langgraph-checkpoint-postgres；模型适配使用 langchain-openai，ASR 使用 httpx |
| 依赖与部署 | 新增独立 `requirements-server.in`／`requirements-server.lock`、本地 `.venv-server`；`deploy/company/` 放 Dockerfile、Compose 与 Caddy 配置 |
| 定向验证 | `tests/server/`、`tests/web/`；复用既有工具，不把服务端依赖塞进桌面 requirements.lock 或安装包 |

服务端单独解析、锁定依赖，固定 FFmpeg 容器版本；首期不带 sounddevice、faster-whisper 或本地推理模型。服务端依赖已完成独立安装和兼容性检查，固定版本及证据见[实施摘要](implementation.md)。React Router 使用[声明式浏览器路由](https://reactrouter.com/start/modes)，不引入 SSR 或另一套全栈框架。

## 数据流与权限

文字／附件上传 → 事务保存消息并入队 → worker 识别媒体、查询授权上下文 → Agent 回复及进展草稿 → 员工确认 → 工作修订 → 周期报告草稿 → 员工提交 → 老板看板。任务不依赖浏览器持续打开。

- 对象包括公司、成员、会话、消息、附件、工作事项、进展草稿与修订、报告与修订、汇报规则、处理任务、登录会话。各对象有稳定 ID、归属、创建／更新时间及必要版本；工作修订保存来源 ID，报告保存输入修订快照。
- 服务端从登录身份确定公司与员工，客户端传入 owner／company 字段不能改变授权。员工只访问本人材料；管理员可查看本公司已发送上报及附件、已确认进展、已提交报告。独立编辑草稿与未提交报告仅本人可见；管理员查看原始回复时仍标明 AI 建议是否确认。
- 业务服务与工具内都鉴权。管理员不能代员工确认或发布；模型不能调用确认、发布、成员管理和修改规则的接口。原始材料、模型摘要与正式事实分开存储，checkpoint 不是业务事实来源。
- 会话采用随机 256 位不透明令牌、服务端存哈希，HttpOnly／Secure／SameSite=Lax cookie，默认 8 小时过期；同源部署，写操作校验 Origin 和 CSRF 令牌。浏览器不持久存访问令牌或业务材料，敏感响应禁止公共缓存。
- 密码用 pwdlib／Argon2id；首位管理员由交互式命令初始化，不把密码放在命令行。管理员创建临时密码，首次登录强制修改；停用、密码重置撤销会话，不能停用最后一名有效管理员。登录限流，失败不暴露账号存在性。[密码存储参考](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)。
- 附件采用服务端 UUID 路径，校验内容、大小和归属；只能绑定本人尚未绑定的上传。下载每次鉴权，禁止通过原始文件路径或公开 URL 读取。未绑定上传 24 小时后清理，已发送材料不因此清理；登出清除客户端状态和媒体对象 URL。

## HTTP 契约

前缀 `/api/v1`，JSON 使用稳定 ID、UTC 时间和 revision；分页默认 50、最多 100 条，使用游标。模型密钥与 Base URL 由部署方在服务端提供，不返回浏览器，不自动读取 Electron 设置。

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

参考集成采用百炼北京地域的 OpenAI 兼容端点，准确 Base URL 与 Key 由部署方提供，适配其工作空间地址；不将示例工作空间或旧域名硬编码为唯一入口。图文 Agent 使用 `qwen3.5-flash-2026-02-23`，关闭默认深度思考；ASR 用 `qwen3-asr-flash` 接收 Base64 WAV，得到文字后进入同一消息处理流程。[ASR 官方格式与限额](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference)。

配置分开保存 Agent／ASR 的模型、地址、凭证及受限参数。兼容接口不保证所有模型都有图像或工具调用能力：首次真实联调检查文本、图像、工具调用、语音和错误响应；换模型需验证所用能力。SDK 禁止隐式付费重试，日志只记任务 ID、阶段、耗时与用量，不记原始材料或密钥。缺少模型配置时消息仍可保存，处理状态提示暂不可用，不伪造回复。

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

- 公司时区默认 Asia/Shanghai，服务端接受有效 IANA 时区；日报周期为当地自然日，周报为周一至周日，报告保留创建时的时区和周期日期。
- 日报日期默认每天，周报默认每周五；生成时间、截止时间初始不启用，管理员保存有效配置后启动。生成日内截止时间不得早于生成时间；本轮不支持跨日截止。原型的 17:30／18:00 仅是可调整示例。
- worker 的独立轻量调度每分钟计算后续触发，员工＋报告类型＋周期唯一；队列处理期间调度仍运行。变更规则记录生效版本，不回补变更前周期；停机恢复只补当前周期已到期、未生成的一次任务，停用期间不补。
- 自动生成只准备草稿，未确认消息不进入正式完成事项；没有有效输入时保存空状态而不调用模型。手动生成与自动触发共用周期对象和唯一约束。
- 已提交内容保存不可变修订；更正先建立本人可见的新草稿，提交后形成新修订，管理者仍可读原提交版本。源工作后续变化不重写历史报告。

## 开发、部署与兼容

已实现独立入口：`npm run dev:web`（5174）、`npm run dev:server`（8000）、`npm run dev:worker`，以及同时启动三者的 `npm run dev:company`；用跨平台 Node 脚本选取项目 Python、传递模块路径并管理退出。现有 `npm run dev` 继续启动 Electron，Web 独立 `npm run build:web`。本地 PostgreSQL 由 Compose 开发服务提供，Web 开发代理 /api 到服务端。

部署在一台 Linux 主机上：Caddy 同源提供静态 Web、HTTPS 与 /api 反代，API 一个 Uvicorn 进程，worker 一个进程，PostgreSQL 一个实例。复用同一服务端镜像，通过不同入口运行 API／worker；生产不安装 Node 开发依赖。媒体、数据库和 Caddy 状态分别挂持久卷，数据库不暴露公网端口。PostgreSQL 起始 shared_buffers 64 MB、max_connections 20；应用小连接池，实际内存与队列延迟再测，不预设 2 核 2 GB 已足够。

手机录音使用有效 HTTPS 与域名；生产提供方须准备域名、DNS、服务器、百炼地址／凭证及额度，浏览器 localhost 例外不适用于手机访问服务器 IP。[Caddy HTTPS 前提](https://caddyserver.com/docs/automatic-https)。开发可用文字与录音文件测试，不能把模拟视口称为手机实机麦克风验证。

部署入口负责 Alembic／checkpoint 初始化，再启动服务；迁移前备份，失败停止升级，不能带着不兼容 schema 启动。首期备份提供维护窗口脚本：暂停写入和任务领取、等待正在写入的任务安全停下、导出数据库和附件清单／文件后恢复；保留 7 份，存入部署方指定备份位置。恢复验证使用备份对应镜像和数据，不默认执行破坏性降级；异机备份位置由运维配置，不擅自购买云资源。

## 交互原型与当前检查

打开[prototype.html](prototype.html)，可切换员工／管理员、手机预览和浅色／深色／系统主题。页面覆盖工作助手、进展确认、我的工作、日报／周报、团队详情与原始上报、成员、账户、外观和汇报规则，并包含发送失败演示。

2026-09-12 协调 Agent 轻量自查：走通确认进展 → 编辑并提交报告 → 管理员查看上报和提交结果；修改汇报规则后员工能看到安排；检查桌面、手机深色和 360 px 布局，无整页横向溢出，所走流程无浏览器脚本错误。

这是静态示例：身份切换代替登录，语音／附件与 AI 回复是演示，业务状态刷新后重置；部分历史、日期与账号操作仅展示示例。它供页面与交互审查，不是服务、权限、真实模型或实机录音验收，不生成 acceptance.md。

## 实施与验证顺序

1. 用户于 2026-09-12 已认可技术提案和原型并发出实施指令；实施 Agent 先建立独立 Web／服务入口、数据库迁移与身份权限，再打通文字 → 进展确认 → 报告 → 看板。
2. 接入图片、语音、持久 harness、报告调度与恢复，完善移动交互；这是同一 Spec 内的开发顺序，不减少最终范围。
3. 认证、API、持久化及构建入口按 S3 验证，Web 交互按 S2。固定样本覆盖员工隔离、管理员材料读取、草稿权限、工具白名单、租约恢复、幂等、人工更正、周期及版本冲突；PostgreSQL 特有事务行为在真实 PostgreSQL 中定向验证，不用 SQLite 冒充。
4. 外部服务自动测试用替身；真实文字／图片／语音联调使用公开或用户授权样本并取得费用授权。首批浏览器目标为当前 Chrome／Edge、Safari，手机含 iOS Safari／Android Chrome；不能以桌面视口模拟代替手机采集实测。
5. 只运行本次新增模块的相关测试、类型和普通构建；共用 UI 变动才在用户日常环境 `npm run dev` 回归相关 Electron 页面。新增 Web 检查融入现有轻量 CI，不默认加入付费模型、物理麦克风或全套桌面打包，也不为新增 Spec 重复已有验收。
6. 交新的独立验收 Agent，记录真实服务／设备未覆盖边界；验收通过后汇总给用户。部署、提交和推送按用户授权执行。

方案与原型阶段按 S0 轻量自查；后续业务实施及返工按上述 S3／S2 完成相称检查，当前证据见[实施摘要](implementation.md)，独立结论见[验收记录](acceptance.md)。
