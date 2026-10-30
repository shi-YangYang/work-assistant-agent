# Agent 回答与操作速度：实现与验证

## 主要改动

已实施，待独立验收。业务改动只有授权调用输入的两处 JSON 紧凑序列化：删除 JSON 分隔符周围的格式空格，保留所有字段、Schema、原文字符串、角色、政策与校验。未改变模型、推理档位、预算、重试、授权、来源、幂等或回执完成路径。

稳定观察到的是授权输入成本下降：四对首次授权实际输入减少 495～510 token，约 7.2%～7.4%。没有证据支持普通回答全面提速；操作端到端差值同时受外部请求波动及基线原有模型错误重试影响，不能全部归功于本改动。

## 涉及文件

- `apps/server/app/agent/actions/intent.py`：仅两处 `json.dumps(..., separators=(',', ':'))`。
- `scripts/benchmarks/assistant-latency.py`：明确允许已验证归属的 Spec081 环境，保留旧 suite 限制与首试保护。
- `scripts/benchmarks/assistant-latency-browser.mjs`：增加 Spec081 支持、实际 low/high 选择核对、新会话入口及 SSE 观察；把易误解的 `workCommitTimes` 更名为 `workRecordTimes`，明确 `updatedAt` 不是提交时间。
- `scripts/benchmarks/agent-response-latency-cases.json`：冻结同一空会话内“短答→明确创建工作”的两回合序列、输入与质量要求。
- `scripts/benchmarks/assistant-latency-runtime.py`：仅隔离测试进程安装完整合成模型传输输入、可见输出、建图与 Schema 准备观察；复用既有有界 Timing 和事务提交观察。生产不记录完整输入。
- `scripts/benchmarks/assistant-latency-serve.mjs`：仅启动拥有明确归属的隔离 Web，不改生产服务。

本报告之外的 Spec/Plan/索引由协调 Agent 维护。没有 commit、push、部署或远端 CI。

## 关键取舍

保留的候选：授权输入中的 JSON 格式空白。基线首个工作写入有两次主模型调用和一次必要授权；授权输入 6856 实际 token、外部请求 4.065 秒。其 Schema 可减少 586 字符、该请求 JSON 另减少 98 字符，解析后结构和值完全相同。

拒绝或暂不实施：

| 候选                | 当前证据与结论                                                                                                                         |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 图/Schema 缓存      | 首次建图 198ms，暖建图约14ms；Schema 转换不足6μs。不值得为小开销引入携带状态的图复用或失效机制。                                       |
| 领取唤醒            | 本次领取等待 47～812ms，未观察积压；基线工作路径 50～436ms。更换共享调度需要新通知与恢复机制，不是当前主要成本，不靠提高轮询频率提速。 |
| 准备与最终持久化    | 准备34～104ms，最终持久化22～35ms；未找到可安全删除的重复事实读取。                                                                    |
| 发布/前端           | 沿用来源校验与动画；来源校验后的流式发布较短，操作提交到完整回执约0.21～0.35秒，不改来源保护或会话恢复。                               |
| 额外收尾/工具预加载 | 既有纯操作回执已直接完成，无额外收尾模型；不重算旧成果，不无条件增加工具Schema。                                                       |
| 必要授权            | 保留；不把4秒授权删除，也不增加分类、审核或润色调用。                                                                                  |

外部请求计时覆盖 `_chat` 调用，包含HTTP等待、供应商响应以及本地流处理/回调；无法分离网络、供应商排队和推理，不称为供应商纯计算时间。并行或嵌套阶段不相加冒充端到端。

## 验证

业务修改触及授权输入，采用该子系统定向检查，未跑全仓测试、build、lint 或 typecheck。

- `test_authorization_evidence.py`：10 passed，1 failed，5.65秒。
- 同一个失败 `test_saved_plan_rechecks_refusal_and_creates_exactly_two_linked_works` 在隔离的原始 `6622a97` 源码上单独复现，3.15秒。受控 `SelectedJudge` 把追加的修复说明当 JSON 解析；属于已有测试假设，与紧凑序列化无关。没有修它，也没有重跑10项已通过检查。
- general/work/report 三个 verdict Schema 的前后解析结构完全相同；合成引文中的空格、换行、引号和反斜杠保持不变。Schema 字符分别 4854→4432、6707→6121、4595→4197。字符数不当成 token。
- 修改的 JS/JSON 已用项目 Prettier 格式化；源码 diff 检查通过。

证据：[定向检查](../../artifacts/agent-response-latency/authorization-tests.txt)、[原始基线同失败](../../artifacts/agent-response-latency/baseline-failed-test.txt)、[结构等价](../../artifacts/agent-response-latency/serialization-equivalence.json)。

### 真实 low/high 对照

当前真实配置为 `deepseek-v4.1-flash`。主模型分别使用所选 low/high；授权仍沿用原有 `enable_thinking=false`，没有为了实验降档。配置、输入和业务 diff 冻结于 [freeze.json](../../artifacts/agent-response-latency/freeze.json)。

共16条用户输入、35次真实模型请求（基线19、候选16），无追加用户确认或手动质量重采。每档两对 AB/BA，每个样本使用独立合成员工、空工作列表、空会话；短答后的创建沿同一会话继续。首对 low A1 的两个定位样本直接复用，分别在 `rewrite-low-A1`、`create-work-low-A1`；其他样本一次驱动完成两回合，不把它们误记为独立会话。

秒数如下。短答“首显”仅指首个非空且已授权的正文 DOM，平滑动画可能尚未显示完整句子；“完整”是本次单句回答可用时间的保守上界。操作值是实际保存后的完整可用回执。

| 场景     | 档位/配对 | 基线首显→完整 | 候选首显→完整 | 基线→候选主模型/授权次数 |
| -------- | --------- | ------------- | ------------- | ------------------------ |
| 短答     | low 1     | 3.649→4.130   | 3.380→3.881   | 1/0→1/0                  |
| 短答     | low 2     | 3.882→4.448   | 2.382→2.833   | 1/0→1/0                  |
| 短答     | high 1    | 3.229→3.730   | 3.630→4.114   | 1/0→1/0                  |
| 短答     | high 2    | 3.897→4.348   | 4.269→4.831   | 1/0→1/0                  |
| 创建工作 | low 1     | 11.959→11.959 | 8.265→8.265   | 2/1→2/1                  |
| 创建工作 | low 2     | 23.131→23.131 | 19.047→19.047 | 2/3→2/1                  |
| 创建工作 | high 1    | 16.930→16.930 | 12.282→12.282 | 2/2→2/1                  |
| 创建工作 | high 2    | 13.965→13.965 | 10.115→10.115 | 2/1→2/1                  |

| 创建工作配对 | 首次授权输入token，基线→候选 | 全部授权外部请求秒，基线→候选 | 实际工作提交秒，基线→候选 |
| ------------ | ---------------------------- | ----------------------------- | ------------------------- |
| low 1        | 6856→6349                    | 4.065→3.161                   | 11.727→8.044              |
| low 2        | 6857→6347                    | 4.038+5.118+4.888→13.022      | 22.922→18.799             |
| high 1       | 6847→6352                    | 4.638+3.332→4.524             | 16.680→11.995             |
| high 2       | 6845→6349                    | 5.092→3.646                   | 13.699→9.762              |

逐角色的所有调用、输入/输出token、实际参数、工具次序、调用身份、首次错误及原始时间见 [summary.json](../../artifacts/agent-response-latency/summary.json)；完整请求/Schema/返回分别在 [基线 trace](../../artifacts/agent-response-latency/baseline/trace.jsonl)、[候选 trace](../../artifacts/agent-response-latency/candidate/trace.jsonl)，持久读回在各自 `readback.json`。这不是降低调用预算或减少必要审核；基线额外授权来自原有重试。

质量核对：8次短答均保留12份、3份缺签字及补齐后才归档的条件；8次创建各保存恰好一条指定工作，正文、标题、进行中状态正确，没有报告或额外业务写入。合成数据读回与 `after_commit` 事件一致。原 [receipt-open.json](../../artifacts/agent-response-latency/receipt-open.json) 和对应 `work-open.png` 中，low 详情有效；high-B2 文本仍是聊天页、截图只有加载状态，原记录保留，不能证明 high 详情已加载。

针对这一取证缺口，使用同一 highB2 账号、会话 `89de9b63-e5a5-4126-9169-b4e9d955f537` 和既有工作 `5d5128f1-e6c3-4145-a97e-de8dd33986b1` 重新点击原回执。修正的 [只读驱动](../../artifacts/agent-response-latency/open-receipt-rework.mjs) 等待准确工作 URL、详情标题、“编辑内容”按钮可用、“进行中”状态及“工作内容”区域内完整正文，并确认详情 GET 返回200、加载占位消失；[补充记录](../../artifacts/agent-response-latency/receipt-open-rework.json)、[独立截图](../../artifacts/agent-response-latency/pairs/high-B2/receipt-open-rework.png) 和 [页面文本](../../artifacts/agent-response-latency/pairs/high-B2/receipt-open-rework.txt) 均已保存。截图已人工核对为工作详情。

[网络记录](../../artifacts/agent-response-latency/pairs/high-B2/receipt-open-rework-network.json) 中除允许的登录 POST 外，观察到的 `/api/v1/` 业务请求均为 GET；页面拦截器禁止其他写请求，实际没有触发拦截。没有发送消息、创建／修改工作或再次调用模型。补采前后两侧 `ModelUsage` 均为基线19、候选16，合计35不变。此次只补充现有对象的页面证据，未重复既有通过项；等待新的独立验收。

## 已知限制

- 高档短答对照完整显示变慢约0.38/0.48秒；该路径没有调用被修改的授权函数，输入/调用量无新增。原样保留波动，不用其他场景收益抵扣，不声称普通回答更快。
- low候选第2次授权用了13.022秒，明显慢于该对基线的首次授权4.038秒。稳定收益是输入token减少；小样本不支持将总等待缩短全部归因于序列化。
- 基线 low A2 的前两次授权带Schema外 `allowedFields`，high A1首次带 `resumetask`。完整正确输入包含 `additionalProperties=false`；保留3次纯模型合同错误及系统原有重试，不加提示补丁、不为它们重采。候选未观察同类错误不代表准确率提高。
- 首对low A1使用旧浏览器观察版本，无浏览器SSE字段，汇总保留null；其他操作样本由终态读回显示回执，没有非空流式正文，其SSE正文时间也为null。各session保存实际driver哈希。
- 原始浏览器样本字段 `workCommitTimes.commitSeconds` 来自工作 `updatedAt`，不是实际commit；汇总使用测试进程 SQLAlchemy `after_commit` 事件计算。工具已更正字段名。跨进程时间用同机墙钟关联，本地duration用单调时钟；不声称亚毫秒精度。
- 8次短答沿现有生命周期返回 `awaiting_input/complete`、`taskOutcome=completed`，没有用户问题框，不当成提问等待场景。
- 未改报告、文件、复杂材料或用户确认路径的业务规则／流程；共享授权序列化涉及 general/work/report 三分支，已做结构等价核对，其他入口没有真实端到端提速结论。既有 Spec080 未决项保持未决。上述旧定向测试失败仍存在。
- 首次环境准备因Docker/数据库未启动失败，空临时目录已移除；一次合成登录因用户名大小写失败，尚未发送消息，修正测试账号后另建输出目录，首试记录未覆盖。
- 独立验收观察到采样结束后两个 worker 的无 jobId 数据库连接异常，原因未定；不属于已测模型失败。补采前本地时间20:15的 [只读诊断](../../artifacts/agent-response-latency/receipt-rework-diagnostic.json) 显示两侧 `load_environment` 所有权校验及数据库读取成功，共享 PostgreSQL／Redis 当前 healthy；20:16 的详情 GET 与登录也成功。无需恢复或重启服务，这些当前成功不解释历史异常。

## 待确认事项、测试资源归属

无需产品决策，等待独立验收。保留全部证据及隔离环境供只读复核，当前没有模型任务运行。

- 基线：schema `spec081_baseline_c11ff3e99681`，API/worker/Web PID `18160/18161/18162`，端口 `8017/5197`。
- 候选：schema `spec081_web_54a44e6a075f`，API/worker/Web PID `18552/18553/18554`，端口 `8018/5198`。
- 精确归属、私有配置位置及命令见 [resources.json](../../artifacts/agent-response-latency/resources.json)。凭据仅保存在0600私有文件；生产/日常数据库未写入。
- 安全清理：`.venv-server/bin/python artifacts/agent-response-latency/cleanup-owned.py --apply`。脚本默认只预览；已验证schema标记、PID命令、独立进程组和精确Redis namespace。执行时停止这6个进程、删除各自Redis键及测试schema/私有临时配置，保留证据。
- Docker Desktop、`paa-company-postgres-1`、`paa-company-redis-1` 是已启动的共享服务，不归本任务清理，不会停止或删除。

## 合同精简实施：独立范围、授权复用与共享工具入口

本轮业务实现已完成，等待独立验收；上文两处 JSON 空白优化和旧证据保留。风险 S3（授权合同）。没有 commit、push、部署或远端 CI。

本轮保留 proposal-blind 范围提取和随后独立授权两次模型调用，不把看见提案的授权器兼任意图提取器。工作更新的实际首次授权输入减少 898～1014 token，范围输出减少 177～311 token，但范围 Schema 输入增加 304～325 token。两个关口合计输入净减少 584～699 token。端到端耗时有升有降，不能宣布稳定整体提速。

### 实际改动和兼容边界

