# 公司共享后端结构与职责重构

## 背景与当前行为

公司后端位于 `services/company/src/paa_server/`，API、worker 和 harness 共用同一 Python 包。除迁移外有 43 个 Python 文件、8,631 行，其中 36 个文件直接放在包根目录。现有功能覆盖多个业务，但业务定位、公共能力归属和依赖关系不够清楚。

| 文件 | 总行数 | 主要问题 |
| --- | ---: | --- |
| `api.py` | 978 | 工厂内部同时定义中间件、错误处理、身份依赖、DTO、查询和 62 个路由；全包静态扫描共 99 个路由定义 |
| `agent/harness.py` | 814 | 提示词、运行上下文、任务租约、模型封装、工具、middleware、图装配和历史恢复集中维护 |
| `business_actions.py` | 493 | 模型意图核对、事实校验、业务执行、确认和回执混合 |
| `business_access.py` | 462 | 公司授权、版本化来源、团队查询、引用和删除失效逻辑混合 |
| `worker.py` | 449 | 领取任务、恢复、心跳、消息处理、维护、调度和进程生命周期混合 |
| `model_services.py` | 433 | 服务配置、用途绑定、连通性检测和 HTTP 路由混合 |
| `models.py` | 422 | 所有业务的 ORM 定义集中在一个文件 |

行数不是唯一依据：190 行的 `service.py` 也混合了幂等、权限、报告、进展确认和多个业务的 DTO。多个业务模块反向导入 `agent.harness` 获取租约检查；一些依赖通过函数内 import 连接，搬动文件不能自动解决职责问题。

## 目标

- 能按业务找到路由、校验、用例和查询，沿“发消息 → 后台处理 → Agent 工具 → 业务保存”读懂实现。
- 拆开多职责大文件，消除万能服务文件和对 harness 装配入口的反向依赖。
- HTTP 与 Agent 继续复用同一套权限和业务写入；保持全部现有功能和数据兼容。
- 用轻量架构检查及开发说明防止后续重新堆回大文件。

## 范围与非目标

范围为公司后端 Python 包，包括 HTTP API、worker、harness 的代码组织及相关测试引用。将 `services/company/` 迁入 `apps/server/`，与 `apps/web/`、`apps/desktop/` 平级；后端为 Web、Electron 及未来客户端共用。保留 `tests/server/` 和现有部署边界，不重构 Web 前端或 Electron 本地核心。

`packages/` 保持根目录平级，继续存放真实跨应用复用的模型参数校验、声纹引擎、品牌资源与输入契约；不在本次重构中重命名包或重做客户端。内部 Python 包暂保留 `paa_server`，避免把启动命令改名与职责迁移混在一起。

本次不增加功能，不调整提示词内容、模型策略、预算／超时、并发额度、权限与业务规则，不改 API 协议、数据库 schema、环境变量或 CI/CD 触发方式。不更换 FastAPI／SQLAlchemy／LangGraph，不拆微服务，不新增 Redis、Celery、通用 Repository／Unit of Work 框架。

## 目录方案与依据

