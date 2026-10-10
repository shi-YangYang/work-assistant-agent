# Web 全量测试实施计划

依据 [Spec](spec.md)；具体场景见 [测试矩阵](test-matrix.md)。按已确认范围实施，首轮与复测证据分别保留。

## 涉及模块

- Web：路由和身份、布局与主题、聊天、工作、报告、团队、成员、全部设置与公共媒体／表单组件。
- Server：HTTP、认证授权、业务模块、Agent、上下文／记忆、任务队列、模型／联网／媒体集成、数据库与迁移。
- Sandbox：控制协议、隔离执行、内置工具、成果发布和清理。
- 验证：现有 Vitest／pytest／Playwright、`web-acceptance`、真实 Agent／记忆／沙盒评测脚本。

## 实施顺序

### 1. 冻结范围与先验

1. 记录起点 SHA 与工作区状态，读取现有产品契约和测试入口。
2. 从 `App.tsx`、`AppRoutes.tsx`、页面内操作、OpenAPI、工具注册表、Job 和 maintenance 获取清单。
3. 将每项映射到测试 ID、角色、状态、预期和证据；旧测试只是候选，不以文件名算覆盖。
4. 扩充 `cases.json`，冻结至少 60 个真实任务、独立预期和至少 20% 保留集。确定外部依赖、模型配置与用量记录方式；不设费用或累计调用次数上限。
5. 文档与后续用户要求冲突的例子：用途分配曾规定 640px，后续已要求铺满右侧；菜单已叫“聊天搭子／云搭子”。以最新明确要求为准，记录待同步文档，不恢复旧界面。

### 2. 校准与隔离

- 复用 `environment.py` 的测试库、schema 所有权、临时文件和 0600 凭据检查。需要新运行标识时扩展参数，不删除保护条件。
- 为本次指定产物根目录、端口与资源清单；兼容旧 `SPEC044_*` 入口，不能只把所有安全前缀替换为宽泛字符串。
- 校准旧页面标题、账号数据字段、全局执行权限、模型流式配置读取和最新迁移。测试脚本不兼容应先修复测试入口，记录差异。
- 本次评测入口取消旧脚本按累计消息／调用数量硬停止的限制，保留单请求超时、产品重试策略和隔离资源保护。
- 缺少记忆、思考强度、流式、当前工作记录等浏览器场景时，在原功能分组中补用例。
- 先验证测试隔离保护，再做任何删除、迁移、服务终止、配额或压力操作。

### 3. 建立首轮基线

- 运行现有 Web 与 Server 自动测试以及有关沙盒协议／内置工具检查，保留失败和跳过。
- 构建真实 Web，启动隔离 API／worker／数据库／可选沙盒；浏览器功能测试走真实业务后端。
- UI 稳定测试可使用受控模型应答，但需标记；不能从静态 Mock 页面推出业务功能通过。
- 同时记录请求、控制台异常、HTTP 断言、数据库读回和屏幕证据；字段和计数日志脱敏。

### 4. 补齐功能、接口与先验覆盖

- 每个公开 API 至少一个有断言的合法流程，保护接口补拒绝行为，写入补数据读回和适用原子性／幂等／版本用例。
- 动态 action、文件下载、SSE 消息语义、定时任务和清理单独登记；不能用 OpenAPI 响应列表代替真实分支执行。
- 变形与状态机用例使用固定种子、固定时间和独立事实表；需要时系统化生成组合，失败输出可重放种子。
- 复用已有有效断言，不为追求用例数量复制测试。以覆盖清单闭合为终止条件，不以行覆盖率或测试数量代替质量。

### 5. 浏览器与真实 Agent

- 全页面截图矩阵：1440×1000 和 390×844，浅／深色，管理员／员工各自可达页面。
- 关键布局补 360×780、768×1024、1280×720、1920×1080；检查 200% 缩放、软键盘／安全区及长内容。
- Chromium 做全量；Firefox／WebKit 做登录、导航、浮层、输入／附件、SSE、中断和下载的关键链路。仿真手机不等同真实设备。
- 既有 Playwright 默认 `reducedMotion: reduce`：静态对比可保留，但翻书、宠物、步骤文字光带、加载和打字机必须另在正常动效设置下录像／逐帧检查。
- 真实 Agent 首轮按冻结样本执行，不自动刷到通过；至少 12 条浏览器旅程验证 UI → API → worker → 模型／工具 → 正文／记录／文件闭环。
- 核对业务结果以 API／DB／文件为准；语义与风格按预期人工审阅，模型裁判只能提供辅助意见。
- 两个旧 Python 取消语义失误作为已知回归样本保留，依据执行结果或官方资料确定答案；不把某次模型答对当永久修复。

### 6. 故障与运行条件