- `work_change_plan.py`：模型线协议改为 `changed` 与 `preserved`，十字段须全部显式出现、唯一且互斥。文本／状态／日期／记录四类 changed 条目继承原字段限制；文本 value 仍只能 null 或明确清空的空串。展开后执行原 dense 模型和原 `validate_plan`，内部计划、缓存、checkpoint 和完成范围继续使用原 dense 形状；计划版本 12→13。
- `intent.py`：已验证计划的工作更新使用 `PlannedWorkVerdict`，不再要求模型输出重复的 `requestedChanges/requiredFields/appendFields`。授权模型仍决定 allowed、实际值／内容是否正确、材料选择、来源、确认、恢复与回执。程序从计划和本次原子组重建旧内部 `WorkIntentVerdict`；字段拒绝必须返回 `invalidFields`。版本 20→21，缓存及 checkpoint 仍保存 dense verdict。已有两处 JSON 紧凑序列化保留。
- `tools/business/actions.py`：统一精简完整说明，全部 action、参数、注册名和执行器不变。保留工作内容身份／字段语义、报告周日期与生成／提交区别、版本、来源、幂等、恢复和共享控制。没有按组删 action，也没有新增动态投影：否则工作回执后直接生成报告可能多一个加载回合。
- 测试修改位于 `test_work_change_plan.py`、`test_checklist_scope.py`、`test_authorization_contract_repair.py`、`test_tool_catalog.py` 和两个对应 `_support` 模型替身；基准 cases 在保留旧 journey 的基础上增加本轮三条固定旅程。其他已有 benchmark 修改保留。
- 没有改首轮工具预加载、worker 唤醒、用户可见动画、重试边界、调用预算、主模型档位或报告生成链路。普通创建／报告仍使用原来的独立授权合同。

### 旧保护与新实现逐项对应

| 既有有效检查                                   | 本轮承载位置／替代方式                                                                                                                                                                                                                                                                                                                                                             |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 范围不能从候选 changes 反推                    | 原 `source_input` 仍不发送提案字段／值；独立范围调用在授权前完成。`required_fields/operation_fields` 只选择已验证计划中的原子组，不发明用户意图。                                                                                                                                                                                                                                  |
| 十字段不可遗漏；禁止把缺项默认 preserve        | compact wire 的 changed+preserved 必须唯一、互斥、并集恰为 FIELDS；缺一个 preserve 也失败。新增未知字段／额外属性同样拒绝。                                                                                                                                                                                                                                                        |
| 引文来源、逐字匹配、非空、字段模式             | changed 保留全部 quotes；expand 后仍执行原 `validate_plan` 的用户来源、逐字引用和模式限制。完整用户文本仍包含否定／条件指令，preserved 显式列名。                                                                                                                                                                                                                                  |
| 文本清空、精确状态／日期、记录字段、清单选择   | typed wire 保留原 TextFieldPlan 限制及说明、FieldPlan 引文约束；原 dense 校验和 patch_error 继续检查 status、dueDate、clear、记录范围及 checklistSelection。                                                                                                                                                                                                                       |
| requestedChanges 的来源与 kind/field 分类      | 已验证独立计划已完成来源与字段归类；后续不再让见过提案的模型重提取。dense requestedChanges 是程序字段索引，每字段选首条已验证引文，最多10条，遵守旧32条上限；其 `explicit_field` 只作内部目的字段兼容标记，不表示用户说过字段名。所有引文留在发送给授权器的 compact plan 和持久 dense plan；持续指令／resume／authorization 使用各自原始来源，未改为依赖这个索引。代码有对应注释。 |
| 缺字段、越界字段、原子组不相互阻塞             | 原 patch_error、canonical_field、required_fields 的对称覆盖和互斥原子组检查保留。成功 verdict 只重建本原子组全部必需字段；不会要求正文步骤同时写属性或材料步骤。                                                                                                                                                                                                                   |
| 不能把错误值默认通过；不能捏造缺字段让用户重述 | allowed 仍由授权模型给出，程序不默认 true。`invalidFields` 必须唯一、canonical 后属于当前已请求原子组；allowed=true 不得附问题字段。`fields` 拒绝，以及 `other` 且 invalid_arguments/missing_info，都要求非空真实字段；唯一例外仍是已有、引文验证通过的材料保存位置缺口。原精确 missingInputs／recoveryOwner 和 missing_info 约束继续执行。                                        |
| 单字段错误只修该字段                           | 拒绝时 dense requiredFields/requestedChanges 只从有效 invalidFields 重建；目标／来源等拒绝保持原分支，不能把一处错误扩大为整组。模型是否显式提供 failureKind 的 `model_fields_set` 被保留，内部默认值不能伪装成模型输入。                                                                                                                                                          |
| append 不覆盖旧事实／不编造增量                | appendFields 从本原子组计划模式计算；授权模型仍提供 appendValues，原 append_contract 检查键精确匹配、非空且是实际提案的连续原文子串；原写入追加路径不变。                                                                                                                                                                                                                          |
| 授权引文、对象、真实执行意图与内容             | quote/quoteMessageId、quote_valid、当前/持续真实指令、目标权限仍检查；独立计划不是执行授权。授权模型逐项核对实际内容、条件与来源，不因字段在计划内就允许错误内容。                                                                                                                                                                                                                 |
| 材料与保存目标、注入、来源版本                 | normalize_contract/resolve、material selection、validate_sources、权限/版本栅栏保留；工作正文／附件／助手内容仍只是数据。源变化、目标变化、取消 lease 不复用旧允许结果。                                                                                                                                                                                                           |
| 确认、恢复、重放、完成回执                     | requireConfirmation、receiptOnly/taskContext、recoveringItem、task_item_reference、bind、旧 source/resume 绑定、待确认/成功回执防重放及整个任务完成判断均保留。dense 序列化消费者不换形状。                                                                                                                                                                                        |
| 非工作更新的合同与共享入口                     | create/report/general 使用原字段合同；execute_business_action 全 action/参数可达，[]、work、reports、两组四种组合均定向检查。                                                                                                                                                                                                                                                      |
| 合同修复与资源预算                             | 原联合 repair_constraints 和已有有界重试保留；新字段错误加入同一错误集合，未提前抛出导致丢失其它修复约束。未增加 classifier/reviewer/调用轮次。                                                                                                                                                                                                                                    |

### 相称检查与已知旧失败

使用 `.venv-server/bin/python`；没有全仓 build、lint、typecheck 或无关完整测试。项目格式器覆盖 JS/JSON，本轮修改的 cases JSON 已用项目 Prettier 整理；Python 不在当前格式器覆盖列表内。

| 检查                                                 | 结果／定位                                                                                                                                                                                                     |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 范围／清单／完成／授权修复首次检查                   | 84 passed、6 failed。修正 compact 替身和联合错误收集位置；后续针对失败检查12 passed、1旧失败。                                                                                                                 |
| 权限、授权证据、材料／来源、执行与工具等相关安全检查 | 201 passed、12 failed、4 deselected。12项均由已有共享测试 schema 缺 migration 导致（缺 cancel_reason、旧默认 auto）；在本轮新建并迁移的 owned schema 只重跑这12项，12 passed，4.16秒。没有修改共享测试数据库。 |
| 恢复旧 other 拒绝范围保护                            | 11 passed，9.12秒。                                                                                                                                                                                            |
| typed compact Schema 后范围／清单／完成检查          | 86 passed，17.44秒；包括十字段逐一遗漏、重复/交叉、额外字段、伪引文、状态/日期、文本约束、歧义、材料、确认、版本、重放与恢复。                                                                                 |
| 最后拒绝诊断与显式字段来源修正                       | 9 passed，9.15秒；包括多字段组只错一个时只返回一个诊断、有效拒绝不写入、有效通过、cross-group 拒绝、联合修复和未显式提供 failureKind。                                                                         |

检查有交叉，计数不可相加。原 `test_new_authorization_request_does_not_inherit_prior_repair_constraints[evidence]` 仍失败，在原始 HEAD 源码+原始测试也复现（1 failed，1.88秒），新迁移测试 schema 同样复现。与本轮映射无关，未顺手修改；完整原始复现在 [baseline-evidence-test-original.log](../../artifacts/agent-response-latency/contracts-20261025/baseline-evidence-test-original.log)。首次路径布局错误的日志不作有效复现。上轮已证实的 `test_saved_plan_rechecks_refusal_and_creates_exactly_two_linked_works` 旧夹具失败未纳入重跑。其余完整日志在本轮目录，失败未删，已通过检查未无理由重复。

### 固定真实模型样本与版本分界

本轮独立证据根为 [contracts-20261025](../../artifacts/agent-response-latency/contracts-20261025)。旧根及 `retest-20261025` 未覆盖。基线冻结的是 HEAD `6622a971bac05ef74f40bff7a7d626e0bfb3a8b1` 加任务开始时已有两行紧凑 JSON 改动，不是旧未优化 baseline；源码、原 diff、哈希、真实配置分别保存在 `baseline/` 和 `baseline-source/`，凭据仅0600文件。

采样前固定 [cases.json](../../artifacts/agent-response-latency/contracts-20261025/cases.json) 和 [freeze.json](../../artifacts/agent-response-latency/contracts-20261025/freeze.json)，32条初始输入（原上限40以内），每档每项至多两对 AB/BA：既有工作属性修改→同会话生成周报（2输入）、正文追加（1输入）、创建控制（1输入）。种子数据通过 API／DB 准备，无模型调用。实际模型 `deepseek-v4.1-flash`，主模型使用用户所选 low/high；范围／授权保留原 enable_thinking=false，报告子任务保留配置 reasoning_effort=low、max_tokens=4000，未调档位或预算。

- 初版在已发6条输入后暂停。low B2 的文本计划 value 错误引发失败，是 compact Schema 丢失原文本约束造成的**实现缺陷**，不是归咎模型。补回原限制并恢复 other 拒绝保护后冻结 [freeze-final.json](../../artifacts/agent-response-latency/contracts-20261025/freeze-final.json)，业务 diff 哈希 `105eec602509e989f4028ae7ca9736ced4d233b3d2be345213d44266f96f6c68`；重启候选 API/worker，从独立源码快照继续原剩余26条。旧 low B1/B2 共4候选输入全部保留，排除最终候选速度统计，未补采替换。
- 已发19条时暂停修正拒绝内部诊断与显式 failureKind 来源；9项定向检查后冻结 [freeze-diagnostics.json](../../artifacts/agent-response-latency/contracts-20261025/freeze-diagnostics.json)，业务 diff 哈希 `4d36c7ed47af8d4c5df798b9fab00f953caf72b96a2fafe852bb7833289853bd`，再次重启候选 API/worker，从第二个快照继续原剩余13条。模型输入/Schema、成功路径不变，先前最终合同的成功样本未执行该拒绝分支，因此保留；summary 的每行 `sourceFreeze`、每次调用的 `traceFile` 标明两份源码。没有无声热加载或重新发送旧样本。
- [run-complete.json](../../artifacts/agent-response-latency/contracts-20261025/run-complete.json) 确认32条固定输入结束，最终冻结后业务代码不变。实际116次模型请求：基线55、旧候选21、最终候选40。内部原有重试不是追加用户输入。最终12输入与对应基线12输入分别40/41请求，差的一次来自基线原有无效授权输出重试，不是删除必要关口。

最终候选完整可用耗时如下，单位秒；操作计实际写入后完整回执，报告计子任务完成并打开有内容的报告。失败没有成功耗时。low 属性／报告的候选是已排除旧版本，故不生成最终配对结论。

| 场景           | 档位／配对 | 基线→最终候选完整可用秒 | 总模型请求（含报告子任务） |
| -------------- | ---------- | ----------------------- | -------------------------- |
| 属性更新       | high 1     | 14.831→14.803           | 3→3                        |
| 属性更新       | high 2     | 17.464→13.752           | 3→3                        |
| 正文追加       | low 1      | 26.730→13.581           | 5→4                        |
| 正文追加       | low 2      | 19.048→14.148           | 4→4                        |
| 正文追加       | high 1     | 15.198→18.546           | 4→4                        |
| 正文追加       | high 2     | 16.947→17.314           | 4→4                        |
| 创建控制       | low 1      | 9.799→11.996            | 3→3                        |
| 创建控制       | low 2      | 20.331→12.365           | 3→3                        |
| 创建控制       | high 1     | 12.915→10.648           | 3→3                        |
| 创建控制       | high 2     | 10.196→10.664           | 3→3                        |
| 属性后生成报告 | high 1     | 55.150→42.163           | 3→3                        |
| 属性后生成报告 | high 2     | 30.323→失败             | 3→3（含1次失败子调用）     |

范围／授权成本分开列；以下 token 均来自真实 usage，授权列只列首次，不能把字符当 token。正文 low1 基线另有一次修复授权，输入7093／输出411。

| 更新场景   | 范围输入 token A→B | 范围输出 token A→B | 首次授权输入 token A→B | 首次授权输出 token A→B |
| ---------- | ------------------ | ------------------ | ---------------------- | ---------------------- |
| 属性 high1 | 2663→2971          | 549→372            | 7231→6259              | 505→309                |
| 属性 high2 | 2664→2979          | 616→388            | 7289→6275              | 479→306                |
| 正文 low1  | 2653→2978          | 347→126            | 7060→6141              | 382→199                |
| 正文 low2  | 2662→2976          | 343→130            | 7039→6141              | 384→319                |
| 正文 high1 | 2665→2973          | 458→147            | 7085→6134              | 302→204                |
| 正文 high2 | 2663→2967          | 388→155            | 7078→6105              | 234→309                |

主模型工具入口输入单列：同形状更新首调用约5750～5760→5579～5590 token；创建纯 load_tools 首调用仍2352～2362 token，其后含工作工具调用约5798～5806→5615～5631 token。报告在工作回执后首调用5807/5810→5645/5641 token，全部直接 execute_business_action，没有额外 reports 加载。正文 low B2/high B2 主模型自行同时选择 load_tools 和 get_work_item，工具 trace 保留，但两者都在同一模型回合，没有增加请求数；入口动作/参数本就完整，未因裁剪强制加载。创建首轮预加载开销仍存在，本轮没有处理它。