采用“业务模块就近组织，HTTP／任务入口保持轻量”的模块化单体。FastAPI 官方提供 [APIRouter、多文件与依赖组合](https://fastapi.tiangolo.com/tutorial/bigger-applications/)，并未规定唯一的企业目录模板；以下是结合本项目规模的方案。

参考的实际结构与取舍：

- [FastAPI 官方全栈模板](https://github.com/fastapi/full-stack-fastapi-template/blob/master/backend/app/api/main.py)采用集中装配和按资源拆分的路由，适合借鉴入口与依赖组织；不照搬其较少业务下的集中模型／CRUD 结构。
- [Netflix Dispatch 的 incident 模块](https://github.com/Netflix/dispatch/blob/main/src/dispatch/incident/views.py)将 views、models、service、flows 按业务就近组织，可参考业务内分工。该项目已归档，仅作为真实项目的结构案例，不采用其旧依赖或所有实现方式。
- [FastAPI Best Practices 作者的项目经验](https://github.com/zhanymkanov/fastapi-best-practices#project-structure)建议多业务单体按领域组织，每个模块维护自身 router、schemas、models 和 service。这是实践建议，不是 FastAPI 官方规范。

据此采用业务目录优先：ORM 也放入各模块，db 只管理公共 Base、连接和模型登记。保留现有函数式服务及 SQLAlchemy 查询，仅有复杂或复用查询时拆 queries；不为普通 CRUD 强制引入接口类、Repository 和 DTO 多层转换。

```text
apps/server/src/paa_server/
├── api.py                 # 保留 create_app 和 app，负责应用装配
├── worker.py              # 保留 python -m 入口，负责启动／关闭
├── cli.py                 # 保留迁移、管理员初始化和密钥命令
├── http/
│   ├── routers.py         # 明确注册各业务 router
│   ├── dependencies.py    # DB、Settings、当前身份与管理员依赖
│   ├── middleware.py      # 来源、请求大小、安全头、请求编号和日志
│   └── errors.py          # 统一 HTTP 错误与字段校验响应
├── core/                  # 配置、路径、错误、共用输入和版本规则
├── db/
│   ├── session.py         # engine／session factory
│   ├── base.py            # 唯一 Base、公共 ORM 字段与时间函数
│   └── registry.py        # 显式登记全部模型，供迁移和 metadata 使用
├── modules/
│   ├── auth/              # 密码会话、钉钉与桌面授权
│   ├── members/           # 成员生命周期和账号管理
│   ├── conversations/     # 会话管理
│   ├── messages/          # 消息提交、读取、转写更正
│   ├── work/              # 工作、修订与进展确认
│   ├── reports/           # 报告、来源、周期、待办和通知
│   ├── team/              # 团队看板与明细查询
│   ├── attachments/       # 私有附件、预览、提取结果和文档引用
│   ├── model_services/    # 服务配置、模型用途绑定、检测和用量
│   ├── voiceprints/       # 公司声纹管理与同步
│   ├── support/           # 用户问题反馈
│   └── operations/        # 业务操作、确认及持久回执
├── security/              # 所有权、公司锁、来源授权／失效、加密凭证
├── tasks/                 # 上下文、租约、队列、运行槽、调度、反馈及任务处理
├── agent/                 # 图装配、提示词、模型适配、工具、核对与 checkpoint
├── integrations/          # 受控模型 HTTP、钉钉客户端、媒体处理／解析子进程
├── migrations/            # 保留已有版本与路径
└── assets/                # 保留现有检测音频等包内资源
```

模块按需要使用 `router.py`、`schemas.py`、`models.py`、`service.py`、`queries.py`、`serializers.py`；只创建有实际职责的文件，不为每个模块补齐整套文件。无独立数据实体的模块不建 models；任务、幂等等基础设施数据定义随明确的所有者维护。复杂报告、附件和模型服务可按明确子职责继续拆分，不建立全项目的 `utils.py` 或 `crud.py` 杂物箱。

## 职责与依赖要求

- `api.py` 只装配资源、lifespan、错误、中间件和路由，不继续嵌套定义业务端点。业务路由使用模块级 `APIRouter`，处理参数、身份依赖和响应适配；查询和写入由所属模块提供。
- 设置和 session factory 由当前应用实例提供，依赖函数可替换；不把某个 `create_app(settings)` 的身份、配置或连接捕获到全局 router 中。多测试应用不得串环境。
- 模块内部的业务服务不导入 HTTP 路由、应用入口、worker 或 harness 装配。跨业务调用指向具体服务／查询接口；遇到双向依赖时提取共同规则或由上层编排，不用函数内 import 掩盖循环。
- `security` 保存确定性的权限及来源规则；团队列表查询归 team，DTO 归对应业务。安全规则不得为 API 和工具复制两份。
- `tasks` 拆出纯上下文／异常与租约保护模块，业务、模型调用和 checkpoint 按需使用；任务队列、处理器与 Agent 装配分开。`RunContext` 的定义不因被导入而装配工具或模型。
- `agent` 拆出 policies、model、middleware、tools、意图／事实核对与调用编排。提示词和工具名称／参数／授权策略原样保留；模型辅助核对留在 Agent 编排中，确定性保存与确认归业务模块。禁止改成工具直接调用 HTTP 路由。
- `integrations` 处理具体协议、受控网络和解析进程，不导入业务 router。模型配置的数据校验归业务；底层调用使用明确的协议输入，不反向依赖服务配置的 HTTP 表单。
- `core`、ORM 定义和底层协议不能反向依赖业务编排。业务 ORM 就近放在模块的 models，使用同一个 Base／metadata；跨模块外键不通过导入对方 service／router 连接。db/registry 的集中导入只用于完整登记模型，是明确的装配例外；业务直接引用具体模型文件，不建立汇总全应用的导出入口。
- Python 文件超过约 400 个非空行时审查职责，API／worker 入口目标不超过约 150 个非空行。阈值属于本项目维护提示，不是行业标准；禁止压缩多条语句、搬成同样巨大的 helper 或拆碎单一流程来达标。

## 兼容与风险边界

- 所有现有 URL、方法、状态码、字段、默认值、错误码／字段错误、Cookie／CSRF、分页／日期语义、SSE 事件及二进制响应保持。静态路径与动态 ID 路由的匹配次序保持，不能只比对路由数量。
- 保留公司／角色／所有权、已删除记录、来源修订、管理员与员工区别，以及模型请求前和提交前的复核。钉钉与桌面授权不得因为拆路由丢失来源、PKCE、状态或令牌约束。
- 请求事务仍在返回成功前提交；原有 `Depends(..., scope='function')`、失败回滚及 SSE 独立读取语义不变。业务函数不自行多开事务或提前提交；共享 session factory，不在并行任务间共享同一个 AsyncSession。
- 公司锁、成员锁、任务锁顺序，消息幂等键／摘要、业务修订、任务 fence／lease、模型配置快照和 checkpoint 标识保持；恢复不能重复执行已完成操作或自动重复收费请求。
- 原始材料、数据库、Key、已有报告、会话、模型配置和声纹不迁移、不清空。只改 Python 模型文件归属，不新增或改写历史 Alembic migration。
- 保留 `paa_server.api:app`、`create_app(settings)`、`python -m paa_server.worker`、`python -m paa_server.cli` 及现有 npm 命令名；开发脚本、Docker、CI 依赖安装与缓存、测试和文档中的物理路径同步迁入 `apps/server/`。部署项目名、卷名、环境文件及持久化位置不变，API 仍不在进程内启动 worker。
- 配置搬动后仍正确定位 `.env.company`、默认数据及声纹环境；文档／图片解析仍能以 `python -I` 运行。包内音频、相邻解析脚本和 Linux 容器路径必须同步核对，不能只在仓库 cwd 下能运行。
- 内部导入和测试 patch 目标随迁移更新；不为维持旧测试导入在旧文件堆放永久转发层。仅保留确有外部用途的稳定入口。业务不因本次重构重新设计自有异常体系。

## 验收标准

- [x] API、harness、worker 及表中多职责文件实际拆分；全部现有后端模块有明确归属，模块无无意义空层。
- [x] 路由、共享业务服务、权限、任务运行控制和底层协议边界明确，无对装配入口的反向依赖或本次新增循环。
- [x] 全量后端行为测试通过；身份隔离、事务提交、幂等、版本、任务恢复、模型出站及文件边界均有现有或补充回归证据。
- [x] 路由／请求响应契约和 ORM metadata 对照无非预期变化；未新增迁移，原启动入口、解析子进程、资源路径有效。
- [x] Web 的登录、消息、工作／报告、团队和设置主要链路通过定向联调，区分受控模型与真实外部服务，不以假成功证明可用。
- [x] 旧路径和失效引用清理，架构说明补齐“如何增加接口／业务／工具／任务”的位置与一条真实数据流；轻量边界检查能阻止反向导入。

## 实施范围

一次覆盖公司共享后端的目录迁移、API、worker 和 harness 职责拆分；现有功能、模型行为、Web 界面和 Electron 核心均保持不变。
