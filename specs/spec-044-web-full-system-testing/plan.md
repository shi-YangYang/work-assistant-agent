# 实施计划

## 范围与顺序

实施按 S3，在独立环境完成全功能与流程验收。

1. **盘点与冻结**：从路由、请求层、OpenAPI、worker 和工具注册表生成清单，对照[功能矩阵](matrix.md)。复用现有有效用例，列出缺口、环境要求和真实模型样本，冻结预期及预算。
2. **隔离环境**：复用现有测试库约束，建立独立 schema、测试公司／账号、临时媒体与密钥、测试服务和沙盒。先检查目标标识、迁移版本和清理逻辑，不能默认使用开发账号执行业务写入。
3. **确定性基线**：执行 Web、公司后端和沙盒协议现有全量测试；分别记录产品、测试和环境失败，不先改代码再称其为基线。
4. **覆盖补齐**：补页面操作、接口失败、权限、并发、恢复用例及正式 Web Playwright 配置。每个测试均有结果断言，避免只检查 HTTP 200 或元素存在。
5. **真实浏览器与模型**：启动独立 API／worker／Web，逐页面操作并查看截图；执行已确认的真实 Agent 样本。按矩阵 F01～F08 扮演员工／老板，根据助手的实际答复继续对话，完成上传、澄清、确认、目标修改、跨页面核验和交付，保留逐轮操作及流程阻塞记录。
6. **故障与负载**：在独立环境注入有界故障；运行真实 gVisor 破坏性与恢复用例、录音固定输入、真实声纹提取以及冻结的性能场景。
7. **缺陷处理**：按用户确认范围处理。修复后只复测受影响场景；跨共享层改动扩大到对应子系统。保留首轮失败，不能重跑到绿或削弱断言。
8. **独立验收与清理**：新的验收 Agent 核查覆盖清单、关键业务断言、首轮与复测、截图及环境残留，给出结论和明确限制。

不得因为某一外部服务不可用就放弃其余测试；同样不能用可控替身替代未完成的真实验收。全部必测项有结果且必要回归通过后停止，不进行无目的随机循环测试。

## 组织与数据流

`冻结用例 → 独立身份／数据 → 浏览器或 HTTP → API → worker → 模型／工具／沙盒 → 数据库／成果 → UI 与数据双重断言 → 脱敏证据`

- 主 Agent 负责规格、覆盖范围和结果汇总。
- 实施 Agent 建立测试资产并执行；共享同一个数据库命名空间的测试串行运行，不能让不同临时加密密钥污染彼此。
- 仅无文件／环境冲突的子任务并行；新的独立验收 Agent 不参与实现、不修改业务代码。
- 真实模型配置通过已有配置读取逻辑提供，测试专用主密钥重加密，不输出密钥。新增总调用计数时覆盖评测器、核对、压缩和自动重试，不能只数用户消息。
- 用户模拟与验收判定分离：交互者只使用界面可见内容和预设角色事实；独立验收结合后台证据判断结果。自适应追问遵守冻结目标与分支，完整记录，后续可提取为稳定回归用例。

## 改造目录

下面为实际新增和原位修改范围。不迁移业务目录；生产改动限于本次测试确认的缺陷。