两个关口仍各一次。外部调用秒数含请求等待和流处理，不是纯推理时间。正文 high 两对、创建 low1/high2 变慢如实保留。正文 low1 基线多一次授权，是输出了 Schema 已禁止的额外 `targetContent`；完整输入支持这一合同错误定位，原修复后成功，未改提示或补采。

### 保存质量、失败和证据限制

最终候选10/10工作创建／更新成功：每次一条预期动作、一次目标 revision，属性值精确，正文追加保留原完整块对象（ID、顺序、条件、备注）、其他属性与材料未变；创建只保存一条指定内容、状态进行中的工作。对照基线工作12/12成功。最终候选报告1/2成功，基线4/4成功；整体候选11/12、基线16/16，样本范围不同，不把这两个比例解释为准确率估计。

报告检查不只搜索“12/3/签字”：逐栏读取实际保存内容。最终 high B1 的 completed 仅“已核对12份材料”，ongoing 明确工作尚未完成且受阻，blockers 保留3份缺签字及“补齐签字后才能归档”，next 是联系补齐的未来行动；未把归档或联系负责人说成已完成，publishedRevision=0。其实际报告页面已查看。其它成功报告同样保留事实、条件和未完成状态；旧 low B2 由于属性操作失败，报告按原工作源写“等待材料反馈”，该旧旅程依然失败。详见 [manual-quality-review.json](../../artifacts/agent-response-latency/contracts-20261025/manual-quality-review.json)。

最终 high B2 报告子任务 `1c798d6e-2b5c-435e-870f-edab7481f7d4` 返回 `ProviderError invalid_response`（模型响应未正常完成或达到输出限制），状态 awaiting_retry，草稿为空。72.257秒是观察到失败并打开空草稿的时间，**不是可用报告耗时**；summary 的 `successfulUsableSeconds=null`。未重试、未加预算、未把 enqueue 当成功。

[report-input-comparison.json](../../artifacts/agent-response-latency/contracts-20261025/report-input-comparison.json) 比较 high A2/B2 的完整子任务 outgoing messages/config：只归一化不同账号/对象 UUID 和同日种子创建／revision采样时间后完全相等，周期间、到期日、状态、正文、12/3数量、归档条件和预算未变。38个报告、任务及模型传输源码文件哈希一致。原始时刻与完整输入都保留；因此定位为未修改报告调用链的一次失败，不把它判作已证实的本轮合同回退，也无法仅靠现有证据断言是纯模型错误或服务端中断。失败抛出前未捕获供应商原始返回，缺该次 usage 和精确 finish reason，不能猜测 token。保留空报告、失败 job 和页面供验收，不能宣布报告链路全部成功。

旧候选 low B2 属性更新等待83.728秒后未写入，系统正确阻止了不合法计划，但产生不必要澄清。Schema 信息损失已修；旧 low B1 即使成功也随同旧版本排除，未用补采掩盖失败。最终 low 属性／报告证据不足就是不足。

证据索引：[summary.json](../../artifacts/agent-response-latency/contracts-20261025/summary.json) 含每调用角色/参数/tokens、工具顺序、commit 时间、源码冻结和原始 pair 路径；各侧 trace*.jsonl 保存完整 outgoing JSON/Schema 与可见响应，readback.json 为DB快照，pairs 下为浏览器截图/DOM/网络/SSE。未保存私有思考；失败调用缺 usage。不主张亚毫秒精度。

### 资源归属和交接

资源保留供独立验收；采样 runner 已结束，无新增模型请求。以下进程在清理脚本只读预览时均验证了命令、metadata 路径、独立进程组和 schema ownership marker：

- 基线 schema `spec081_baseline_d1b34b56e285`，API/worker/Web PID `32181/32182/32183`，端口8017/5197。
- 候选 schema `spec081_web_468bfff77ae9`，最终 API/worker/Web PID `33638/33639/32209`，端口8018/5198。原32207/32208、32973/32974已停止；metadata保留历史记录，不代表仍运行。
- 单元检查 schema `spec081_recovery_1d71c3cf0d0c`，无服务进程、无Redis namespace。业务写入仅在本地 `paa_company_test` 的owned测试 schema。
- [cleanup-owned.py](../../artifacts/agent-response-latency/contracts-20261025/cleanup-owned.py) 默认只读预览，已成功运行。验收取证后运行 `.venv-server/bin/python artifacts/agent-response-latency/contracts-20261025/cleanup-owned.py --apply`：仅停止这两套存活服务、删除各自精确Redis namespace、三份owned schema和私有临时配置；保留原始证据。遇到PID复用/所有权不符会停止，不误杀。共享Docker、PostgreSQL、Redis及日常服务不归本轮清理。

已停止验证和采样，等待独立验收；报告失败与两项旧测试失败不作已通过声明。最终业务 diff 检查通过。

独立验收通过后，协调 Agent 执行本轮 `cleanup-owned.py --apply`，全部归属检查通过：上述6个存活服务已停止，3份测试 schema、各自 Redis namespace 和私有临时配置已清理。原始证据保留，共享 Docker／PostgreSQL／Redis 与日常服务未停止或删除。未提交、推送或部署。

## 报告单次输出额度修复与固定复测

本次实现完成，但固定候选质量为 **15/16（7项新测正确＋8项复用正确，1项新测失败）**，不能宣布整体通过。报告候选4/4生成完整草稿；high B2工作属性实际写入正确，但最终任务和页面仍显示部分完成／失败，详见下文。没有追加采样或修复该新发现；等待新的独立验收及协调 Agent 对具体系统根因的处理。

### 本次文件与边界

- `apps/server/app/agent/reports.py`：唯一生成请求单次上限4000→8000；没有新增审核或生成回合。
- `apps/server/app/agent/context/context_usage.py`：report按请求值、模型较小能力上限及原8000任务剩余额度取最小值，输入空间预留使用同一实际额度；其他目的原4000单次预留不放大。
- `apps/server/app/agent/runtime/model.py`：非助手剩余输出耗尽时在HTTP前拒绝；报告返回后的累计额度固定8000，即使异常 `node_retry=True` 也不放宽至32000。助手原无输出限额行为保留。
- `tests/server/agent/completion/test_assistant_output_limits.py`、`tests/server/modules/reports/test_report_reliability.py`：补报告实际HTTP参数、剩余额度／耗尽／模型能力、上下文预留、异常重试上下文、供应商越额及显式推理参数断言。
- 未改变报告来源摘要、lease/fence、幂等、人工编辑候选保护、`length`拒绝、报告重写的助手路径、模型、显式推理强度、任务总额度或重试次数；没有清理旧 `verify_report`。本次源码是Python，项目Prettier配置不覆盖这些文件；业务diff检查通过。

### 定向检查与环境准备

S3限输出预算与报告子系统。迁移后的owned schema `spec081_recovery_4b03a132f25c` 中执行一次选定检查，**41 passed、14 deselected，6.39秒**；没有业务测试首次失败、修复或重跑。覆盖实际8000请求、累计剩余、小provider能力、耗尽不发送、异常node_retry不扩大报告总额、供应商越额拒绝、助手及内部调用隔离、显式high推理保留、截断不保存、来源撤销及人工编辑保护。没有全仓测试／构建／lint／typecheck，两项历史授权夹具失败未改、未重跑，仍为未解决项。

命令与原始结果见 [targeted-tests-first.log](../../artifacts/agent-response-latency/report-budget-20261026/targeted-tests-first.log)。使用 `.venv-server/bin/python scripts/company/web-acceptance/environment.py exec --metadata …/unit/environment.json -- .venv-server/bin/python -m pytest -q tests/server/agent/completion/test_assistant_output_limits.py tests/server/modules/reports/test_report_reliability.py -k 'output or report_http or report_retry_context or valid_report_without_tools or invalid_report_keeps_original or generation_has_no_semantic_review or report_late_response or structured_report_actual_request or manual_report_retry or report_default_mode'`。

环境首轮API/worker启动因快照缺 `packages/api-contracts/input-rules.json` 失败；两臂对称补齐当前 `api-contracts/model-config` 资源。恢复准备脚本又因缺 `manifest` 局部变量失败，补声明后只恢复未完成准备。两次均发生在0 Job／0 ModelUsage时，没有发送或重采真实输入；失败日志、失败PID及最初freeze均保留。最终采样前另存 [sampling-freeze.json](../../artifacts/agent-response-latency/report-budget-20261026/sampling-freeze.json)，两臂业务差异严格仅上述三个预算文件。

固定用户请求仍生成2026-10-25所在周。当前实测已为上海10月26日，为保留原合成来源语义，仅在owned测试runtime将新建／更新的 `WorkItem.created_at/updated_at`、`WorkRevision.created_at` 中超过 `2026-10-25T16:00:00Z` 的时间减86400秒，映射到上海10月25日并保留先后顺序。两臂相同，每次原时间和映射时间写入trace；任务、租约、系统／模型时间和计时不变。采样前两侧读回各4份固定正文／备注，均在目标周，且没有Job/ModelUsage；采样后每份报告确实选择原始与属性更新后的两份完整来源快照。没有操作日常／线上数据。

### 固定16输入及时间

基线是本次修复前的全部未提交候选＋报告4000，候选仅加本次预算修复；按low/high各AB、BA，共16输入、8会话。全部首试保留，没有用户重发、手动重试或补采。实际62次模型调用，基线29、候选33；8个报告子任务均各生成一次，基线实际 `max_tokens=4000`，候选8000，报告均保留 `reasoning_effort=low`。助手high不等于报告high。

| 输入       | 档位／配对 | 基线完整可用秒 | 候选完整可用秒               | 基线→候选调用数 |
| ---------- | ---------- | -------------- | ---------------------------- | --------------- |
| 属性更新   | low 1      | 10.214         | 12.998                       | 3→3             |
| 属性更新   | low 2      | 12.814         | 14.915                       | 4→4             |
| 属性更新   | high 1     | 11.282         | 14.565                       | 3→4             |
| 属性更新   | high 2     | 12.481         | 失败；29.614秒观察到矛盾状态 | 3→7             |
| 同会话周报 | low 1      | 28.849         | 56.014                       | 3→5             |
| 同会话周报 | low 2      | 45.967         | 29.059                       | 5→3             |
| 同会话周报 | high 1     | 47.559         | 28.722                       | 5→3             |
| 同会话周报 | high 2     | 32.635         | 31.414                       | 3→4             |

上表调用数已按 job／child job 对原始 `wire_input` 重新归属，纠正初稿将父助手额外调用误分配给周报的统计；原始记录未改。逐角色核对见 [调用数审计](../../artifacts/agent-response-latency/invalid-attempt-20261026/prior-call-count-audit.json)。

报告时间到子任务实际完成、从回执打开并显示完整草稿，非入队时间。失败属性步骤没有成功可用时间，29.614秒不计成功。逐次首显／完整可用／提交事件、工具顺序、每调用token和参数见 [summary.json](../../artifacts/agent-response-latency/report-budget-20261026/summary.json)、[timings.csv](../../artifacts/agent-response-latency/report-budget-20261026/timings.csv)。报告输出基线1474～2452、候选1416～1956 token，全部 `finish_reason=stop`；本次没有实际超过4000的报告，故证明了新上限传输和本组完成结果，不能声称观察到了超过4000而被救回的同一失败，也不能承诺8000永不截断。小样本、不同父消息路径和外部请求波动不能支持全面提速；low B1明显变慢原样保留。

### 质量逐项与新失败

[manual-quality-review.json](../../artifacts/agent-response-latency/report-budget-20261026/manual-quality-review.json)逐栏核对8份报告与DB：完成仅已核对12份；保留3份缺签字、补齐后才能归档；联系负责人仍是未来计划，没有写成完成。8份均来源两份revision，完整正文、备注及blocked属性未丢，报告revision=2且publishedRevision=0。候选四份报告截图已人工查看，页面正文与DB一致。基线两个A2的ongoing为空，但blockers仍明确未解决签字及归档条件，不把空栏目自动判作完成。

8次属性修改的实际业务数据均正确、每项仅新增一个WorkRevision，原正文块／标题／材料和备注保留；其中high B2的最终任务／反馈不一致，因此只7/8新输入满足完整质量门槛。正文追加和创建各low/high两份，共8项复用旧最终且未受报告额度影响的证据，未重跑、未重复计数旧属性结果。[fixed-quality-slots.json](../../artifacts/agent-response-latency/report-budget-20261026/fixed-quality-slots.json)列出16个候选槽位，15正确、1失败。

high B2属性 job `fa7fd0d9-1883-426d-bebe-7c767d96b851` 的完整输入／工具返回、持久 `taskItems/toolOutcomes/taskBarriers` 和页面见 [失败证据](../../artifacts/agent-response-latency/report-budget-20261026/high-B2-property-failure-evidence.json)及 [截图](../../artifacts/agent-response-latency/report-budget-20261026/pairs/property-then-report-high-B2/1-property-update/complete.png)：

1. 第一次主模型把应保留的title/body传为 `{"unchanged":true}` 对象，另外四属性正确。工具返回 `invalid_arguments`，分配旧事项 `86f423e0-2bda-4063-af55-8e33ee1f081f`，scope为body＋properties，failed outcome字段为blocker/body/dueDate/nextStep/status/title，未写入。
2. 第二次删除title/body，只剩正确四属性，但携带旧事项ID；独立范围／授权允许实际属性变更后，程序仍因事项范围不同返回 `operation_mismatch`，未写入。
3. 第三次不带事项ID，以新事项 `de6cae23-5e82-4938-98e7-1cd5d090efce` 完成同一工作四属性更新，只有一次revision。旧事项仍proposed；failed和succeeded两个toolOutcome具有相同identity但不同key/effect/fields/taskItemId，原失败scope比成功scope多title/body。旧失败反馈和barrier仍保留，任务变为awaiting_input、`incompleteTask=true`、`taskOutcome=partial`；页面同时显示“部分完成／这项操作暂未完成”和“已更新／已完成”。

