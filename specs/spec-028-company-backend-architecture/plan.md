# 后端重构实施计划

范围与目标目录见 [规格](spec.md)。文档阶段按 S0；实施跨越路由、鉴权依赖、任务基础设施与 ORM 注册，按 S3 验证公司后端，不扩展为全仓库或桌面验收。

## 现有职责迁移

| 现有位置 | 目标归属与拆分重点 |
| --- | --- |
| `api.py` | 工厂留原入口；公共依赖／中间件／错误到 http；端点到业务 router；内部查询／DTO／事务用例到所属模块 |
| `authentication.py`、`dingtalk.py`、`desktop_auth.py` | modules/auth 的会话、企业登录和桌面授权子职责；钉钉网络到 integrations，路由与服务拆开 |
| `service.py` | problem／version／共享输入到 core；owned 到 security；幂等到独立持久化模块；报告、进展、会话及 DTO 各归业务，不保留万能门面 |
| `business_access.py` | 确定性权限、来源证据、失效到 security；团队列表／筛选到 modules/team；结果呈现归业务或 Agent 适配 |
| `business_actions.py`、`business_writes.py`、`deletion.py` | 工作／报告写入归各自业务；跨业务动作与确认到 operations；意图／事实核对及工具编排到 agent；文件清理由 tasks 编排 |
| `queries.py`、`report_queries.py`、`team_workspace.py` | work／reports／team 各自 queries、serializers 和 router，保留共用筛选口径 |
| `report_schedule.py`、`report_generation.py` | 周期及待办规则归 reports；调度到 tasks；AI 生成／事实核对到 agent，事务保存仍由 reports 提供 |
| `models.py`、`db.py` | 公共 Base／连接到 db/base、session；ORM 分到各业务 models，任务等基础设施模型随明确所有者；db/registry 完整登记 metadata，不改字段／约束／索引 |
| `schemas.py`、`model_schemas.py`、`validation.py`、`input_rules.py` | 业务输入归模块 schemas；基础校验归 core；HTTP 校验响应归 http/errors |
| `model_services.py`、`usage.py`、`model_provider.py`、`model_secrets.py` | 配置／路由／快照／检测／用量分工；传输／chat／ASR 协议归 integrations；加密归 security；受控模型封装归 agent/model |
| `documents.py`、`media.py`、解析脚本 | 附件权限／内容／引用归 attachments；媒体转换及解析子进程归 integrations；带租约的处理编排归 tasks |
| `worker.py`、`feedback.py` | 队列领取／恢复、任务上下文与租约、处理器、运行槽、调度维护、任务反馈分开；根 worker 只启动与关闭 |
| `agent/harness.py` 及既有 agent 文件 | policies、model、middleware、tools 按职责拆分，harness 保留图调用；共享任务控制移出 agent；历史／核对／checkpoint 保持各自明确职责 |
| `voiceprints.py`、`support_feedback.py` | 路由和业务分别归 voiceprints／support；声纹后台循环由 tasks 调度，继续使用已有共享引擎 |
| `config.py`、`cli.py`、migrations、assets | 配置到 core，核对路径基准；CLI、迁移目录、资源目录与命令不变 |

表中目标是职责边界，不要求每个函数单独成文件。小型单一职责模块可以直接迁移，无需再套一层 service 类或 repository。

## 实施顺序

1. **固定兼容基线**：记录实际注册路由的方法／路径／顺序与必要 OpenAPI 字段、现有 ORM metadata，以及代表性响应、SSE、错误与文件行为。记录源码统计，核对测试数据库保护。基线放临时 artifacts，稳定的兼容断言进入测试，不提交整份重复 API 文档。
2. **迁移与解开公共依赖**：先将 `services/company` 移到 `apps/server`，同步开发、测试、容器、CI 依赖安装路径；保留 npm 命令与 Python 入口名、部署卷和数据路径。再拆 core、db 与 security，明确任务上下文和租约检查的底层依赖；让业务模块不再为一个公共函数导入整个 harness。模型全部登记后核对 metadata。
3. **逐业务拆 API**：建立 http 公共依赖，按认证／成员、会话消息／附件、工作报告／团队、模型服务／声纹／反馈迁移。每组保留原接口与事务语义；删除已迁移的闭包端点和 register_routes 实现，不新旧重复挂载。
4. **拆任务与 Agent**：先分离工具、模型封装与提示词，再拆领取／运行／处理／调度。模型意图核对与确定性写入通过明确参数或窄回调衔接，HTTP 和工具共用业务用例，不能互相调用入口。
5. **清理与说明**：更新仓库内直接导入、monkeypatch、资源相对路径和实际受影响脚本；清理短期兼容文件。更新 `docs/architecture.md`、技术栈目录说明和 AGENTS 的简短引用，不修改 README 的产品介绍或另建重复 Decision。
6. **验证与独立验收**：功能回归和启动通过后，由新的独立 Agent 审查目录边界、兼容结果与主要联调证据。验收不重复已通过且未再修改的检查。