- 故障注入顺序：单次可恢复错误 → 重试耗尽 → 网络恢复 → worker／API 重启 → 数据库与沙盒故障 → 并发和资源边界。
- 相互破坏的场景串行，结束恢复健康后再运行下一项；稳定功能检查和故障注入使用不同测试运行，避免混淆责任。
- 重启仅使用本次进程 PID 或已验证容器 ID，不按通用进程名杀进程，不停止用户日常服务。
- 用合成数据验证空库迁移、已有版本升级与备份恢复；不能为了验收自动迁移用户日常数据库。
- 在受控 Compose／反向代理链路检查 Cookie、CORS、SSE 不缓冲、静态资源缓存、刷新深链和服务重启。测试部署不等于真实服务器已验收。

### 7. 缺陷与验收

- 明确缺陷直接修复：先按根因合并同类失败，再做最小修改；不得为某一句话新增特判。测试资产缺陷同样保留首轮失败和修正理由；涉及产品规则或明显改版先讨论。
- 定向复测失败用例及受影响路径；共享请求、权限、任务状态等变更扩大到相关子系统。不能因文案改动重跑全部真实模型。
- 独立验收 Agent 检查覆盖清单、证据、未运行项、缺陷与保留集，不重复执行已经有效且未受影响的完整套件。
- 证据采集完成后按资源清单清理测试身份、schema、媒体、进程和容器；普通脱敏日志／截图留下，私有凭据销毁。清理失败也必须报告。

## 数据流与证据

```text
真实路由／接口／工具／产品要求
  → 覆盖清单 + 冻结用例／独立预期
  → 隔离环境 + 合成用户／资料
  → 自动检查／浏览器／真实 Agent／故障注入
  → UI 与请求证据 + 数据读回 + 文件核对
  → 分项结果与缺陷 → 定向修复／复测 → 独立验收
```

运行记录至少包含：run ID、SHA、配置摘要、用例 hash、case ID、身份类别、预期、结果、耗时、重试、用量、证据路径和缺陷 ID。状态语义为 PASS／FAIL／BLOCKED／NOT_RUN；不适用项目另列理由。

输出目录 `artifacts/spec054/<run-id>/` 包含清单、自动检查、浏览器、Agent、故障、负载和清理证据。首轮结果只追加不覆盖。请求日志使用白名单字段，屏蔽密码、Cookie、Authorization、模型 Key 和私人材料。

## 测试入口

按以下阶段入口执行，具体结果记录在实施报告：

| 入口 | 用途 |
| --- | --- |
| `npm run test:web` | Web 逻辑与 DOM 回归 |
| `npm run test:server` | 独立 PostgreSQL 下的业务、权限、Agent 与任务契约 |
| `npm run typecheck:web`、`npm run build:web` | Web 类型与普通构建 |
| 已安装 ESLint／Prettier 的 Web 及改动文件定向命令 | 相关静态检查，不顺带执行桌面全量 |
| `node_modules/.bin/playwright test --config apps/web/playwright.config.ts` | 隔离环境就绪后的 Web 浏览器流程 |
| `scripts/company/web-acceptance/{inventory,request_coverage,evidence,load}.py` | 清单、真实请求映射、证据与受控负载；先参数化本次路径 |
| `scripts/company/web-acceptance/agent-http.py`、`agent-browser.mjs` | 真实 API／worker 和浏览器 Agent 旅程 |
| `scripts/benchmarks/{agent-evaluation,agent-permissions-evaluation,memory-evaluation,sandbox-evaluation}.py` | 已有专项样本，统一用量记录与证据，避免与主样本重复执行 |
| `tests/sandbox/test_protocol.py`、`toolkit/`、`real_execution.py`、`recovery_execution.py` | 协议、内置工具、隔离执行与受控恢复 |

确切参数和最小新增入口由实施前校准确定，不能复制旧命令把本次结果写入旧证据。基础环境缺失记录阻塞；先做不依赖该环境的项目。

## 实际改造目录

现有业务目录不迁移。修改只针对已复现缺陷、缺失覆盖和过期验收入口。