已另存 [恢复快照](../../artifacts/agent-response-latency/report-budget-20261026/high-B2-recovery-snapshot.json)，含该job的taskItems、toolOutcomes、workChangeRequirements/Candidates/Plans、barrier、完整原始tool返回和最终状态。后续程序归因入口为 `tasks/feedback/outcomes.py:record` 的fields／same_item匹配，以及 `work_requirements.py:rejected_plan` 仅接受已有独立计划且带not_requested字段的恢复证明；首轮参数校验失败时尚未完成独立计划，快照中旧失败无planRejection。这是观察到的程序状态与身份／字段关系，不能用“模型参数最初出错”代替对最终错误反馈的系统归因，也不证明报告预算引入了它。当前 `execute_business_action` 的Work changes说明还写有“unchanged=true retains the old record.”，处在输入说明附近而unchanged实际是回执字段；这是后续独立验收需确认的输入／输出身份歧义。high B2确实将它放进title/body输入，但现有记录不能证明该句必然造成这一输出。本次没有更改该路径、合同或parser，也未追加复现。该用例失败，后续报告成功不能抵消；整体不宣布通过。

### 内部调用失败与取证限制

除上述最终质量失败，3次父消息模型调用分别失败后通过原有节点恢复：基线low A2 `2b825f01-d747-4fcc-9309-2d43984c7fcd`、基线high A1 `c4e15e87-455e-475d-865f-adbc60ecf99b`、候选low B1 `4ce01f27-6f5f-44b9-8f03-4b9b6671c678`。ModelUsage均记录 `invalid_response/模型未返回完整有效的收尾参数`，不是报告子调用。见 [internal-failures.json](../../artifacts/agent-response-latency/report-budget-20261026/internal-failures.json)。

HTTP200与first_body之后、`model.received/usage`之前失败，结合错误文本定位到流中 `on_delta → ReplyCandidate.feed` 的收尾参数解析拒绝；未到完整响应及框架后处理。被动wrapper只观察 `_chat` 完整返回和transport的 `invalid_response_diagnostic`，该回调直接抛错绕过二者，因此这3次没有完整失败输出、usage或finish reason，汇总保持null。具体哪种前缀或混合参数触发仍未知，不直接归咎供应商中断或纯模型错误，不追加日志改动／重采。59次完整输出及62次实际请求输入、工具顺序、worker timing和DB调用记录均保留。

### 资源与交接

按协调 Agent 指示保留本轮owned环境供独立验收及high B2程序归因，不执行清理。没有新请求运行；本轮采样已结束。

- 基线schema `spec081_baseline_72a4deaf195f`，当前API/worker/Web PID `44257/44259/44140`，端口8017/5197；最初44138/44139启动失败，metadata保留历史记录。
- 候选schema `spec081_web_dc281be1b08e`，API/worker/Web PID `44308/44309/44310`，端口8018/5198。
- 单元schema `spec081_recovery_4b03a132f25c`，无服务进程／Redis namespace；两臂Redis namespace分别由 `spec081:<runId>` 隔离。
- 精确归属／私有配置位置在新证据目录各侧 `environment.json`，仅用于本机 `paa_company_test`；共享Docker/PostgreSQL/Redis和日常服务未停止或修改。保留的 [cleanup-owned.py](../../artifacts/agent-response-latency/report-budget-20261026/cleanup-owned.py) 后续须先新鲜核对schema标记、PID命令/进程组、精确namespace再执行，不能把历史PID当当前归属证明。

下一验收优先读取本节、`sampling-freeze.json`、`summary.json`、`fixed-quality-slots.json`、`manual-quality-review.json`、`high-B2-property-failure-evidence.json`、两侧`readback.json/trace.jsonl/worker-prepared.log`及41项检查日志。旧报告截断、旧low合同失败和两项历史授权夹具失败均保留。没有commit、push、部署或远端CI；本实施Agent不作最终验收判定。

## 非法提案纠正后的状态恢复返工

本节是实施结果，最终结论交新的独立验收；不覆盖上一节 high B2 的 FAIL 和原始轨迹。证据根目录为 [invalid-attempt-20261026](../../artifacts/agent-response-latency/invalid-attempt-20261026/)。修改属于共享事项绑定／持久化 S3，检查限定原故障、授权身份、并发和最终反馈，没有重跑报告预算41项、全仓测试、构建或lint。

### 修复与边界

- `agent/actions/task_items.py`：只给实际 Schema 校验失败且尚未执行的尝试保存服务器 provenance。独立计划完整覆盖当前合法变更、证明删除字段为 preserve，且原消息、来源版本、node scope、引用、action/target、旧尝试和候选／已选需求快照一致，才形成 call-local 恢复证明。显式旧ID与无旧ID的新事项均支持。成功回执必须真实覆盖所需字段；只清理绑定快照中的旧失败／barrier，原始尝试、失败outcome和barrier保留审计。
- `agent/actions/intent.py`、`work_change_plan.py`、`operations.py`：在原独立计划／授权链上携带证明，在初始绑定、保存已选需求及成功持久化前检查。成功结算位于已有 lease 行锁事务内，各 await 未释放事务；没有额外模型回合，正常无 Schema 失败请求不新增恢复 DB 事务。Spec079 的两类并发窗口、租约／版本／幂等保护保留。permission、conflict、已有回执、其他来源／计划、失败／pending／无效回执不能借此清理。
- `tasks/feedback/outcomes.py`：仅用同一真实成功回执及对应旧outcome摘要移除过时失败，ledger、barrier、反馈和实际完成入口一致。不会按 target、step、字段子集或模型自报 resolved 清理。历史 checkpoint 缺少服务器 provenance 时保守不自动恢复。
- 发现并修复同来源／副本合法回执续接时的当前与历史快照错配：只有已读取并验证的实际回执对应当前事项，才把该当前事项明确展示给原授权模型并用它建立快照，不能任意 current 覆盖。具体旧失败为 `test_task_identity_recovery.py::test_continuation_binds_actual_source_and_copy_before_reusing_receipt[same_source_copy]` 第二次执行错误 conflict。旧候选重放也失败；完整原HEAD归因单次尝试被数据库连接耗尽挡在夹具阶段，因此不宣称完整HEAD复现或本次引入。
- `agent/tools/business/actions.py` 仅澄清保持字段应从 changes 省略，unchanged 是服务端回执字段。没有补同义prompt，也不能据此断言旧说明导致原模型错误。
- 冻结后另有两个窄修：精确记录已由本回执解决的非法 attempt digest，跨消息回执校验只跳过这些记录；`tasks/feedback/items.py:collect` 只将同action/target/成功receipt已证明的旧审计别名排除出下一轮投影，job原始审计仍保留。防止旧六字段被当作第二个已完成正文操作；真实执行事项和另一未完成事项仍展示，旧别名不能宽松复用。两文件完整diff/hash见 [final-source-delta.json](../../artifacts/agent-response-latency/invalid-attempt-20261026/final-source-delta.json)，最终文件副本在 `final-source/`。

源码变更涉及上述七个业务文件；测试新增 `tests/server/tasks/test_invalid_work_attempt_recovery.py`，原同来源／副本测试补“授权确实看到服务器认证当前事项”的断言。Python不在本仓已安装Prettier配置覆盖范围，没有配置Python格式化器；未格式化全仓。原有dirty未丢弃。

### 定向检查与首次失败

固定重放使用原high B2真实plan、授权响应和原始字段，只替换夹具message/object ID；这是固定响应测试，不是实际模型采样。原始输入与来源见 `replay-source.json`。

| 证据                                            | 结果及含义                                                                                                                                           |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `replay-before-first.log`                       | 两条原故障均首次失败：旧ID范围拒绝、新ID旧反馈残留                                                                                                   |
| `replay-after-first.log`                        | 两条初步修复通过；之后加强为实际完成入口                                                                                                             |
| `targeted-first.log`                            | 61通过、2失败：同源副本快照错配及DB503，全部保留                                                                                                     |
| `targeted-plan-binding.log`                     | 26通过，独立计划与并发证明检查                                                                                                                       |
| `targeted-final.log`                            | 22通过、1夹具连接失败；不以它宣称最终通过                                                                                                            |
| `targeted-binding-final.log`                    | 32通过、27 deselected，涵盖最终绑定修复、两条恢复、安全负向及原身份并发检查                                                                          |
| `replay-worker-final-first.log`                 | 两条通过实际 `process_job → delivery → persist_final`，最终DTO succeeded、incompleteTask=false、completed、空operationFeedback、一回执／一次revision |
| `partial-continuation-before.log` / `after.log` | 已恢复属性子项＋另一未完成创建的正确部分任务续接：冻结源码首次 operation_mismatch，精确退休旧attempt后首次通过                                       |
| `alias-projection-before.log`                   | 新事项恢复后旧六字段审计别名仍被投影，首次断言失败                                                                                                   |
| `continuation-projection-final.log`             | 最终两条续接路径2通过：只投影真实回执项及另一未完成项、复用原回执／无新revision、不同receipt和新非法attempt仍拒绝                                    |
| `finalize-projection-final.log`                 | collect实际受影响的完成双路径及另一真实正文需求保留3通过；未重复其它成功检查                                                                         |

`replay-followup-first/fixed/diagnostic.log` 是早期续接夹具错误：完全完成任务不会作为 previousTask 续接，因此“事项不存在”不能证明业务bug。保留这些失败，改用上表真实部分任务场景后才确认边界。没有把失败日志改成通过。

DB503根因记录在 `failed-fixture-diagnostic.log`：psycopg OperationalError，服务器 `FATAL: sorry, too many clients already`，该异常未提供SQLSTATE；不是无诊断重试。新候选首次worker也在0用户请求／0模型时因相同问题退出，保留首次日志。经协调Agent授权，新鲜核对metadata/schema/PID命令与进程组后仅暂停上一预算轮四个API／worker，证据 `paused-owned.json`；旧schema、Web、Redis和trace仍保留。新候选从同freeze恢复启动后才采样。`existing-head-first.log` 的完整HEAD归因仍未完成，不再尝试。

### 新12输入与复用4报告

[sampling-freeze.json](../../artifacts/agent-response-latency/invalid-attempt-20261026/sampling-freeze.json) 在第一条请求前固定477个源码资源、配置、原用例精确文本及顺序。包括旧准备曾遗漏的 `packages/api-contracts/input-rules.json`。新的独立owned schema和snapshot；真实Web→API→worker→实际模型→最终聊天回执卡片及DB读回，每场景low/high各两次，共12次首试，无补采、替换或用户重发。合成Work/Revision日期沿用前轮减24小时映射说明，保留trace；任务、lease和计时未改。

12条最终交付均正确：属性四字段精确且标题／正文块／材料保留，正文仅末尾追加、原块／备注／条件和属性保留，创建仅一条、精确标题正文及进行中状态。每条一份成功业务回执、一次revision变化，无独立进展；最终succeeded、incompleteTask=false、taskOutcome=completed、remaining和operationFeedback均空。材料夹具为空，精确保留断言不等于非空材料渲染验收。原采样三个场景high B2的聊天完成截图已查看；12条完整正文和属性通过DB／API原始读回逐条核对。原采样没有打开工作详情页，不能将聊天卡片截图称为详情页证据。

实际42次模型请求：助手21、独立plan8、授权13。创建high B1第一次授权误把当前messageId `62ca729d-281d-4b19-8e59-280f61b011a8` 当作不存在的taskItemId，完整JSON及输入均保留；服务端 `invalid_response` 拒绝后原有授权重试返回空taskItemId，最终正确一次创建。不是用户缺信息或新增系统错误，没有补提示、增加重试或重采；不能称所有模型首轮正确。该额外授权调用计入次数和16.515秒。

| 场景                   | low1      | low2      | high1     | high2     |
| ---------------------- | --------- | --------- | --------- | --------- |
| 属性完整可用秒／调用数 | 12.648／3 | 12.465／3 | 12.781／3 | 10.282／3 |
| 正文完整可用秒／调用数 | 13.264／5 | 14.379／4 | 13.848／4 | 12.967／4 |
| 创建完整可用秒／调用数 | 10.448／3 | 14.082／3 | 16.515／4 | 13.233／3 |

属性均execute；正文low1为load_tools→get_work_item→execute，其余get_work_item→execute；创建均load_tools→execute。这里的完整可用时间到最终聊天回执卡片显示，不包含工作详情打开。具体工具参数、每次wire、token、角色、首显／可用耗时及历史基线在 [summary.json](../../artifacts/agent-response-latency/invalid-attempt-20261026/summary.json)、[timings.csv](../../artifacts/agent-response-latency/invalid-attempt-20261026/timings.csv)。角色直接据请求payload和job归属核对，非按相邻时间猜测；上一表错归属也已局部纠正。

历史属性基线复用report-budget-20261026四项；正文／创建复用contracts-20261025各四项。采样时间与基线源码不同，不能当同轮配对或归因于本次修复的提速证明；新创建high两次比旧基线慢也保留。周报复用report-budget-20261026四个候选及既有人工栏目核对，没有新报告请求。合成16质量槽位为新12正确＋历史报告4正确，分别标记见 [fixed-quality-slots.json](../../artifacts/agent-response-latency/invalid-attempt-20261026/fixed-quality-slots.json)，不能说本轮新测16条。上轮high B2失败仍在原证据与验收记录中。