```text
specs/spec-044-web-full-system-testing/        [新增] 规格、矩阵、计划与独立验收
apps/
├── web/
│   ├── playwright.config.ts                 [新增] 手动 Web 浏览器套件
│   └── src/
│       ├── components/forms/AutoTextarea.tsx [修改] 避免 WebKit 布局观察循环
│       └── features/assistant/components/
│           ├── composer/ExecutionModePicker.tsx     [修改] 选择前保持焦点
│           ├── conversation/PersonaPicker.tsx       [修改] 同上
│           └── messages/{ChatHistory,MessageCard}.tsx [修改] 卡片按原消息归属显示
└── server/app/
    ├── agent/
    │   ├── actions/{intent,operations}.py   [修改] 字段完整性与失败执行槽恢复
    │   ├── actions/work_change_plan.py      [新增] 独立六字段变更计划
    │   ├── completion/{delivery,reply_review}.py [修改] 收尾及按需核对
    │   ├── completion/fact_review.py        [新增] 精简事实核验及正文缺失检查
    │   ├── context/history.py              [修改] 有界历史执行目录
    │   ├── completion/quantitative_review.py [新增] 数值关系一致性
    │   ├── context/request_clock.py         [新增] 本地日期与星期依据
    │   ├── harness.py                      [修改] 收尾协议验证
    │   ├── prompts/policies.py             [修改] 口径、条件与来源表达
    │   ├── tools/web.py                    [修改] 失败降级、来源等级及关键词定位
    │   ├── tools/{execution,registry}.py   [修改] 历史执行读取工具
    │   ├── reports.py                      [修改] 区分进行中职责与完成事实，旧审核恢复
    │   └── runtime/{model,middleware,tool_nodes}.py [修改] 有限修复、缓存及网页失败恢复
    ├── integrations/web_research.py        [修改] 有界读取、错误分类与关键词定位
    ├── modules/attachments/documents.py     [修改] 材料使用范围准确表达
    ├── modules/executions/service.py        [修改] 记录实际代码输入来源及回执标识
    ├── modules/executions/queries.py        [新增] 私有执行回执分页与权限检查
    ├── modules/model_services/parameters.py [修改] 保留显式模型推理配置
    ├── modules/conversations/context/context_store.py [修改] 精确失效依赖
    ├── modules/operations/{receipts,targets}.py [修改] 来源版本与旧失败记录
    ├── modules/team/sources.py             [修改] 团队工作截止日期投影
    ├── modules/team/agent_queries.py        [修改] 统一查询依据尾注
    ├── security/invalidation.py            [修改] 不误伤无关私人任务
    └── tasks/
        ├── {context,lease}.py              [修改] 上下文与报告审核参数
        ├── feedback/outcomes.py            [修改] 已取消操作的终态
        ├── nodes/node_execution.py         [修改] 可选失败结果与中断恢复
        └── processing/handlers.py          [修改] 输出准确来源及失效原因
tests/
├── server/
│   ├── test_acceptance_environment.py      [新增] 测试环境与清理保护
│   ├── test_full_system_acceptance.py      [新增] 匿名与并发一致性
│   ├── test_process_worker_recovery.py     [新增] 真实进程故障恢复
│   ├── full_system_worker_probe.py         [新增] 有界故障注入子进程
│   ├── test_infrastructure_failures.py     [新增] 数据库、密钥、媒体故障
│   ├── test_api_coverage_gaps.py            [新增] 实际 HTTP 成功路径
│   ├── test_model_service_http_coverage.py [新增] 模型管理 HTTP 断言
│   ├── test_{admin_scope_coverage,core_scope_coverage}.py [新增] 全路由角色/归属边界
│   ├── test_agent_virtual_files.py          [新增] 实际图内文件与宿主机隔离
│   ├── test_operation_{source_freshness,attempt_recovery}.py [新增] 来源与失败恢复
│   ├── test_task_receipt_projection.py      [新增] 历史卡片/取消终态/截止日期
│   ├── test_{answer_quality,work_change_plan}.py [新增] 状态、字段及缓存边界
│   ├── test_web_research_recovery.py        [新增] 网页失败、来源及重试恢复
│   ├── test_execution_evidence.py           [新增] 历史执行读取与隔离
│   ├── test_fact_review.py                  [新增] 核验范围、推理配置及重试
│   ├── test_quantitative_review.py       [新增] 按需核对及纠正边界
│   └── test_{assistant_execution,response_delivery,task_retry,documents,
│             context_store,report_reliability}.py [修改] 明确缺陷回归
├── web/dom/assistant-task.test.tsx           [修改] 卡片归属 DOM 回归
├── sandbox/{recovery_execution,serial_execution}.py [修改] 隔离目标校验
└── e2e/web/                               [新增] 真实浏览器
    ├── fixtures/test.ts                   身份、请求记录、截图与错误断言
    ├── auth/login.spec.ts                 登录、切换账号
    ├── assistant/{composer,recording,generated-files,network}.spec.ts
    ├── business/{work,reports}.spec.ts     工作与报告跨角色流程
    ├── settings/{management,configuration,voiceprint}.spec.ts
    └── navigation/pages.spec.ts           页面与窄屏截图
scripts/company/web-acceptance/            [新增] 显式启用的测试工具
├── environment.py                        独立 schema、账号、密钥及清理
├── inventory.py                          API、工具与页面清单
├── request_coverage.py                   ASGI 实际响应与用例映射
├── load.py                               固定数据量、有界并发
├── materials.py                          合成附件、音频
├── seed-report.py                        声明式初始报告夹具
├── {cases,retest-cases,retest-facts-cases}.json 冻结场景与独立复测目标
├── {readback,retest-readback,evidence}.py  只读业务、checkpoint 与模型用量证据
├── {agent-retest,report-retest,concurrent-retest}.py 有界复测与原失败保留
├── agent-http.py                         真实 HTTP 模型流程
└── agent-browser.mjs                     交互式浏览器用户流程
artifacts/spec044/                        [忽略提交] 运行证据
├── environment/                          资源归属与私有凭证
├── server/                               测试、请求覆盖与性能记录
├── web/                                  模块测试、类型、Lint 与构建
├── browser/                              操作证据、逐页截图
├── agent/                                首轮对话、复测、回执与真实文件
└── sandbox/                              隔离、资源边界、取消与恢复
```