同一包的模型、权限、租约和导入高度耦合，由一个实施 Agent 串行推进 Python 源码与其测试；协调 Agent 同步包外工程路径与文档，二者不修改同一组文件。不因分阶段实施留下一半新路径、一半旧门面的最终结果。

## 依赖与数据流

```text
HTTP router → 业务 service／queries → security、db、明确的底层适配
任务处理器 → Agent 编排／tools → 同一套业务 service
任务运行与模型调用 → 共享上下文、租约／版本检查
Agent model → 模型配置解析与受控 integrations
```

实际依赖检查按具体模块，而非仅按顶层目录：tasks 的 context／lease 不得导入 tasks 的 runner／handlers；modules 内 router 可以依赖 http/dependencies，service 不可；http 的装配可以导入 router，通用 middleware 不能依赖业务装配。ORM 模型只依赖公共 Base 等底层定义，不导入 service；db/registry 显式导入业务模型是模型装配例外，不被业务服务反向引用。避免为了层级图把同一事务拆成多次提交。

## 验证计划

- **完整后端回归**：使用独立且已迁移的 `paa_company_test`，执行 `npm run test:server`。目前源码中有 209 个 test 函数，参数化后的执行数量以实际报告为准。原行为断言保留，只调整确实迁移的导入／patch 目标；不能通过保留不再被调用的旧对象让测试虚假通过。
- **必要补充**：路由契约及 ORM 登记对照；两个 `create_app(settings)` 的配置／身份依赖隔离；提交失败不能返回成功；SSE 关闭后的资源释放；可运行的解析子进程与资源路径。优先复用既有相关测试，只补拆分实际造成的覆盖缺口。
- **结构检查**：在现有 Python 测试入口加入轻量 AST 依赖约束，覆盖入口反向依赖、业务对 harness 装配的引用和实际模块循环。保留 SQLAlchemy 登记等必要显式导入，不新增庞大的架构框架。源码行数统计辅助审查，不能代替行为测试。
- **运行入口**：检查 API health、worker 启停及任务领取、CLI 导入／帮助、迁移 metadata 与既有无待迁移状态；不重写已有 migration。对变更的相对路径在不同 cwd 下检查，并在现有 Linux 公司容器环境验证关键导入／解析入口；无法执行时列为未验证，不冒充部署通过。
- **Web 联调**：在本地通过现有 Web 检查登录／退出和切账号、发消息与任务流、文件／语音处理、工作修改与确认、报告生成／提交、管理员团队查看、模型配置保存与测试、问题反馈。危险操作用测试资料；原配置与资料保留。自动检查用受控 Provider，不依赖用户真实 Key。
- **前端范围**：复用相关 API／SSE／错误契约测试；不因 Python 目录变更改动前端实现。若发现接口不兼容，修复后端而非让前端追随重构。未修改 UI，不逐页做视觉改版验收。
- **工程范围**：沿用现有 Python 风格与已安装工具，不借机全包格式化或新增 formatter。如果修改格式化器覆盖的 JS／TS／配置，整理并检查对应文件。无需桌面构建、真实模型下载、收费模型调用或远端 CI/CD；本地检查失败只对相关部分返工复跑。

受控模型结果证明业务与协议链路，不能描述成真实厂商联调；钉钉和桌面授权保留受控回归，不要求重新操作用户公司配置。全量后端测试只在准备好的独立测试库执行，不在开发／生产库运行清理 fixture。

## 主要风险与回退

- 路由从闭包变为模块后可能错误捕获设置或丢掉依赖；通过应用实例隔离、权限负例与契约对照发现。
- `service ↔ business_access`、`harness ↔ action_tools／business_actions`、报告调度与生成存在交叉引用；迁移时按公共规则、业务用例、编排的次序解开，不能只把 import 藏进函数。
- 不改变请求 session、并发 session factory 和公司／成员／任务锁顺序。SQLAlchemy 要求[并发任务各自使用 AsyncSession](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks)，不能为复用引入全局 session。
- `python -I` 的解析脚本不能依赖开发时 PYTHONPATH；配置层级、`assets/probe-zh.wav`、解析脚本相邻关系、CLI 的 migrations 路径需成组更新。
- 无数据迁移；回退为本次代码及引用回退，不回滚业务数据。只有稳定启动入口保留兼容，内部模块路径不是对外公共 API。

补充参考：[FastAPI 测试依赖替换](https://fastapi.tiangolo.com/advanced/testing-dependencies/)。