新12条均未触发 schemaFailure/recoveredSchemaFailure，因此没有实际模型碰到本次非法恢复链或冻结后两个续接窄分支。最终源码相对freeze仅 task_items.py精确退休attempt和feedback/items.py审计别名投影；这两个分支有上述定向重放，12条正常路径的实际证据保持适用，但没有重新采样最终文件，不能声称真实12已直接覆盖恢复。没有扩改历史parser，旧3次内部收尾解析根因缺证仍保留限制。

### 保留资源与交接

只运行清理预览，没有执行清理。新候选schema `spec081_web_b4b10850d6e2`，runId `b4b10850d6e24468883dcc15106d46d7`，Redis namespace `spec081:b4b10850d6e24468883dcc15106d46d7`，端口8019／5199；预览时API48699、worker48701、Web47389存活，初始47387/47388已退出。精确资源和私有配置路径在 `candidate/environment.json`；[cleanup-owned.py](../../artifacts/agent-response-latency/invalid-attempt-20261026/cleanup-owned.py) 默认只预览，后续明确授权才能 `--apply`，执行时重新核对归属；当前 [cleanup-preview.log](../../artifacts/agent-response-latency/invalid-attempt-20261026/cleanup-preview.log) 不能替代未来新鲜检查。旧预算轮环境与unit schema按前文保留，旧清理脚本单独管理，不动共享服务和日常／生产资源。

验收优先读取本节、final-source-delta、32项定向日志、最终5项受影响检查、summary/manual-quality-review/fixed-quality-slots和候选trace/readback；最终源码在原dev工作区，采样源码不可覆盖。没有commit、push、部署或远端CI。本实施Agent不作最终验收判定。

独立验收PASS后，协调Agent执行两轮已有清理脚本；每份manifest均重新核对归属后成功清理。新候选与旧预算轮共4份owned schema、剩余5个Web/API/worker进程、各自Redis namespace和私有临时配置已删除，原始证据保留。清理结果分别在 `invalid-attempt-20261026/cleanup-final.log` 与 `report-budget-20261026/cleanup-final.log`；共享Docker/PostgreSQL/Redis及日常环境未变。停止验证，未提交或推送。

### 验收补充：从原回执只读打开三份工作详情

独立验收指出原12条缺工作详情导航证据，以上原范围已更正。随后新鲜验证owned schema/API/worker/Web归属，以原property/body/create各high B2账号进入原会话，点击唯一“查看当前工作”原回执链接进入详情，等待精确标题及每段完整正文显示；不是直接拼详情URL导航。三份详情的GET均200，链接对象、响应对象和DB对象一致，截图已通过view_image实际查看：

| 场景             | 原工作对象ID                           | 详情状态／revision                                                             |
| ---------------- | -------------------------------------- | ------------------------------------------------------------------------------ |
| property high B2 | `61d1a0f7-6a64-4df2-98ae-410a5fc18adb` | 有阻碍／2；原正文和备注保留，期限10月30日、阻碍和下一步正确                    |
| body high B2     | `825c0df8-fa97-43aa-ad8b-240c78bd1958` | 进行中／2；原正文和备注后精确追加“已收到2份补充说明，仍须补齐签字后才能归档。” |
| create high B2   | `1f0bcf73-9748-4182-9c02-5ee49ab494ad` | 进行中／1；完整指定正文                                                        |

证据在独立新增的 [detail-readonly](../../artifacts/agent-response-latency/invalid-attempt-20261026/detail-readonly/)：每场景 `before.json` 保留原会话／回执href，`detail.json` 保留最终URL、完整DOM和GET响应，`detail.png` 是实际详情截图，`network.json` 记录方法／URL／响应码。观察器阻断全部非GET浏览器请求，仅显式允许三次登录POST；实际没有业务修改请求或被阻断的修改尝试。前后只读DB快照比较见 [verification.json](../../artifacts/agent-response-latency/invalid-attempt-20261026/detail-readonly/verification.json)：ModelUsage 42→42，Job、BusinessAction、WorkItem、WorkRevision及模型记录均未变化，没有新模型／新采样。首次离线比对脚本误读WorkItem.status而非content.status的KeyError仅修正读字段，没有重新导航或读库。

这三份是原计时结束后的补充只读证据，不是原12条均已打开详情。原timings、summary和采样截图均未覆盖，原可用时间仍只到最终聊天卡片，不包含这次详情导航耗时。未修改业务源码、验收结论、清理或提交。

## 扩展执行结果：54 项冻结集合

用户要求扩大实际测试后，本轮复用了现有服务端、Web 和浏览器基准框架，完成了冻结范围内的合理可执行分支；没有把旧 16/16 当作 54 项通过。统一证据在 [expanded-20261026](../../artifacts/agent-response-latency/expanded-20261026/)，逐项输入、断言、分支状态、实际测试 nodeID 和源码断言在 [coverage.json](../../artifacts/agent-response-latency/expanded-20261026/coverage.json)。本轮结论是 **41 项通过、6 项失败、7 项部分覆盖，不能宣布扩展集合质量通过**。通过项包含明确标注的夹具修订、环境恢复和系统修复后验证，不表示首次调用全部成功；各原始结果均保留。

### 实际执行数量与边界

- 服务端去重 **1955 个测试节点：1946 通过、9 跳过**。1437 个相关核心节点加 501 个材料／工具／沙盒节点，再加 17 个本轮保护节点；重跑不重复计数，3 个迁移名称按原节点别名合并。最初 55 个失败全部保留：41 个源于隔离测试 Redis 未配置；其余 14 个经具体合同／夹具归因后定向校正。没有把它们概括为数据库连接耗尽，原 JUnit 没有该异常。
- Web **426/426 通过**，属于受控 DOM／单元证据。9 个服务端跳过包括 4 个 opt-in Redis 传输节点、2 个所有权／进程恢复节点、3 个 opt-in 真实沙盒故障节点；没有把跳过视为通过。没有在真实模型批次中并行启动重检查争用数据库连接。
- 实际 **65 个初始输入、90 个总用户输入**，在 80/160 上限内：86 条真实消息任务（63 初始、10 普通后续、5 沙盒环境恢复、8 问题／确认续接），另有 2 次报告页生成和 2 次取消。C08 的 1 条受控问题重放任务明确排除；D04 在 HTTP202 后观察器异常的任务计入，没有漏算或重发。
- 受观测 Chat provider HTTP 请求 **279 次**，包含内部授权、报告、已有重试等；记录 8 次 attempt error。它们不是 279 个场景，也不是 279 个用户输入。模型为实际配置的 `deepseek-v4.1-flash` low/high；报告采用实际低档配置，音频使用既有 ASR 配置。原始请求／响应／工具／时间数据在 `real/trace.jsonl`，索引在 `real/full-evidence-index.json`，预算去重在 `real/budget-counts.json`。
- 没有建立新的 before/after 矩阵，也没有据此宣称整体提速。沙盒恢复、A06 环境中断、D04 人格偏离等时间排除正常速度比较。逐条原始可用时间与内部请求时间仍保留。

本地日志：`local/server.xml`（1379 通过／52 失败／6 跳过）、`local/supplement.xml`（495／3／3）、`local/streaming-environment-recheck.xml`（41 通过）、`local/fixture-five.xml`（5 通过）、`local/remaining-nine.xml`（8 通过／1 失败）、`local/binding-contract-recheck.xml`（最后 1 项通过）。新增材料保护在 `report-material-protection.xml`；改为不同当前／父消息后，只重查对应 3 项，最终 `report-parent-protection-fixed.xml` 通过。选项修复在 `question-body-preview.xml`（5 通过／1 测试读取公有 DTO 错误），该节点改从持久记录核对内部 ID 后 `question-body-preview-fixed.xml` 通过。`local/test-node-results.json` 按实际先后保留每个节点全部结果。

### 本轮确认并修复的三处系统问题

1. **报告读取工作上传材料失败**：`report_context.load_materials` 已先经 `agent_attachment` 验证工作材料归属及访问权限，但又把工作直接上传材料的空 `message_id` 交给 `active_message`，导致 D09 在生成模型调用前失败。现在仅对有消息来源的附件复核父消息；工作材料、工作权限、提取版本和 chunk 校验保留。新增 13 项检查覆盖正常读取、未关联、移除、工作／文件删除、跨用户／公司、权限撤回、提取变化／缺 chunk，以及正常／删除／撤权的不同父聊天消息。正确 L 夹具包含 12 项工作、24 条不同日期／状态进展；冻结后一次真实样本实际读取 12 份工作材料、调用一次报告模型，48 个事实断言均满足，草稿未提交、管理员读取 404。实际 `completion_tokens=3829`、正常 stop，不称实际证明超过 4000 输出。
2. **无规则生成受到工具说明误导**：D07-submit 的实际 wire 含“生成时传 employee obligation ID”的无条件旧说明，与生成动作无需预查待办冲突。仅将说明限定为“选择已有待办生成”场景，普通按周生成不要求规则／待办。冻结后一次真实生成并提交成功，`publishedRevision=2`、父卡 completed、管理员 GET200；未修改提交权限矩阵。原拒绝仍保留。
3. **同名工作选项变成不可区分**：C08 模型原始选项已区分“核对12份／缺3份”和“预算8000／联系供应商”，服务端却改成真实同名标题加旧 `summary` 空串。`interactions.ask` 现在为已授权本人工作采用 summary 或当前正文的 160 字预览，继续使用真实标题／对象 ID／revision，不接受模型伪造描述；读取前复核当前访问权限，他人资料仍受原有权限限制。6 个最小定向节点最终通过；原 raw 问题零模型重放后，实际页面显示两段不同正文。对照、持久记录和截图在 `real/C08-controlled-replay.json`、`real/C08-controlled-options.png`，不是新的真实模型首试。

三处业务源码原位修改；测试修改在 `tests/server/modules/work/test_work_materials.py` 和 `tests/server/agent/execution/test_assistant_interactions.py`。其余测试调整仅处理已取消二次审核需求、更新工作快照字段、完整四栏报告夹具、当前授权 Schema 和明确的来源可见性合同。`authorization_contract_repair[evidence]` 保留证据变化导致新模型调用、无旧 repair 文本的断言，同时明确直接授权留下的未执行事项触发 STALE_BINDING 安全拒绝、零写入；没有改业务安全绑定逻辑。公开 execute 同请求重放、提交后响应丢失及事项恢复已有通过证据。

### 仍失败或未完全覆盖的项目

| 结果 | ID  | 实际结论                                                                                                                                             |
| ---- | --- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 失败 | A04 | 把未勾选的原件核对说成“尚未开始”；未勾选只能证明未完成。                                                                                             |
| 失败 | B04 | 数字／条件正确，但正文泄露读取行号、字符范围及内部读取过程，违反已有明确规则。                                                                       |
| 失败 | B06 | 将“不含采购金额”误读为金额冲突，后续又错算附件分类数量，并暴露附件 ID。                                                                              |
| 失败 | D03 | 输入确有 21 和 34，正常 stop 原始输出及保存报告遗漏 21；页面独立分支正确，不能抵消模型遗漏。                                                         |
| 失败 | D05 | 助手首试现有 4 次内部请求均超时，尚无足够证据区分外部服务排队／推理／网络原因；无额外重试。页面无规则生成成功。                                      |
| 失败 | G03 | PPTX 将“验收后支付”加强为“验收合格后支付”；DOCX 正文条件正确。两者 OOXML 有完整中文，但本地渲染缺中文字形，未满足中文视觉验收，不能以 XML 文本代替。 |
| 部分 | A06 | 修正时间的 30 轮合成历史确实进入真实末轮输入并保留早期限制；实际 1M 上下文未触发压缩。原夹具时间错误及中断失败保留。                                 |
| 部分 | D10 | 正常真实流程和受控 invalid-JSON 子任务失败／原任务重试通过；计划中的精确子任务超时注入未执行。                                                       |
| 部分 | E01 | 初次消歧和原问题续接已执行；W 正文没有要“更正”的审核期限，后续目标问题合理，夹具不足不能算完成修改。                                                 |
| 部分 | E02 | 真实 3 题均由自定义文本作答；单选自动跳页、返回改选未由真实流程执行。受控 DOM／Schema 边界另列。                                                     |
| 部分 | F06 | pending／failed／unavailable 及正确回执通过；另一动作／目标／成员的完整替换矩阵未充分逐项对应。                                                      |
| 部分 | F08 | 取消、旧 fence、防迟到及保留已提交内容通过；专用进程 SIGKILL／接管节点跳过，未冒充已执行。                                                           |
| 部分 | F10 | 前缀、异常、重试、SSE 状态及权限变化检查通过；原正文／工具参数交错解析疑点未精确复现归因，不能关闭。                                                 |

C10 修订夹具真实上传同名旧／新文件后，只保存新版 7 个工作日文件，原两份材料和完整正文／属性不变；模型额外询问一次保存位置，按原问题选择 W 后完成。E06 的 ask／auto／full、明确先预览后同意／拒绝均有实际结果。G01／G02／G04 原沙盒不可达失败保留，启动本轮自有真实 gVisor 沙盒后各按冻结输入至多恢复一次；XLSX 值／类型／空白、G02 2000／800／2800 汇总与图、G04 改标题后内容一致和旧链接原 hash 均已核对。没有用 export_table 冒充通用沙盒执行。

A03 原始模糊草稿、A05 合法 no-op、C10 缺旧附件、A06 未来时间均单独留痕后修订；不是纯模型失败改提示重采。D04 初次错误删除定位未入队，修正定位后的实际请求入队后才因人格校验抛错，最后只读补采原任务；其实际人格为 dabao，排除同条件耗时比较。先前暂停还造成 A06 在途失败和 51 条之后的登录／观察器错误；DB 消息／任务证明这些 51 条此前未入队后才执行，原始失败日志未覆盖。

### 验收与资源交接

