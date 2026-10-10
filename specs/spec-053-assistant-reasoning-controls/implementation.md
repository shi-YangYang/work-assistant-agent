# Implementation

已删除 Web／公司 API 的独立推理预设实体、编辑器和用途绑定。模型直接配置 `reasoning.efforts` 与 `reasoning.initial`，账号偏好、消息引用和新任务绑定使用实际 `effort`。

## 实现

- 模型设置仅提供可选强度、初始强度；普通使用不用配置名称、ID、开放开关或重复填写参数。特殊接口参数留在折叠高级设置。
- 用途分配仅选择模型和请求方式。旧独立报告参数及显式空参数语义保留；报告跟随助手时也保留原有显式参数行为。
- 消息接受时冻结实际参数和模型版本；账号跨会话偏好、上传／保存竞态、自动与手动重试、问题续接、幂等规则保持。
- 新增迁移 `0028_direct_reasoning` 转换活动模型、用途和账号偏好，保留加密凭证、不可变 revision 和已接受任务。旧任务及旧幂等请求只在兼容边界读取旧 ID。
- 旧模型草稿转换实际选中参数；无法可靠转换的旧用途草稿要求用户明确放弃后读取当前配置，不静默保存不同参数。
- 原有输出 token 上限移除、主任务及推理核对继承强度的实现继续保留；服务商与任务安全边界不变。

## 涉及文件

- 后端：`modules/model_services/{schemas,service,bindings,parameters}.py`、`reasoning/`、`modules/messages/schemas.py`、`migrations/versions/0028_direct_reasoning.py`。
- Web：模型设置、用途分配、配置 controller／draft hooks、新 `ReasoningSettings` 与私有 CSS；删除 `ReasoningPresetEditor`。助手偏好 API／hook／picker、Composer 待发引用类型。
- 共享契约：`packages/api-contracts/src/index.ts`。
- 测试与调用方：思考强度、迁移、模型服务、报告与 Web 草稿／发送回归；评测脚本只同步引用结构，未运行付费评测。
- 上一阶段调用点和输出限制修改保留在工作区，未回退或提交。

## 验证

- 后端相关范围 **158 个不同测试通过**：首轮 42 个非 fixture／迁移检查通过；补齐独立测试环境后 115 个 fixture 检查通过；另新增 1 个嵌套参数报告回归通过。追加的环境参数断言只重跑对应单个测试，不重复计数。
- Web 7 个文件 **70 个测试通过**：54 个思考强度／发送／模型草稿，15 个模型检测／选择／报告重试，1 个旧用途草稿恢复。
- Web typecheck、全部改动 TS／TSX ESLint 通过；随后新增的旧用途草稿 guard 及其测试已单独格式化、lint 和测试通过。本次涉及源码已用项目 Prettier 整理，diff 检查通过。
- 协调 Agent 的实际浏览器检查通过：真实隔离 API，管理员创建／配置／保存 → 员工选择 → 刷新持久化 → 消息接受／取消；桌面浅色、手机深色、键盘和草稿保持。没有调用真实模型。

环境问题单独记录：共享测试库缺少 0027 字段，首次 fixture 建立失败；新的隔离 runner 起初遗漏 LangGraph checkpoints 初始化，导致清理失败和后续凭证校验连带失败。补齐标准初始化后在全新独立 schema 重跑受影响项通过，临时 schema 自动删除；未修改共享测试库或用户业务库。两次早期测试收集的缩进错误也已修正。

证据：`artifacts/spec053/direct/server-module-check.log`、`browser-check.json` 及浏览器截图。没有运行全项目、架构全量、桌面、远端 CI 或付费模型测试；未 commit／push／部署。

## 报告参数兼容返工

- 独立报告有参数覆盖时，绑定强度从该参数读取，不再借用助手模型初始强度；迁移前无选择的 `{}` 继续使用原报告轻量策略，显式空对象仍保留原意。
- 报告策略识别高级基础参数 `reasoning.effort`，即使未开放任何用户档位，也不关闭已显式配置的推理。
- 定向 **10 项通过**：迁移后的 null／显式空对象／顶层与嵌套独立强度经真实保存、绑定、解析及报告策略验证，同时覆盖助手初始强度、报告跟随、历史快照和原有报告默认策略。与前述计数有重叠，不合计。证据：`artifacts/spec053/direct/report-rework-check.log`。
- 使用自有独立测试 schema，先执行标准 Alembic 与 checkpoint 初始化，结束后删除 schema 和临时目录；未改用户或共享测试 schema。此次仅改绑定、报告参数策略及相关回归，Python 无项目配置的格式化器，遵循现有格式并通过 diff 检查；未重复前端检查或调用真实模型。

## 兼容边界

- 旧未绑定模型若实际选中的是私有参数或服务默认，迁移保留该参数并不自动开放某个档位；不擅自改成第一个公开强度。
- `parameterOverrides` 是特殊协议实际参数映射，不是命名实体或用户选项；普通档位直接发送 `reasoning_effort`。
- `explicitReasoning` 仅保留旧显式参数对报告轻量策略的影响，包括显式 `{}`。
- 0028 不自动降级成命名预设；回滚需恢复迁移前备份。迁移本身不改写历史 revision。