```text
specs/
├── README.md                                           [修改] 规格索引
└── spec-054-web-comprehensive-testing/
    ├── spec.md                                         [新增] 范围与验收
    ├── plan.md                                         [新增] 实施与目录
    ├── test-matrix.md                                  [新增] 先验与覆盖矩阵
    ├── implementation.md                               [新增] 结果与限制
    └── acceptance.md                                   [新增] 独立验收结论
apps/server/app/
├── agent/
│   ├── completion/limits.py                            [新增] 无循环依赖的答复长度常量
│   ├── completion/{delivery,response_repair}.py        [修改] 修复内部核对指令泄漏与错误业务分类
│   ├── completion/completion.py                        [修改] 剩余事项与纯回执结束条件
│   ├── runtime/reply_stream.py                         [修改] 改用独立常量
│   └── harness.py                                      [修改] 核对指令作为内部上下文
└── modules/conversations/task/task_state.py             [修改] 中断不伪造缺失输入
apps/web/
├── playwright.config.ts                                [修改] 参数化环境与证据路径
└── src/
    ├── app/layout/pet/PetStage.tsx                      [修改] WebKit 关闭弹窗后焦点返回
    └── features/assistant/components/composer/reasoning/
        └── ReasoningEffortPicker.tsx                   [修改] 异步保存后的焦点
scripts/company/web-acceptance/
├── {environment,inventory,request_coverage,load}.py      [修改] 所有权、当前覆盖清单与受控负载
├── evidence.py                                         [修改] 实际用量与工具回执，排除隐藏推理
├── agent-http.py                                       [修改] 冻结多轮任务、确认续接与不可覆盖证据
├── runner_environment.py                               [新增] 共用隔离身份与旧入口兼容
├── agent-browser.mjs                                   [修改] 当前浏览器任务与分段正文证据
├── agent-browser-common.mjs                            [新增] 浏览器公共操作
├── agent-browser-interactive.mjs                       [新增] 兼容原交互入口
├── ui-layout.mjs                                       [修改] 角色、主题和视口矩阵
└── {cases,suite}.json                                   [修改／新增] 冻结样本与执行范围
tests/
├── e2e/web/
│   ├── fixtures/{test.ts,environment.mjs,seed-layout.py} [修改／新增] 隔离身份与合成页面状态
│   ├── navigation/{pages,motion-layout}.spec.ts         [修改／新增] 页面、焦点及正常动效
│   ├── assistant/{composer,generated-files,network,recording}.spec.ts
│   │                                                   [修改] 校准真实组件与故障时序
│   ├── assistant/{preferences,streaming}.spec.ts        [新增] 全局偏好、强度与流式
│   ├── business/reports.spec.ts                        [修改] 当前工作正文与报告流程
│   └── settings/{configuration,voiceprint,memory}.spec.ts
│                                                       [修改／新增] 设置、实际声纹与记忆
├── web/dom/assistant-context.test.tsx                    [修改] 当前服务商输出空间规则
└── server/
    ├── test_acceptance_agent_http.py                    [新增] 驱动确认续接、受理恢复与不可覆盖证据
    ├── test_completion_repair_boundary.py               [新增] 核对指令与公开答复边界
    ├── test_receipt_completion_state.py                 [新增] 中断续接及真实剩余事项
    ├── test_{assistant_memory,assistant_persona,business_actions}.py
    │                                                   [修改] 记忆、租约与真实工具包装层
    ├── test_{boundaries,work_records}.py                [修改] ASR 配置冻结与工作更新访问
    ├── test_{execution_settings,password_schema}_migration.py
    │                                                   [修改] 兼容不可逆迁移的测试前置条件
    └── {test_infrastructure_failures,full_system_worker_probe}.py
                                                        [修改] 真实故障注入与副作用核对
artifacts/spec054/<run-id>/                              [运行时新增，不入 Git] 首次结果、复测和清理证据
```

既有沙盒测试与专项测试按覆盖需要复用，无源码修改。测试目录内的修改与新增以最终 diff 为准；没有为本次验收另建产品测试框架。

## 风险与迁移策略

- 测试方案本身无业务数据库迁移；迁移验证针对现有迁移链，在副本执行。
- 外部模型输出、新闻与供应商可用性有波动；固定业务事实，实时信息记录采样时间，分别统计模型和网络失败。
- 不因测试过期而放宽产品契约；不因产品改名而保留明显失效的测试断言。
- 真实调用不设总费用或次数上限；费用无可靠计价依据时标为未知。覆盖清单和必要回归完成后停止，不因无上限而重复已通过项目。
- 截图容易遗漏抖动、遮挡和焦点问题，必须结合点击与连续状态证据。
- 同轮输出与环境隔离；清理前先保留脱敏复现证据，不能覆盖唯一失败样本。

## 失败项追加修复

按[返工范围](rework.md)处理首轮失败与阻塞；原始结果不改，新的实际改造目录和定向验证在该文档与实施报告维护。

后续来源交付、流式节点期限和用量状态的原位修改及新增文件，见[追加修复目录](rework.md#来源交付与活跃流追加修复)。分别保留两轮修复的真实成绩和独立验收。

针对剩余回答错误，按[证据一致性范围](rework.md#回答与实际证据的一致性)修复生成与工具观察之间的缺口；真实回归和原错误正文回放分别冻结，不调整已通过的流式期限、来源 UI 或用户模型强度。