当前自有 API `8022`、Web `5202`、单 worker 暂留用于只读验收；精确 PID／命令在 `real/environment.json`，私密配置仅在受保护文件中。两个隔离 schema 分别为 `spec081_web_cf110a5dd673`、`spec081_web_b2a7dab1014c`。自有沙盒 project 为 `spec081-expanded-cf110a5dd673`，两个容器完整 ID 和归属标签在 `sandbox-owned.json`。不操作日常 Postgres／Redis 或生产数据。

验收后清理命令（已执行默认 dry-run，尚未清理）：

```bash
.venv-server/bin/python artifacts/agent-response-latency/expanded-20261026/cleanup-owned.py --execute
```

脚本逐项验证进程命令、schema marker、私密目录和容器 project/ID，正常停止本轮进程，再清理本轮 schema／私密凭据／命名空间／容器及其专用卷网络；保留测试日志、原始模型记录、截图和下载成果。新增 JS 观察器已使用项目安装的 Prettier 按文件格式化；Python 不在项目 Prettier 覆盖范围。本轮没有提交、推送、部署或远端 CI 结论。实施报告不是独立验收结论。

独立验收已核实上述计数及三处系统修复，整体仍为 FAIL，无必需业务代码返工。随后协调 Agent 执行已有清理脚本，重新核验归属后成功停止本轮3个进程，删除2个隔离 schema、专用 Redis 命名空间、私密配置及2个自有沙盒容器和专用卷／网络；共享服务与日常环境保留。实际结果见 [cleanup.json](../../artifacts/agent-response-latency/expanded-20261026/cleanup.json)。原始证据均保留，未提交或推送，本轮停止验证。

## 七项缺口补测与超时归因

本轮七个要求分支均已实际执行，**执行完整度 7/7；这七项质量为 6 通过、1 失败；全 54 项当前质量为 47 通过、7 失败、0 部分覆盖**。新增失败为 A06 原始模型回复泄露内部字段，未用系统提示补丁或重新采样掩盖。旧 A04/B04/B06/D03/D05/G03 失败原样保留。当前台账及原 54 项完整历史在 [coverage.json](../../artifacts/agent-response-latency/gaps-20261026/coverage.json)，原 expanded 文件未覆盖；这是实施结果，尚待新的独立验收。

### 分支结果与证据

| ID  | 实际执行与结论                                                                                                                                                                                                                                                                                                                             | 证据（均位于 gaps-20261026）                                                                                                                                             |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A06 | 隔离配置冻结 `contextWindow=80000`，实际估算 140610 超过 90% 门槛，经真实生产压缩到 11364；3 次真实摘要模型调用后真实主模型答复。持久摘要、主模型实际输入和原始输出均保留早期“原件只供阅读、不上传第三方”和最新 9000/2400/6600、验收后支付。质量失败：原始答复暴露 messageId、“历史 transcript 为空”等内部信息。                           | `A06-compaction.json`、`history-preflight.json`、`real/cases/A06-past/results.jsonl`、`real/trace.jsonl`                                                                 |
| D10 | 正常助手编排实际 report child；在未改变的生产 `request_with_deadline` 下无进展 60.000122 秒后超时，原父卡 blocked／子任务 awaiting_retry。浏览器点击原报告页“重试”一次，同 child attempt1/fence2 成功；原父卡 completed、同 action 成功、报告内容一致，仅 1 份报告、revision1→2、publishedRevision0，无重复业务操作或手动 ReportRevision。 | `D10-fault-freeze.json`、`D10-consistency.json`、`real/D10-retry/`、`real/D10-final-details/`                                                                            |
| E01 | 冻结工作正文确有 3 工作日审核期限，真实材料 M5/M7；真实助手先澄清，回答 M7 后正文改成 7 工作日，其他正文块、条件、属性及材料保留。一次写入，revision1→2；真实详情 GET200，截图已实际查看。                                                                                                                                                 | `real/cases/E01/results.jsonl`、`real/cases/E01/1-E01-1/`                                                                                                                |
| E02 | 真实模型返回 3 道单选题；浏览器 radio 自动跳下一题，回到第二题将 next_week 改为 this_week，再提交。原卡仅 1 次 POST、每题仅 1 个最终 optionId、一次真实续接。续接追问选项明确暂缓的工作主题，再真实回答一次，最终仅创建《审核资料准备》一项、期限 11月1日、系统内文字交付，无文件；详情 GET200。                                           | `E02-selection-assertions.json`、`real/E02-radio/`、`real/E02-topic/`、`real/E02-final-details/`                                                                         |
| F06 | 另一 action、target、member 的回执以及实际入队的 pending report child 均不能消除旧 schema 失败或宣称完成。member 经真实 DTO 权限检查 404 并回滚，pending 使用真实生产 generate_report 入队结果。既有 positive 不重复。                                                                                                                     | `local/receipt.xml`、`local/receipt-member.xml`、`local/pending-child.xml`                                                                                               |
| F08 | 专用进程在写入前、提交后、交付后三处真实 SIGKILL/reclaim；旧 fence 迟到经实际 lease 被拒绝 3 次。最终 3 份工作／3 份回执，重复副作用和 stolen lease 均为 0。                                                                                                                                                                               | `local/process-worker-recovery.json`、`local/process-late.xml`                                                                                                           |
| F10 | 5 种任意 name/arguments 分片、content/tool 交错、Unicode/escape、嵌套字段与整包 tool_arguments 一致；4 种非法尾部安全撤回。写入前／后两条完整 HTTP 分片失败链均经原重试机制及原任务重试，最终仅一次实际写入，完整原回执和 SSE snapshot 一致。4 个 opt-in 真实 Redis 传输节点全部通过，含独立 reader 进程、容量拒绝与独占容器重启。         | `F10-parser-attribution.json`、`local/stream-before_write.json`、`local/stream-after_write.json`、`local/stream-new.xml`、`local/stream-recovery.xml`、`local/optin.xml` |

A06 是**受控低阈值下实际压缩**，不是自然 1M 窗口压缩；仅修改新 owned 环境的配置和版本快照，实际模型、low/high、输出预算和重试次数未变。首个新 A06 误沿用未来日期历史，未把历史带入，已计入新增初始输入并保留原失败夹具结果；第二次先以实际 refs 和 estimator 只读验证 30 条历史、早期限制及末轮纠正再入队。没有假摘要。A06 的 `job.state=awaiting_input` 是 `tasks/processing/handlers.py` 既有无操作／无交付物纯文本生命周期；其 `taskOutcome=completed`、remaining 空，模型没有发等待指令，页面按 completed 展示。不得将该状态误报为模型误选或新系统缺陷。

E02 两次未提交的驱动失败源于 Playwright `check()` 在自动换题后重新定位；改成单次 `click()` 并等待题号变化后，继续原 interaction。未产生额外 answer POST 或模型调用。D10 重试观察器曾等待错误标题，成功任务未重发，后续只读原页面取得最终证据。所有驱动原错误仍保留。D10 初始提交到失败子任务 72.429 秒、失败页面观察 73.619 秒；人工等待 76.497 秒；重试 POST 到成功 38.720 秒；从原提交到成功合计 187.646 秒。原驱动 `usableSeconds=73.619` 实为失败页可见，明确不能当成功交付耗时。

### D05 已证实的失败层

未新增付费诊断请求。原 job `9807fa9a-f483-458e-bcac-16b3355ee3f2` 的原始 trace／日志已逐事件提取到 [D05-diagnosis.json](../../artifacts/agent-response-latency/gaps-20261026/D05-diagnosis.json) 和 `D05-raw-timing.json`，保留原日志行号与调用 ID：

- `worker-resumed.log` 3695–3702、3707–3714、3719–3726：三次 TCP 分别 56.581／61.200／84.298 毫秒完成，TLS 握手分别 10005.005／10001.105／10000.955 毫秒触发 `ConnectTimeout`，尚未发送 HTTP 请求头／体。
- 3731–3744：第四次 TCP 117.314 毫秒、TLS 5668.608 毫秒完成，请求头／体已发送；等待响应头 54202.712 毫秒仍无响应头，由原有 60 秒无进展保护取消，底层 `CancelledError`、外层 `TimeoutError`，从 model.send 到结束 59999.235 毫秒。
- 四次都是初始助手模型，未进入报告子任务／模型内容，没有额外程序模型往返；10 秒 connect 限制和流式 60 秒无进展限制、四次重试边界均为现有代码。

因此已区分 TLS 握手超时与“请求发出后尚无响应头，被系统 deadline 结束”，不能统称网络、模型推理失败或报告子任务超时。客户端证据不能再区分供应商入口排队、内部处理或中间链路细节，该最小剩余部分需要供应商日志。没有据此改网络、加时、增加重试或换模型；原 D05 质量失败保留。

F10 历史限制单列：`report-budget-20261026` 的 **3 次** `on_delta/ReplyCandidate invalid_response` 没有完整失败字节，旧 observer 只保存成功返回的 wire_output，确切非法前缀／工具索引／名称变化无法还原；不得归咎模型。expanded 的 **8 个**混合 attempt error（包含连接超时）另列，不是 8 个解析失败。本轮完整可控刺激证明当前边界与恢复路径，未发现新的 parser 产品缺陷；不能声称恢复了历史字节或找到了那三次确切刺激。

### 修改、检查与预算

本轮无新增产品业务源码修改。仅将 `scripts/company/web-acceptance/agent-audit/faults.py` 的现有等价 allowlist 纳入 spec081，保留精确 schema/runId/marker/PID 归属保护；并补充 `tests/server/_support/agent/process_worker_recovery.py` 的真实旧 fence 迟到检查、`tests/server/tasks/test_invalid_work_attempt_recovery.py` 的四个回执反例、`tests/server/agent/streaming/test_assistant_reply_stream.py` 的 11 个分片／恢复节点。前一轮三处产品修复未改动或重复验证。新文件哈希在 [source-hashes.json](../../artifacts/agent-response-latency/gaps-20261026/source-hashes.json)，真实样本冻结、完整合成输入／输出／工具／时间、数据库读回和页面截图均在同目录。

按共享任务恢复与流式传输的 S3 受影响范围补验，共 **20 个去重节点最终通过**：4 Redis、1 真实进程恢复、4 错误回执、11 分片／恢复。`local/results.json` 保存每次结果历史。首次进程节点在 spec081 allowlist 处拒绝、尚未 kill；修正入口后仅重跑该节点。追加迟到写断言后再跑一次该节点。member 测试原期望返回 failed，实际契约是404；两条恢复测试原期望漏了正确追加的业务回执，均只修正断言再定向验证。pending child 从受控返回值加强为真实入队后仅重查该分支。未删除失败历史或放松业务断言，未重复 Redis 及前轮 1946 服务端／426 Web 通过项。

实际执行命令和节点在 `local/run-optin.py`、`local/run-process.py`、`local/run-process-late.py`、`local/run-new.py` 及各 `.log/.xml`；最后回执 member／pending child 和 streaming recovery 的小范围命令见对应日志。本轮修改 Python 不在项目 Prettier 覆盖范围，未引入其他格式化器；最终仅检查本轮 diff，不进行全套 build/lint/typecheck。

[budget.json](../../artifacts/agent-response-latency/gaps-20261026/budget.json)：新增 **5 初始输入＋3 次问题回答＋1 次报告重试＝9 总输入**；其中 8 个消息任务。新增 provider HTTP 请求 28 次，另有 1 次注入超时的 ModelUsage 记录未真正发出 provider HTTP。累计 **70 初始／99 总输入／307 provider HTTP 请求**，未超过 80/160 上限。首次无历史的 A06 已计入，两次 radio 未提交驱动错误无新调用；不是把内部调用算成用户场景。

### 保留资源与独立验收交接

仅运行 [cleanup-owned.py](../../artifacts/agent-response-latency/gaps-20261026/cleanup-owned.py) 默认预览，未执行清理。[cleanup-preview.json](../../artifacts/agent-response-latency/gaps-20261026/cleanup-preview.json) 已核对 exact schema marker、runId、当前 PID 参数及独占 Redis 容器 ID/标签：

- 真实环境 schema `spec081_web_7201e5bad4c5`，API8022/PID92285，Web5202/PID92287，worker/PID93595；runId `7201e5bad4c547348756fecf5fabc778`。新 worker 使用本轮 `runtime-timeout.py`，已退出的旧 worker 不复用。
- 本地恢复 schema `spec081_recovery_2f97d27d1498`，runId `2f97d27d14984da3b7240f6dbd9d757e`；没有常驻测试进程。
- 专用 Redis namespace `spec081:7201e5bad4c547348756fecf5fabc778`；独占故障测试 Redis 容器 `ccdd8a0891216afbd91395286b626c354a8a8e8bf590068307e636966b62228e`、标签 `codex.spec081=gaps-20261026`、端口6398。

验收后可由协调 Agent 运行 `.venv-server/bin/python artifacts/agent-response-latency/gaps-20261026/cleanup-owned.py --execute`；届时重新验证归属，先停本轮进程再清对应 schema／namespace／私密目录及凭据／独占 Redis 容器，保留全部证据，不动共享服务与沙盒。当前私密配置仍供验收使用，路径仅在环境 metadata 中。没有 commit、push、部署或远端 CI 结论。本轮无待实施的系统修复；已完成执行的模型质量失败与历史字节不可得限制保留，交新的独立验收判断。

## D10 进度摘要与 D05 引用返工

上一节首个实施结论 **47通过／7失败**保留为历史。随后独立验收确认 D10 失败阶段把“报告生成入队”节点成功误计为业务完成，实际为 `taskOutcome=blocked`、`completed=[]`、报告正文为空，故独立质量口径为 **46通过／8失败**，七项补测 **5通过／2失败**、执行仍为 **7/7**。当前 [coverage.json](../../artifacts/agent-response-latency/gaps-20261026/coverage.json) 已按该 FAIL 更正，并保存首个实施、独立验收及本次修复记录；本次局部验证通过后仍待新的独立验收，不自行改写其结论。原始快照、错误截图、首试耗时及预算完整保留。