性能报告中的 SQL 计数只测工作查询模块；连接池计数只测检查器引擎。HTTP 耗时、响应大小、API 进程内存和并发写入另行实测，不据此声称已观测 API 内部连接池或云服务器容量。

## 运行与检查

确定性检查复用当前命令，实施时注入隔离环境：

```sh
npm run test:web
npm run test:server
npm run typecheck:web
npm run build:web
```

- 修改的格式化覆盖文件由已安装 Prettier 整理；Web、共享 Web 契约和新增测试／脚本运行相应 ESLint 与格式检查，不为本次 Web 验收启动桌面构建。
- 新 Web 浏览器套件入口：`npx playwright test --config apps/web/playwright.config.ts`；服务 URL 必须来自本轮资源清单，不能默认指向用户已开的 5174。
- `test:server` 已包含独立解释器沙盒协议检查，不另重复运行。真实沙盒复用 `tests/sandbox/{real_execution,recovery_execution,serial_execution}.py` 与真实模型沙盒评测，执行前核实其目标和输出路径。
- 真实模型／权限评测均显式选择用例与输出路径，不能直接无参数运行整个历史语料。预算确认后在 manifest 中记录首轮规模、复测范围和实际调用统计。
- 真实语音使用有转写答案的合成或授权固定音频；声纹使用授权的固定样本。录音在浏览器注入固定媒体，物理录音与系统授权未实测时单列。
- 新库执行当前迁移；隔离旧版本库如需验证会话／历史兼容，仅使用合成旧数据。不得用开发库反复迁移来做破坏测试。

## 验收判定

- 覆盖清单的所有必测项都必须关联执行记录；当前正确的 4xx、确认或澄清可能是通过结果，不能一律要求“成功写入”。
- 产品声称完成时，要与真实业务／文件结果相符；只完成部分任务时须准确告知，不计为全任务成功。
- 完整用户流程同时检查结果和可用性：用户是否必须重复描述、被要求无意义确认、找不到结果或不能继续。功能接口通过不能替代流程通过。
- 真实模型首轮完成率、权限违规数、假成功数、重复副作用数、供应商失败数分别给出；不只报一个总通过率。
- 安全／数据完整性及确定性功能失败不得放行。真实样本未达到预期则保留失败，明确原因；不得边改样本边验收。
- 环境或第三方受阻列出影响功能及已完成替代验证；未被用户接受的必测缺口仍属于未完成。

## 风险与清理

- 测试目标误配：执行入口核验专用库、schema、测试 URL、目录和容器标签；不满足即拒绝运行。
- 副作用外溢：不停止宿主网络／共享数据库，不删除真实账号，不给真实员工发通知，不对外做压力测试。
- 长时间运行：用例、进程、模型请求与故障注入均有上限；清理只作用于记录在案的本轮资源。
- 凭证泄漏：日志、trace、截图和成果均脱敏；Cookie、认证头、主密钥不保留在验收证据中。
- 测试假设过期：以现有产品契约与本 Spec 为准；修正错误用例须记录理由，不能借此回避真实缺陷。
- 纯测试建设无生产迁移和数据搬迁；若发现确需修改数据结构或产品规则，先提交具体方案。