### 共享修复

- `apps/web/src/features/jobs/utils/progress.ts`：有 `taskOutcome` 时以其状态显示完成摘要，不再把成功工具节点数量追加为“已完成 N 项操作”。核对服务端 `tasks/feedback/outcomes.py` 后确认 `completed` 也包含部分内容交付和进展建议，因此同样不把其长度当操作数。无结果合同的旧任务保留既有计数；取消状态优先显示“已中断”。
- `apps/web/src/features/jobs/components/TaskProgress.tsx`：取消摘要复用同一方法，避免取消仍暴露同类错误计数。任务节点的真实步骤状态、成功业务卡、失败原因、权限及重试行为均未修改；没有按工具名称、中文标签或 D10 特判。
- 两份既有进度测试补齐成功入队与业务交付的区别、处理中／等待／部分完成／取消／恢复、无结果合同兼容及展开节点保留。部分完成含真实保存步骤及非操作完成项，仍显示“部分完成”并保留原成功步骤。
- [D05-diagnosis.json](../../artifacts/agent-response-latency/gaps-20261026/D05-diagnosis.json) 的失效 `tasks/retry.py:run` 引用改为 `apps/server/app/tasks/retry/runner.py:7 (run)`。只改派生引用，原四次请求、raw timing 和 worker 日志均未覆盖；未改网络、deadline 或重试预算。

### 相称验证与页面证据

按 **S1** 处理，两份 TS／TSX 业务文件及两份测试文件已使用项目已安装 Prettier 按文件格式化。唯一测试命令为：

```bash
node_modules/.bin/vitest run --config apps/web/vitest.config.ts tests/web/assistant/task-progress.test.ts tests/web/dom/assistant/task-progress.test.tsx --reporter=default --reporter=json --outputFile=artifacts/agent-response-latency/gaps-20261026/ui-rework/tests.json
```

**2文件、30测试通过**，见 [tests.log](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/tests.log) 和 [tests.json](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/tests.json)。这些是本次相关测试执行数，不与此前426 Web节点重复累加。没有全量 lint／typecheck／build，没有重跑此前20服务端节点或1946服务端／426 Web集合。

真实 React 聊天页沿用 owned Web5202/API8022，以 GET 网络快照重放原 `D10-retry/before.json`、原 `firstMessage` 处理中及 `D10-final-details/result.json`。在同一页面通过既有离线／在线恢复事件刷新，展开的节点保持：失败摘要“暂时无法继续”，处理中“正在处理”，成功“已完成”；失败原因及报告失败／生成中／成功卡与快照一致。三张截图已逐一实际查看，见 [失败](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/failed.png)、[处理中](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/processing.png)、[恢复成功](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/recovered.png)。[replay-result.json](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/replay-result.json) 保留源文件哈希、摘要、同页身份及预算哈希；相邻 `.html/.txt` 为 DOM／文本，[network.json](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/network.json) 为无凭据网络记录。首次驱动仅因凭据文件结构读取错误在登录前退出，修正私密文件入口后成功；失败记录在 `driver-history.json`，没有额外业务或模型请求。

这是**受控快照页面重放**，不是新的真实模型端到端样本，也没有恢复数据库旧状态。仅1次 owned 登录 POST、其余 GET，**0业务 POST、0新增模型请求**；累计仍为 **70初始／99总输入／307 provider请求**，预算文件前后哈希一致。原报告同一 child attempt1 成功、仅1报告、revision1→2 的证据复用，不重新触发模型或60秒故障。[D10-consistency.json](../../artifacts/agent-response-latency/gaps-20261026/D10-consistency.json) 追加了原误判与修复证据，保留原恢复断言的适用范围；[source-hashes.json](../../artifacts/agent-response-latency/gaps-20261026/source-hashes.json) 保存原四份指纹与新增四份文件，`source-delta.patch` 追加本次小修，独立补丁另存 `ui-rework/source-delta.patch`。

A06及六个旧质量失败继续保留，F10历史失败原始字节不可得的限制不变。本次未修改模型提示、预算、API或后端调用；没有全面质量PASS或提速结论。未commit、push、部署、查询远端CI或清理资源，owned服务留给主Agent和新的独立验收；必要局部验证已通过，停止扩大检查。

新的独立验收已通过 D10 摘要及 D05 引用返工，最终台账按验收结论更新为七项执行7/7、质量6通过／1失败，全54项47通过／7失败／0部分覆盖；整体质量仍FAIL。原首次实施47／7、中间独立验收46／8、原错误截图和修复过程均保留。没有增加模型调用，累计预算仍为70初始／99总输入／307 provider请求。

协调Agent随后执行已有 `gaps-20261026/cleanup-owned.py --execute`，新鲜核对进程参数、数据库schema标记及容器ID／标签后成功停止本轮3个进程，删除2个隔离schema、专用Redis namespace、私密配置／凭据和独占故障Redis容器。实际清理记录为 [cleanup-final.json](../../artifacts/agent-response-latency/gaps-20261026/cleanup-final.json)，原始证据保留，共享服务及日常环境未动。无本次必需系统返工，不追加采样或重复通过检查，未commit、push或部署。

## 输入契约、确定性统计与失败取证实施

本阶段完成已授权的输入整理、附件程序统计、报告事实分组和隔离观察器失败取证；**不作质量通过或全面提速结论**。必要模块检查最终151个去重节点通过，真实采样仍有模型质量失败。全部新证据位于 [input-contracts-20261026](../../artifacts/agent-response-latency/input-contracts-20261026/)，旧失败与旧台账未覆盖，后续交新的独立验收，不再补提示或真实采样。

### 实现及保护边界

- `agent/context/history.py` 仅投影模型 materials 时去掉 `feedbackProjection` 和空字段，保留续读定位的 `messageId`。没有全局替换用户文本；共享 references、private snapshots 与 task_context 中授权／续接标识未改。相同30条历史的材料封装从3270降到2490字符（减少780），原用户文字和必要ID均保留，不能宣称完全不向模型传ID。
- `modules/attachments/inventory.py` 增加 `inventory_summary`；handlers 和 get_message_context 从同一个可见 inventory 得到总数、既有 kind 分组和口径。统计包含当前可见未删除上传项、重复上传各计一项；收到不等于读过，缺事实不等于冲突。程序不从任意正文猜金额、合计或冲突。工具继续保留 text/userRequest/reply 与分页合同，仅省略空 transcript。
- `agent/reports.py` 增加模型专用 `confirmed_by_work` 投影和输入版本，按 workId 关联 currentState 与有序原始 facts；数字、条件、时间、来源和逐条进展仍在输入中。权限核查、原 source_payload、source digest、保存保护与原持久事实不改。没有添加审核／规划／润色轮次，也未改报告8000输出预算（该改动此前已有）。
- 最终集中说明在实际使用的 `agent/prompts/main.py`：来源卡与正文内部标识的边界、保持数字／时间／否定／条件、不添前提；work 能力说明未勾选只表示未完成，没有完成依据继续保持进行中；documents 能力按程序口径计数，区分收到／读过、缺事实／冲突，只在任务需要时说明未读范围。没有要求所有附件任务使用金额／音频模板。
- `scripts/benchmarks/assistant-latency-runtime.py` 只用于隔离观察器：为请求关联 requestId，在异常时保存已经解析的公开 content 与 tool 参数增量、阶段、64000字符／1024增量上限、截断与遗漏标识。排除 reasoning 和已知凭据（覆盖凭据跨相邻分片）；不保存可能含私有推理的原始 SSE。工具JSON失败可保留回调前增量，SSE解析前失败和非流失败不能虚称有完整字节或增量；原异常原样传播，观察器写失败不能覆盖原错误，不产生新业务／模型调用。历史三次 invalid_response 的原始失败字节仍不可得。

### 实际提示入口缺陷与有界修复

首批9初始／11总输入后发现实施接线错误：新主提示说明写到了旧 `prompts/policies.py:POLICY`，实际 harness 使用 `main_policy`。因此首批没有收到这部分新说明，不能声称模型忽略已送达规则。首批源码与结果保存在 `first-candidate-source/`、`first-candidate.patch`、`real/cases/`，报告 WORK_POLICY 和其他输入投影当时已生效。

撤去旧 POLICY 的本轮无效修改，把原先约定的说明精简接入实际 CORE／按需能力；没有按首批模型答案添加新规则。实际 worker→harness→模型请求的3个定向节点通过后另行冻结一次8初始／10总输入：B06 high三轮、A04 high、A06 high受控80K、B04 high、G03 DOCX low、G03 PPTX low、A01 low、A02 high。首发 B06 wire 已核实实际包含说明才继续其他样本，证据 `wiring-first-wire-check.json`。D03 输入完整、报告政策已生效但漏21，故未再采样；D05 外部失败不采样。

首批冻结 SHA256 `407cf0949c7b49c1bb5af61f7c0d4cae7df11b5b05a644bf52185890d7a7a800`；接线版冻结 SHA256 `564cb50b8c4dc384d211f85596b20d6517b3d732bfb1f8a9fead90a1019c640d`。`final-source-check.json` 核对接线版冻结的472个源文件全部未变；两轮来源、输入、原档位、顺序和上限分开保存，不能混为同一候选。A06仅隔离配置切换80K阈值，30条历史用户文字与原失败夹具一致，实际3次摘要调用和1次主模型调用；模型、网络、输出计划和重试预算未改。

### 相称检查

按跨模型输入、权限事实和保存边界的S3受影响范围执行相关模块，未重跑此前1946服务端／426 Web集合，也未做全量build/lint/typecheck。

| 记录                            | 实际结果                       | 原因与后续                                                                                                                 |
| ------------------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `local/targeted.log/xml`        | 99节点，97通过／2失败，56.10秒 | 旧报告测试仍断言原数组；get_message_context空text被省略影响既有契约                                                        |
| `local/fixed-contracts.log/xml` | 50通过，18.64秒                | 保留text/userRequest/reply合同；报告检查核对完整事实与分组，不只换字段；仅重查2失败及48个受影响conversation_task_state节点 |
| `local/observer.log/xml`        | 5通过，0.03秒                  | 取证脱敏／日志异常保护修改后仅重查观察器；覆盖实际adapter的tool JSON、SSE和非流失败、截断、跨分片密钥与原异常              |
| `local/wiring.log/xml`          | 3通过，3.43秒                  | 实际harness完整请求、work能力和documents能力装配包含新规则                                                                 |

执行器为 `.venv-server/bin/python -m pytest`，使用 owned local 环境，具体实际节点、参数化、时间和失败原文见以上 JUnit／log。`local/executed-scopes.json` 从实际JUnit重建完整选择器供复现，明确不是另一次运行；`local/results.json` 保留每个节点历次结果，最终151个去重节点通过。已通过项未无故重跑。Python文件经项目已装Prettier `--file-info` 确认 inferredParser=null，不在其覆盖范围，未引入另一格式化器；本次相关diff检查通过。

### 真实质量观察（实施判断，待独立验收）

[quality-observations.json](../../artifacts/agent-response-latency/input-contracts-20261026/quality-observations.json) 保存每分支原结果路径、SHA和任务ID；完整原回复、工具参数序列、SSE、刷新截图、下载与数据库读回保留。

| 分支     | 观察                                                                                                                                                                                                                                                                     |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A01      | 按要求仅输出排序结果，无工具和写入，未发现本次质量问题。                                                                                                                                                                                                                 |
| A02      | **失败**：原“须验收后支付”变为“验收合格后支付”，增加前提。确切历史原回复也有同错，属于旧pass漏判；见下文，不宣称是新提示导致。                                                                                                                                           |
| A04      | **失败**：未再把未勾选说成尚未开始，但确定推断签字依赖外部负责人、本人不可控，并添加期限暂停须有提交补签要求依据等原文没有的条件。                                                                                                                                       |
| A06      | **失败**：原件只读／不上传第三方、9000／2400／6600与验收后条件都在真实压缩后保留，仍在正文输出messageId和UUID。                                                                                                                                                          |
| B04      | **失败**：正确引用终止条款、提前30日及保密义务存续，未再输出行号／字符范围；仍输出检索词、无匹配及全文覆盖检查过程，不能仅匹配旧泄漏字符串判通过。                                                                                                                       |
| B06      | **整段三轮失败**：最终核对改为无差异、单一金额来源与五份无金额材料计数正确、图片与第三批同名来源区分正确，末轮无UUID；但首轮仍有received、revision和完整提取说明，第二轮列完整附件UUID，未满足原输出边界。音频在首轮已读并说明，不因末轮没重复音频说明而机械添加新断言。 |
| D03      | **失败保留**：真实报告输入按工作含21、34，100、200不在输入，保存的草稿仍只含34、publishedRevision=0。证据 `D03-evidence.json`；不程序猜正文语义或补算，也未因主提示接线修复重采此路径。                                                                                  |
| G03 DOCX | 数字、签字后归档／验收后支付保留，未添加“合格”；Office实施Agent用修好字体的同一可复现环境确认1页中文正常，原文件哈希未变。正文“核对已完成，共核对12份”需结合已核对12份与补签后才能归档全文由独立验收判断状态边界。                                                       |
| G03 PPTX | 数字与条件保留，原错误“验收合格”未再出现；Office实施Agent确认2页中文正常且原文件哈希未变。同样将“核对已完成”措辞交全文独立判断，不以单个关键词判对／错。                                                                                                                 |

Office结果单列内容和视觉，原文件与渲染见 `office/candidate-review.json`；不是对首批未接线Office文件作最终提示效果判断。所有本轮只读工作快照前后相同，D03只保存草稿；没有为了得到绿灯再改提示或重采。

历史漏判证据：[A02-historical-misclassification.json](../../artifacts/agent-response-latency/input-contracts-20261026/A02-historical-misclassification.json) 保存 expanded 的 `real/cases/A02/1-A02-1/answer.txt`、`results.jsonl` SHA，以及 gaps `coverage.json` 第155／159／165行原A02 pass位置。旧“47通过／7失败”只能称原台账结论，不能在发现此具体漏判后无条件作为准确质量基准；旧文件不覆盖，交协调／独立验收追加纠正。新旧同一条件断言下均失败，既不能归因新提示，也不能因此把本次转为通过。

### 输入、耗时与预算

[comparison.json](../../artifacts/agent-response-latency/input-contracts-20261026/comparison.json) 为机器可读逐轮新旧对照；`evidence-index.json` 还保留首批接线缺失阶段和每次实际请求的角色、哈希、公开输出、工具参数及计时。下表“旧→候选”均为非同期，D03候选是首批、其余为最终接线版。字符为各次请求消息文字之和（不含图片base64），schema字符单列；token为provider实际usage，不是估算。耗时到页面可用／文件下载／报告打开，未只取首字。

| 分支      | 可用秒        | chat请求 | input tokens | 消息文字字符  | schema字符  |
| --------- | ------------- | -------- | ------------ | ------------- | ----------- |
| A01       | 4.23→3.23     | 1→1      | 2318→2360    | 1870→1930     | 3683→3683   |
| A02       | 2.95→18.52    | 1→1      | 2343→2381    | 1902→1962     | 3683→3683   |
| A04       | 34.45→35.63   | 3→4      | 23096→29604  | 21460→25824   | 45921→61176 |
| A06       | 144.71→101.73 | 4→4      | 93756→94860  | 153509→154519 | 3689→3689   |
| B04       | 17.15→20.25   | 3→3      | 45145→31608  | 64683→41329   | 31367→31367 |
| B06第1轮  | 18.42→17.80   | 1→1      | 7936→8090    | 10470→10804   | 10495→10495 |
| B06第2轮  | 15.14→9.85    | 1→1      | 10712→10905  | 16927→17292   | 10495→10495 |
| B06核对轮 | 13.91→17.10   | 1→1      | 13160→13312  | 22468→22862   | 10495→10495 |
| D03       | 31.90→26.53   | 4→4      | 14087→14335  | 18946→19377   | 21056→21213 |
| G03 DOCX  | 10.83→16.97   | 3→3      | 22209→20531  | 12361→8958    | 54259→54259 |
| G03 PPTX  | 14.51→20.39   | 3→3      | 20451→20482  | 8717→8907     | 54259→54259 |

A02的18.52秒不能归为模型或提示变慢：原worker日志第1377–1417行显示排队0.601秒、provider2.864秒，首SSE4.354秒／首屏4.464秒。主要差额是worker `model.end`→`persist.start` **12.378秒**，随后最终保存0.418秒、最终SSE18.189秒／DOM18.518秒。该阶段包含usage持久化、graph／checkpoint收尾、pendingReply与确定性交付检查；现有事件未细分各await，不能锁定其中某个确定等待缺陷，也不能称纯验收驱动污染。原值保留，细节见 `A02-timing.json`；无额外模型、工具、重试或采样。若另行定位，最小下一步是在隔离固定模型返回下对这一段补分段／DB等待观测，不直接增加真实样本。

DOCX旧成功来自同会话环境恢复续接，新样本为初始生成；原值仅供追溯，不能作同输入提速对照。B04总输入下降同时工具读取路径变化，不能全归因投影；A04工具路径从3次变4次，不能隐去成本。A06最终87395 input tokens属于3次压缩、7465属于主模型；D03为助手8583、授权4449、报告1303，未新增审核轮。所有请求逐调用细节见机器对照。相同静态规则CORE435→495字符、work375→408、documents304→422，其余能力不变；schema单次定义没有为本轮新增工具。字符节省与新增说明均如实列出，不能宣称总token下降或全面提速，更不能以质量失败样本证明质量不下降。

[budget.json](../../artifacts/agent-response-latency/input-contracts-20261026/budget.json)：旧70初始／99总输入／307 chat provider请求；首批9／11，接线修复8／10，累计 **87初始／120总输入**。原80／160上限与针对已确认接线缺陷另行冻结的87／120上限并存记录，未伪装首批在新规则下执行。新增45 chat provider HTTP请求，累计352；另外实际2次ASR调用单列，新增模型调用合计47。21次admission均有结果，无隐蔽重采，授权预算余量0。原模型与low/high、网络、重试预算不改。

### 保留资源与交接

新鲜进程命令核对及准确路径见 [owned-resources.json](../../artifacts/agent-response-latency/input-contracts-20261026/owned-resources.json)，全部保留给独立验收，尚未清理：

- 真实 schema `spec081_web_4bb833ae634b`，runId `4bb833ae634b4279b8f9a6fc3028835a`；API8023/PID10952、worker/PID10964、Web5203/PID7933。
- 本地检查 schema `spec081_baseline_4b5f7145e6d4`，runId `4b5f7145e6d44911bca0913b32f2ca64`，无常驻测试进程；metadata中端口只是配置，不代表第二套监听进程。
- Redis namespace `spec081:4bb833ae634b4279b8f9a6fc3028835a`；owned沙盒8014，compose project `spec081-input-contracts-4bb833ae634b`，runtime容器 `144cf9b7786e637be0818c7886b381ef16a218fa86b22ea9a0cf6906a4fa5249`、control容器 `77d932a70ddb3a228d338eb8e24b7947f6189c039ffb0d7a84c0491a62d13afb`。
- 两套私密配置目录、两份credentials路径及sandbox-state路径均列于资源清单；只记录指针，不输出密钥。验收后协调Agent须重新核对归属后清对应进程、schema、namespace、私密配置和自有沙盒资源，保留证据，不动共享服务。

未commit、push、部署或查询远端CI；未修改acceptance.md，也未作最终验收。本轮系统修改及相称检查已完成，剩余模型质量失败／Office措辞判断与历史漏判如实交接，停止扩大验证。

### A02 保存前停顿的有界系统归因

针对上述12.378秒继续完成一次 **0真实provider** 的受控重放，独立证据见 [A02-system-attribution/attribution.json](../../artifacts/agent-response-latency/input-contracts-20261026/A02-system-attribution/attribution.json)。`replay.py` 在短生命周期测试进程里把原公开provider回答作为一次固定SSE返回，阻止其他所有HTTP；真实submit_message原子入队／占用后，走原process_job、BoundedChatModel、usage事务、LangGraph、实际Postgres checkpoint、pendingReply、finish_waiting、assess和保存。原业务源码及真实样本未修改，正文与原A02完全相同，无工具、修复或额外模型轮。

本次 `model.end→persist.start` **0.109673秒**：usage尾事务10.864毫秒、checkpoint收尾19.197毫秒、pendingReply7.939毫秒、finish_waiting9.488毫秒、assess16.328毫秒；整个受控worker0.950秒，全部SQL最大24.014毫秒。原12.378206秒未复现，不能据此否认原等待或归因模型；原日志没有逐await／SQL锁等待／OS负载历史，仍无法识别确切阻塞者。固定回答也没有重放原私有推理、网络分片时序和历史资源竞争。这是系统归因证据，不替代原真实耗时，不是新增质量采样，不证明性能通过。

Office实际转换重叠已排除：渲染脚本先创建新目录再执行转换；candidate-docx/pptx目录birth为14:46:25.395964／25.397510，晚于A02停顿结束14:45:25.063约60秒。仅排除真实转换／栅格化，不凭最终产物mtime推断父Python启动时间或旧停顿原因。

未发现可确定修复的固定等待／内容触发缺陷，故没有猜测性业务改动、第二次重放或151节点复跑。新增仅原owned schema中的受控会话、消息、job `b7b05d9e-d940-44aa-910d-2cf9b79f75d6`、一条合成usage及checkpoint，均由原schema清理覆盖；该usage不是真实provider请求，原87／120预算和原证据不变。没有新增常驻进程、schema、端口或容器。`resource-check.json` 新鲜核对原metadata进程归属仍准确，无需改写；服务保留供验收及协调Agent清理。

### 主模型既有输出边界恢复

仅在实际 `prompts/main.py:CORE` 恢复原“正文不汇报读取范围或完整性检查”，保留本轮内部ID、数字、时间及条件约束；未改报告政策、工具合同、节点或重试。交接最初误指 `test_assistant_persona.py`，核实后更新的是 `test_tool_catalog.py` 既有实际harness政策断言，persona文件未动。

按S1只运行既有普通回答接线节点 `test_ordinary_prose_exposes_catalog_and_question_once_and_keeps_clock_role_mode`，通过1项／2.33秒；使用owned local环境与固定fake，验证实际首次system请求，未重复151节点。Python不在项目Prettier覆盖范围；本次diff符合预期且diff检查通过。证据见 [prompt-restoration/result.json](../../artifacts/agent-response-latency/input-contracts-20261026/prompt-restoration/result.json)、同目录补丁／前后SHA及测试log／JUnit。

CORE静态字符为495→511（增加16，不是token测量）。原472份源码冻结中仅main.py因本次恢复变化，其余471份一致；原final-source-check、两轮冻结、真实trace与预算哈希不变。新增真实初始／总输入、chat HTTP与ASR均为0，累计仍87初始／120总输入／352 chat HTTP，新增阶段原2次ASR单列。恢复提示仅本地已验证，未新增真实模型实测，B04原失败及整体质量FAIL保持；A02历史12.378206秒根因仍未知，既有0.109673秒固定响应重放不能解释原等待。未提交／推送／部署、未清理或重启常驻资源，未修改验收报告。

协调Agent已读取最终独立验收PASS（仅最小系统返工），并单列[历史A02覆盖纠正](../../artifacts/agent-response-latency/input-contracts-20261026/historical-coverage-correction.json)，原台账与模型失败不覆盖。随后执行本轮 `cleanup-owned.py --execute`，重新核对进程命令、两个schema所有权及沙盒容器／网络的compose标签，成功停止3个自有服务、删除2个隔离schema及私密配置／凭据、专用Redis namespace、2个沙盒容器和1个专用网络；共享服务与镜像未动。见[实际清理记录](../../artifacts/agent-response-latency/input-contracts-20261026/cleanup-final.json)。原真实与受控证据均保留，未知系统等待仍未关闭；停止本轮工作，未提交、推送或部署。

### B04 恢复约束后的单次真实补验

仅复用原 `long.txt`（SHA256 `5c3308fd953fe1a799e2b628e7c09705896f7ac355c506c2d50a823dd2c852e6`）和“找到终止条款并说明例外。”，high一次完整流程；未改业务代码／提示，未重跑151节点、单元或build。新证据在 [b04-restored-check-20261026](../../artifacts/agent-response-latency/b04-restored-check-20261026/)，冻结SHA256 `7ed6d9ac917a8f3ff2322bc31bdc51a5d37c5abcf02c22d67a20af7da64665d9`，860源码指纹前后不变。关闭沙盒会改变files目录和documents工具，故新建独占沙盒保持可见配置；实际首次工具schema与最近 `input-contracts-20261026/real/wiring/B04` 完全相同，4次实际wire均包含恢复的“正文不汇报读取范围或完整性检查”，模型／high／stream及参数一致。

**实施质量仍FAIL**：原文第45节、提前30日书面通知、尚未完成的保密义务继续有效均准确引用，但正文仍写“例外／除外／不受这几个词全文均无命中”、其他位置未出现及无配套条款等无关检索／覆盖过程。第45节是合法条款定位，不机械视为内部信息；来源卡行／字符范围与正文泄漏分开判断。最后provider公开正文与持久正文、answer.txt完全相同，未经过后处理改写。原始回复、SSE、刷新截图、展开来源卡截图、工具参数和数据库读回齐全；source-card首次只读驱动把summary误定位为button而超时，修正定位后读取同一结果，旧错误保留，没有新增业务输入／模型调用。

本次4次模型／6次find_documents，50217 input tokens、69922消息文字字符、41803 schema字符，首SSE29.951秒、首屏30.029秒、最终可用33.7795秒；最近恢复前B04为3次模型、31608 input tokens、20.2467秒。均为非同期单样本且工具路径不同，不作提示因果或速度收益结论。模型错误／节点重试0，ASR与沙盒调用0，业务写入0。新增1初始／1总输入，累计 **88／121** 达到本次上限；新增4 chat provider请求，累计356，未追加采样。具体见 `comparison.json`、`quality.json`、`final-output-check.json`、`budget.json`。

资源保留待独立验收：schema `spec081_web_54a078904d78`、API8024/PID21323、worker/PID21324、Web5204/PID21325；Redis namespace `spec081:54a078904d784c958b0cbdf47fe99ea5`；sandbox8015/project `spec081-b04-restored-54a078904d78`。`owned-resources.json` 与 `cleanup-preview.json` 保存准确容器／网络／3个自有卷、私密目录指针和进程参数。`cleanup-owned.py` 默认只读预览，执行前验证schema标记、runId、PID参数及精确容器ID／compose标签与卷独占归属；已预览，未执行。由协调Agent在验收后运行 `--execute` 清本次资源，保留证据和共享服务。第4条历史12.378秒等待未重放、原因仍未知；本次不commit／push／部署。

独立验收确认本次B04仍FAIL：实际约束已投递，原始模型正文与持久回复相同，无新增已确认系统缺陷，停止补提示或重采。协调Agent随后按新鲜归属核验执行本轮cleanup-owned.py，清理3个进程、1个隔离schema及私密凭据、专用Redis数据、2个沙盒容器、3个自有卷和1个专用网络；证据保留，见[清理记录](../../artifacts/agent-response-latency/b04-restored-check-20261026/cleanup-final.json)。未改业务源码、提交、推送或部署。
