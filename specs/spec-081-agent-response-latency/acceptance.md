# Acceptance

## 当前整体交付结论（更正）

**FAIL** — 本轮最终候选周报仅1/2成功，尚不能确认满足用户“修改后质量不能下降”的交付要求。工作写入10/10正确和局部安全检查通过不能抵消报告失败。此前将限定范围的独立检查 PASS 用于宣布本轮完成，是协调 Agent 的结论错误；下方历史报告原样保留，不作为当前整体交付通过的依据。

报告子调用的输入、配置及源码等价只能缩小调查范围，不能证明质量未下降。下方新增诊断补齐了直接失败原因，但失败尚未修复；代码仍是未交付候选。

## 周报失败的新增诊断

协调 Agent 复核既有 [worker 日志](../../artifacts/agent-response-latency/contracts-20261025/candidate/worker-final.log) 第228～252行，关联报告 job `1c798d6e-2b5c-435e-870f-edab7481f7d4` 和模型 call `ae280066-58c2-44c8-9767-057448371b5e`：

- HTTP200，`stream_complete=true`，供应商明确返回 `finish_reason=length`；输入1362 token，输出4000 token，正文仅82字符，记录的推理文本长度8451字符。字符数不能换算成精确推理 token 数。
- 实际请求包含 `reasoning_effort=low`、`max_tokens=4000`；模型调用约45.73秒后被输出上限截断。没有证据将本次失败解释成网络中断、报告内容已完整但事实不符，或新增了审核调用。日志中的 `response_repair` 是现有通用分类名，该报告实际只有一次生成请求。
- 因而此前实施／独立验收的“缺 usage 和 finish reason、不能判断是否达到上限”是漏读 worker 日志造成的取证错误，现予纠正。原始日志和历史结论保留；完整失败正文没有保存，仍不能推断具体推理内容。
- 源码追踪为 `reports.generate(max_tokens=4000)` → `context_usage.output_reserve` → `chat(max_tokens=output_limit)`。报告不启用消息任务的 `node_retry`，原有总输出上限为8000，单次仍被4000限制；显式选择的 low 参数被正确保留。

此次只读复核没有新模型请求、测试重跑、业务代码修改或资源启动。确认发生截断不等于已经修复，也不证明将上限改成8000就一定成功。任何预算调整必须明确记录，不能混成同预算提速；完成实际修复和必要验证前，整体仍为 **FAIL**。

## Result

**FAIL** — 业务改动与输入成本下降的证据成立，但 high 档“点击回执并核对工作详情”的取证未完成，实施报告对此表述超出了原始证据。只需修复页面等待与补充现有记录的只读取证，不要求重采模型或扩大业务改动。

## Spec Coverage

- 业务 diff 仅 `apps/server/app/agent/actions/intent.py` 两处 JSON 紧凑序列化；所有字段、字符串、Schema、政策、校验仍保留。未新增模型节点、工具、缓存、预算、重试、推理降档或权限捷径。已有工具加载和回执收束不计为本次成果。
- 已核对冻结清单、实际 diff、两份原始 trace、各样本结果及数据库读回。16 条用户输入对应 8 个不同会话，每个会话依次短答和创建工作；low A1 两次驱动复用同一会话，未伪装成独立样本。实际模型请求为基线 19、候选 16，合计 35，与 ModelUsage 读回一致。
- 实际主模型均为 `deepseek-v4.1-flash`，low/high 参数与样本一致；授权两组均保留 `enable_thinking=false`。每次创建均为两次主模型调用、`load_tools → execute_business_action` 和必要授权；基线多出的三次请求来自原有授权重试，候选没有新增模型回合。
- 首次授权输入四对为 6856→6349、6857→6347、6847→6352、6845→6349 token。Schema 结构等价记录覆盖 general/work/report 三分支，字符串内部空格、换行、引号和反斜杠保留。稳定收益限于输入成本减少约 7.2%～7.4%。
- 8 次短答保留数字与归档前置条件。原始页面结果、`after_commit` 事件和数据库读回共同显示 8 次创建各写入一条预期工作，标题、正文、进行中状态、归属正确；报告、成果、记忆、沙盒执行表无新增记录。未发现本改动导致的多余业务写入。
- low 档详情截图确实包含工作标题、正文、进行中状态；high 档详情证据不足，见下节。原有会话内回执和持久化证据成立，不把详情取证缺口说成写入失败。
- 完整模型请求仅由验证归属的 Spec081 测试进程采集；生产日志和生产启动路径未修改。环境加载保留本机专用测试库、schema 标记、0600 私有配置校验，未发现改动绕过数据隔离。

## Tests and Evidence

- 复核 [定向检查日志](../../artifacts/agent-response-latency/authorization-tests.txt)：10 passed、1 failed。失败为 `test_saved_plan_rechecks_refusal_and_creates_exactly_two_linked_works`。
- 复核 [基线失败日志](../../artifacts/agent-response-latency/baseline-failed-test.txt)：同一测试在隔离基线也失败。基线 `intent.py` 与该测试文件均与 `6622a97` 的 Git 内容一致；堆栈显示 `SelectedJudge` 对追加的非 JSON 修复说明执行 `json.loads(messages[-1].content)`。这是既有失败，不能宣称整个授权测试模块全绿，也不归因于本次分隔符修改。
- 复核 [结构等价记录](../../artifacts/agent-response-latency/serialization-equivalence.json)、[冻结清单](../../artifacts/agent-response-latency/freeze.json)、[汇总](../../artifacts/agent-response-latency/summary.json)、[基线 trace](../../artifacts/agent-response-latency/baseline/trace.jsonl)、[候选 trace](../../artifacts/agent-response-latency/candidate/trace.jsonl) 及两侧 `readback.json`。保存的业务 diff 哈希与冻结记录一致。
- 基线 low A2 两次 `allowedFields`、high A1 一次 `resumetask` 均不在实际完整授权 Schema 属性中，且 Schema 指定 `additionalProperties=false`；保留原始错误和已有重试，不追加提示或重采。候选未出现这些错误不能证明模型准确率提高。
- 本验收仅阅读代码、解析既有证据和查看截图；没有新模型请求，没有重复运行已完成测试，没有全仓 build、lint、typecheck，也没有提交、推送或远端 CI。

## Issues / Required Rework

1. **补齐 high 档工作详情证据并修正实施报告。** [receipt-open.json](../../artifacts/agent-response-latency/receipt-open.json) 的 `high-B2` 文本仍是聊天页；[high-B2/work-open.png](../../artifacts/agent-response-latency/pairs/high-B2/work-open.png) 只有“正在加载页面”。`open-receipts.mjs` 点击后等待的正文在聊天回执里已存在，`first().waitFor()` 可在路由切换前满足，不能证明详情加载。
   - 保留这次 JSON 和截图，不覆盖首试。
   - 对同一已创建工作重新从回执点击进入；等待准确工作 URL 和工作详情专属区域（如标题、编辑内容按钮、进行中状态）均就绪，再断言正文并保存独立证据。
   - 不发送消息、不创建新工作、不请求模型；将实施报告改为与最终有效证据一致。若环境不可用，如实记录，不能用 URL 已变化或旧聊天正文替代详情验收。
   - 按项目规则由新的独立验收 Agent 复核此项，既有通过项不重跑。

## Regression Risks and Limits

- 四对操作端到端均较快，但基线三次模型格式错误重试和候选 low 第 2 次授权 13.022 秒等波动混在结果中，不能把全部差值归因于 JSON。high 短答完整显示慢约 0.38/0.48 秒；该路径未进入改动函数，仍原样保留，不能声称普通回答或全产品提速。
- `browserFirstPaintSeconds` 是首个非空安全正文 DOM，不保证完整可用；本次单句回答采用完整显示时间作为保守可用时间。low A1 没有 SSE 采集，其余操作没有非空流式正文，null 保留。
- 原始 `workCommitTimes.commitSeconds` 实为 `updatedAt`；汇总使用 SQLAlchemy `after_commit` 时间，原始记录不改写。跨进程时间为同机墙钟近似，不宣称亚毫秒精度。
- 未实测报告、文件、复杂材料及用户确认路径的提速；这些业务路径没有修改。Spec080 的历史 FAIL 与未决事项保持独立，既有授权测试失败未修复。
- 验收时两个 worker trace 出现无 jobId 的数据库连接 `OperationalError`。2026-10-25 本地时间，基线最后采样结束为 19:35:43、首个连接异常为 19:55:47；候选分别为 19:34:44、19:55:28。异常不属于这些测量窗口。当前原因未定，不归因于模型，也不能据旧 dry-run 声称隔离服务仍健康或已清理。

## Resource Cleanup

暂保留隔离资源用于上述只读返工。审查 `cleanup-owned.py` 与既有 `load_environment/cleanup` 后，清理边界充分：验证 suite/schema 标记、测试库、精确 Redis namespace、PID 命令与独立进程组；等待所属进程退出后删除对应 schema 和私有配置，保留证据。

返工完成后由协调 Agent 执行清理并以实际结果报告：仅基线 PID `18160/18161/18162`、候选 PID `18552/18553/18554`，以及 `spec081_baseline_c11ff3e99681`、`spec081_web_54a44e6a075f` 的自有资源。当前数据库连接异常须先处理到能校验归属；不得为完成清理跳过所有权校验，亦不得停止共享 Docker、PostgreSQL、Redis 或日常 5174/8000 服务。本验收没有执行清理。

## 返工后的独立验收

**PASS** — 新的独立验收 Agent 已核对本轮只读补证，首次 FAIL 的 high 档详情取证缺口已关闭。上述首次结果、失败截图和限制全部保留。通过范围是本次授权 JSON 等价紧凑序列化及其现有受控／真实样本证据，不代表全产品验收通过或普遍提速。

- 当前业务 diff 仍只有 `intent.py` 的两处分隔符配置，SHA256 为 `9ca66d228e4ae936783a96dcc767e3803dd60e27e6240f8c70ed19eaf2eb9e63`，与冻结记录一致；本轮没有业务或测试修改。
- 将 [原 high-B2 结果](../../artifacts/agent-response-latency/pairs/high-B2/2-create-work/result.json)、候选数据库读回与 [补充记录](../../artifacts/agent-response-latency/receipt-open-rework.json) 交叉核对：用户 `91d6a143-d296-49bf-9538-88ea6a8c810c`、会话 `89de9b63-e5a5-4126-9169-b4e9d955f537`、工作 `5d5128f1-e6c3-4145-a97e-de8dd33986b1` 一致。驱动读取同一回执并点击其链接，等待准确详情 URL、详情专属标题／可用编辑按钮／进行中状态及工作内容区域，已排除旧聊天正文提前满足等待的原因。
- 独立查看 [新截图](../../artifacts/agent-response-latency/pairs/high-B2/receipt-open-rework.png)，页面确为“我的工作”详情，包含“资料归档核对”、进行中状态、编辑内容按钮和完整正文“已核对12份材料，其中3份缺签字；补齐签字后才能归档。”；[页面文本](../../artifacts/agent-response-latency/pairs/high-B2/receipt-open-rework.txt) 与之相符。原 `receipt-open.json` 及只有加载状态的 `work-open.png` 仍在，未被补证覆盖。
- [网络记录](../../artifacts/agent-response-latency/pairs/high-B2/receipt-open-rework-network.json) 包含准确工作详情 GET 200，除登录 POST 外均为 GET，拦截列表为空；[驱动](../../artifacts/agent-response-latency/open-receipt-rework.mjs) 在登录后禁止页面写请求。补采前后 ModelUsage 均为基线 19、候选 16，共 35 次，没有新增消息／模型采样或业务写入证据。
- 实施报告已明确区分原失败证据和补证成功，并保留 general/work/report 共享序列化均有结构等价检查、实际操作模型对照只覆盖工作写入的边界。既有输入 token 减少约 7.2%～7.4% 的结论保持成立，不将完整操作耗时差全部归因于此改动，不宣称普通问答、报告等其他路径提速。

本轮只审阅既有文件、diff、证据和截图，未运行模型、浏览器流程或测试，未执行 build、lint、typecheck、提交、推送、部署或清理。既有授权测试仍为 10 passed、1 个已在原始基线复现的失败；high 短答变慢、外部请求波动、三次基线模型合同错误、历史数据库异常及 Spec080 未决项均不因本次 PASS 消失。

无需进一步返工或采样。[补采诊断](../../artifacts/agent-response-latency/receipt-rework-diagnostic.json) 记录两侧所有权校验及数据库读取成功，之后详情 GET 亦成功，但不能解释此前无 jobId 的连接异常。协调 Agent 可先重新核验当时的 PID／进程组、schema 标记和 Redis namespace，再用已审查的 `cleanup-owned.py --apply` 清理本任务自有资源并报告实际结果；不停止共享服务。清理尚未执行，不能标为已完成。

## 清理结果

协调 Agent 在独立验收后完成新鲜只读归属预检，再执行 `cleanup-owned.py --apply`，退出码0。两个测试schema、各自Redis namespace及私有临时配置已清理，所属6个API／worker／Web进程已停止；原始回复、轨迹、失败截图与补证保留。见 [清理日志](../../artifacts/agent-response-latency/cleanup-apply.txt)。共享Docker、PostgreSQL、Redis及日常服务未停止或删除。本轮未commit、push或部署。

## 用户要求的速度复测

主 Agent 重新运行同一“短答→创建工作”序列，基线仍为 `6622a97`，候选业务diff未变。每个样本使用新的合成员工和空会话，low／high各两对AB／BA，共16条新输入；没有复用或覆盖上轮时间，没有修改业务代码或重跑单元测试。本节为新实测记录，不冒充新一轮独立验收。

以下为从发送到完整回答／已保存回执可用的时间，每组两次的中位数，单位秒：

| 场景 | 档位 | 修改前 | 修改后 | 差值（后−前） |
| --- | --- | --- | --- | --- |
| 普通短答 | low | 4.06 | 3.25 | −0.81 |
| 普通短答 | high | 4.20 | 5.12 | +0.92 |
| 创建工作 | low | 10.01 | 11.46 | +1.45 |
| 创建工作 | high | 13.81 | 13.25 | −0.57 |

本次两组各16次真实模型调用，共32次，无额外模型错误重试。8次短答均保留数字与归档前置条件，8次创建各准确保存一条预期工作，未产生报告或成果。主模型参数仍为实际low／high，授权保留既有 `enable_thinking=false`。输入token减少仍存在，但普通短答不经过修改的授权函数，且实际授权请求有明显耗时波动；不能将普通短答的变化归因于此改动，也不能确认创建工作稳定提速。两个样本的中位数仅描述本次结果，不构成统计显著性。

结论进一步明确为：**本次修改降低了授权输入成本，尚未证实稳定的端到端提速。** 原独立验收只针对等价序列化与输入成本的PASS边界不扩展，旧样本和失败全部保留。

新证据：[逐次时间CSV](../../artifacts/agent-response-latency/retest-20261025/timings.csv)、[完整汇总及回复](../../artifacts/agent-response-latency/retest-20261025/summary.json)、[冻结配置](../../artifacts/agent-response-latency/retest-20261025/freeze.json)。两侧原始trace、浏览器截图及持久读回位于同一复测目录。

## 合同精简实施的独立验收

### Result

**PASS** — 通过范围限于本轮工作范围／授权合同复用、共享工具说明精简，以及已有确定性和真实样本能证明的保护与输入成本变化。未发现最终实现的具体合同回退；不代表全部真实旅程成功、稳定端到端提速或绝对准确率不下降。前轮结果与本轮旧版本失败全部保留。

### Spec Coverage

- 独立核对三个生产文件及其 diff；当前源码哈希与 [freeze-diagnostics.json](../../artifacts/agent-response-latency/contracts-20261025/freeze-diagnostics.json) 一致。范围输入仍不含助手候选修改值，后续独立授权保留。`changed/preserved` 必须唯一、互斥且覆盖十字段，再展开为原 dense 计划并执行原校验；文本 null／明确清空、状态／日期、记录字段、逐字用户引文和清单约束均保留。
- 授权复用计划字段／模式／引文，不默认允许实际提案。成功分支重建本原子组，拒绝只映射真实 `invalidFields`；canonical 后的重复、越界、allowed=true 附错误字段以及 fields／other 参数拒绝空字段会进入原联合修复。已验证材料保存位置缺口的豁免、显式 `failureKind` 来源、精确缺信息约束均保留，没有将默认值伪装为模型显式输出。
- 原计划缓存、dense 持久化、合同版本隔离、授权引文、材料来源与版本、确认、续接、事项绑定、防重放、租约和完成回执路径继续使用。全部计划引文仍在授权输入及持久计划中；内部兼容字段索引取第一条引文，不替代原始授权、持续指令或恢复来源。
- 共享工具仅调整说明；action 枚举、参数、注册入口和执行器未变。工具仍可从工作直接生成报告，实际报告样本均直接执行，没有新增 reports 加载回合、分类调用、预算或重试。

### Tests and Evidence

- 复核已有日志而未重复运行测试：[typed compact](../../artifacts/agent-response-latency/contracts-20261025/typed-compact-tests.log) 86 passed；[最后诊断修复](../../artifacts/agent-response-latency/contracts-20261025/diagnostic-repair-tests.log) 9 passed；[拒绝范围守卫](../../artifacts/agent-response-latency/contracts-20261025/guard-repair-tests.log) 11 passed；[安全检查](../../artifacts/agent-response-latency/contracts-20261025/security-tests.log) 201 passed、12 failed、4 deselected，12 个环境相关失败在 owned 迁移 schema 的[定向重查](../../artifacts/agent-response-latency/contracts-20261025/security-environment-repair.log)通过。检查覆盖有交叉，计数不相加。原 evidence 用例在[原始基线](../../artifacts/agent-response-latency/contracts-20261025/baseline-evidence-test-original.log)也失败；上轮已确认的旧夹具失败仍保留，不能声明整个授权套件全绿。
- 将 [summary.json](../../artifacts/agent-response-latency/contracts-20261025/summary.json) 的全部 116 次调用逐一与四份原始 trace 的调用 ID／wire SHA 对齐：基线55、旧候选21、最终候选40；32条固定输入，无追加质量重采。旧 low B1/B2 的4条输入明确排除最终比较；最终两份冻结版本按行标明，没有以旧失败版本充当最终样本。
- 独立比较最终10次工作样本的浏览器原始结果与候选 `WorkItem/WorkRevision` 读回：创建各一条，更新各一次 revision；正文追加保留原完整块、ID、顺序、条件、备注和属性，属性修改仅更新指定值并保留正文／材料。最终工作10/10成功；最终报告1/2成功，不能用入队或工作成功抵消报告失败。
- 独立查看 high B1 的[报告页面](../../artifacts/agent-response-latency/contracts-20261025/pairs/property-then-report-high-B1/2-weekly-report/report.png)及持久正文：完成栏仅已核对12份，进行中栏保留未完成／受阻，阻碍保留3份缺签字与补齐后才能归档，下一步仍是未来计划；`published_revision=0`。high B2 报告子任务仍为 `awaiting_retry`，持久草稿为空、成功可用时间为 null，明确失败。
- 直接从原始 wire 重做只读比较：失败 high B2 与成功 high A2 的完整报告请求在仅归一化 UUID 和同日种子／revision 采样时间后相同；独立核对所列38个报告／任务／传输源码哈希一致。原始事实、用户要求、周期、状态、正文条件、low 档和4000输出预算未变，支持将其记录为未修改调用链中的失败；缺供应商原始失败响应、usage 和 finish reason，不能进一步断言确定的纯模型、网络或输出上限根因。见[比较记录](../../artifacts/agent-response-latency/contracts-20261025/report-input-comparison.json)。

### Issues, Regression Risks and Limits

- 当前没有要求返工的具体业务缺陷。初版 compact Schema 缺文本限制造成的 low B2 失败是真实实现问题，已恢复原限制；该旧旅程和同时期成功样本不混入最终统计。最终 low 属性／报告没有配对证据，不补采、不外推。
- 六对最终工作更新首次授权输入减少898～1014 token，范围输出减少177～311 token，但范围输入增加304～325 token；主模型输入另列，不能只报告授权节省。范围与授权仍各一次，减少的是合同重复内容。
- high 正文两对完整可用时间仍为15.198→18.546秒、16.947→17.314秒；创建也有变慢样本。小样本和外部请求波动不支持全面提速或统计准确率结论。报告失败原因的精确构成仍未知，不能声明全部所测旅程无失败或全产品质量通过。
- 本轮仅阅读代码、解析既有证据及截图，没有新模型调用、浏览器写入、测试重跑、全仓构建／静态检查、提交、推送或部署。历史 Spec080 未决事项不在本轮关闭。

### Required Rework / Resource Cleanup

无需继续业务返工或模型采样。隔离资源清理由协调 Agent 在最新 PID、进程组、schema 标记和 Redis namespace 归属校验后执行；本验收未操作或清理服务。已审阅本轮 [cleanup-owned.py](../../artifacts/agent-response-latency/contracts-20261025/cleanup-owned.py) 的边界，不将历史 PID 视为当前存活证明，不清理共享 Docker、PostgreSQL、Redis 或日常资源。

## 报告预算修复的独立验收

### Result

**FAIL** — 本轮固定新输入基线8/8正确，候选7/8正确；报告两侧各4/4完成，但候选 high B2 属性更新的成功写入与最终失败反馈矛盾。加上此前未受影响、明确复用的正文／创建8项，当前候选固定集合为15/16，仍不满足全部正确的质量门槛。本节是最新独立验收结论，不用预算局部检查通过替代整体通过；上方历史结论及旧失败全部保留。

### Spec Coverage / Tests

- 核对当前预算代码、[采样冻结](../../artifacts/agent-response-latency/report-budget-20261026/sampling-freeze.json)与两臂源码快照：全部冻结文件哈希一致，两臂仅 `reports.py`、`context/context_usage.py`、`runtime/model.py` 不同，三个候选文件与当前源码一致。基线包含此前未提交候选，不能称为全部优化前的基线。
- 报告唯一生成请求最大4000→8000；实际额度取请求、模型较小能力、原8000任务剩余额度的最小值。耗尽在HTTP前拒绝，返回后越过累计8000仍拒绝；报告即使带 `node_retry` 也不使用32000额度。上下文预留采用同一额度，助手原输出行为和其他内部单次4000边界保留。没有修改模型、显式推理设置、生成次数、重试次数、权限、来源、租约／fence、幂等及保存保护。
- 审阅新增断言和[首次定向检查日志](../../artifacts/agent-response-latency/report-budget-20261026/targeted-tests-first.log)：41 passed、14 deselected。覆盖实际HTTP额度、剩余／耗尽、较小模型能力、输入预留、异常重试上下文、供应商越额、显式high保留、助手隔离，以及相关截断／来源／人工编辑保护。独立验收未重跑测试；这是预算与报告子系统的局部证据，不关闭两项历史授权夹具失败。
- 核对[汇总](../../artifacts/agent-response-latency/report-budget-20261026/summary.json)、两侧原始trace、DB读回、[逐栏质量记录](../../artifacts/agent-response-latency/report-budget-20261026/manual-quality-review.json)和[固定槽位](../../artifacts/agent-response-latency/report-budget-20261026/fixed-quality-slots.json)：16个首次用户输入对应62次请求，基线29、候选33；每个报告子任务均一次生成。实际报告均为low，基线4000、候选8000，不因父助手high而称报告high。八份报告输出与持久正文逐项一致。
- 八份报告周期均为上海时区2026-10-19至2026-10-25，未提交。已逐栏阅读全部正文：完成只写核对12份，阻碍保留3份缺签字，归档仍依赖补齐签字，联系负责人及归档仍是未来动作；基线两个A2的进行中栏为空，但阻碍栏保留未解决条件，不构成已完成误报。独立查看候选四张报告页面，草稿、周期和四栏内容与DB一致。
- 每份报告引用同一工作的原始和属性更新两份revision；DB中的完整正文、原块ID／顺序和“原件由综合部保管”备注保持不变，实际模型输入的最新状态携带完整正文／备注。两侧日期映射记录只涉及 `WorkItem.created_at/updated_at`、`WorkRevision.created_at`，均准确减24小时，落在原请求周期内；没有修改任务、租约、模型时钟或计时。它是owned合成夹具的映射，不是实际业务发生时间。
- 报告输出基线1474～2452、候选1416～1956 token，全部stop。本组证实实际额度传输与完整报告交付，没有观察到超过4000的报告被救回，不能保证8000永不截断。low B1报告28.849→56.014秒等变慢样本保留，不宣布全面提速。

### Issues / Required Rework

1. **修复未执行的非法工作提案经合法纠正后，旧失败仍阻塞完成状态的问题。** [原始调用和失败证据](../../artifacts/agent-response-latency/report-budget-20261026/high-B2-property-failure-evidence.json)、[持久恢复快照](../../artifacts/agent-response-latency/report-budget-20261026/high-B2-recovery-snapshot.json)与[页面](../../artifacts/agent-response-latency/report-budget-20261026/pairs/property-then-report-high-B2/1-property-update/complete.png)一致：job `fa7fd0d9-1883-426d-bebe-7c767d96b851` 的四字段最终正确保存，只有一次新revision，正文／标题／材料未改；但旧六字段失败仍在 `toolOutcomes/operationFeedback`，旧事项仍proposed，最终 `awaiting_input`、`incompleteTask=true`、`taskOutcome=partial`，页面同时显示已更新与部分完成。

   原始工具调用先把保留的title/body错误写成 `{"unchanged":true}`，在 `AgentWorkChanges.model_validate` 阶段失败，尚无独立变更计划。`operations.execute` 经 `invalid_attempt` 将该未执行提案留档为body＋properties事项。第二次删去title/body却复用旧事项，`task_items.reference_error` 以范围不同拒绝；`recovery_candidates` 也排除这一事项。第三次不带旧ID，独立授权后新事项保存四属性。`outcomes.record` 同时要求相同字段集合及兼容事项身份，不能消解原六字段旧失败；`work_requirements.rejected_plan` 又只覆盖已有独立计划、明确not_requested且无taskItemId的拒绝，本例无此证明。最终独立计划明确title/body为preserve，成功回执覆盖全部四个真实要求，因此这是程序恢复／完成状态的具体缺口，不能仅以首次模型参数错误为由停止处理；也没有证据证明它由报告预算改动引入。

   返工应只处理有证据的未执行参数修正：保留原尝试审计，借助同一用户消息／原始来源、动作／目标／引用身份、独立计划及当前合法回执，证明被删字段确实无需修改、全部真实需求已保存，再关联或消解对应旧失败并正确推导任务反馈。不能仅按同target、同step、字段子集或模型自报resolved删除失败；不能消除同一工作上另一项真实正文／进展／材料需求，不能绕过旧回执绑定、来源版本、权限或租约。采用新事项完成时，也必须覆盖跨事项的受证据约束消解，不能只修第二次携带旧ID的路径。

2. **澄清工具中unchanged的输入／回执身份。** `execute_business_action` 的Work changes输入说明中写着“unchanged=true retains the old record.”，而实际输入Schema不支持该标记；原始主模型请求确实看到了这句话，本次把它放入title/body。可最小改为明确“保留字段不放入changes；unchanged属于服务器回执”，不增加泛化提示、额外审核或调用。该句具有歧义，但现有样本不能证明它必然导致了错误，也不能用文案澄清代替第1项状态修复。

最小验证建议：对第1项用固定响应重现非法六字段→合法四字段→成功回执的原始链路，分别覆盖携带旧事项ID及不携带ID，核对只有一次业务写入且最终反馈一致；再覆盖同目标另有未完成正文需求、不同消息／来源／计划、失效或未成功回执不能清除失败的负向边界。按受影响恢复／授权子系统选择必要定向检查，不重跑已通过的预算41项，不加无关测试。真实补证只能在具体修复后按新冻结的受影响范围有界执行，保留本轮high B2失败，不能覆盖首试或将历史槽位改成成功。

### Evidence Limits / Resource Cleanup

- 三次父消息调用在HTTP200／first_body后、完整响应记录前发生收尾参数解析错误，随后按原有节点机制恢复；[内部失败记录](../../artifacts/agent-response-latency/report-budget-20261026/internal-failures.json)保留。代码支持定位到 `on_delta → ReplyCandidate.feed` 拒绝，但完整失败响应、usage和finish reason缺失，具体前缀／混合参数未知；不能据此判纯模型或网络故障。本验收不重采、不顺带修改parser。
- 旧报告length截断、旧候选合同失败、两项历史授权夹具失败和此前变慢样本不被本轮报告4/4抵消。复用的正文／创建8项是历史最终证据，本轮未重跑。
- 本验收仅审阅代码、原始记录和截图，并追加本文件；没有业务修改、模型请求、测试重跑、浏览器写入、commit、push、CI或生产操作。owned资源按交接保留，未清理；后续清理仍须重新核对归属。

## 非法提案恢复后的最终独立验收

### Result

**PASS** — 本轮最终候选的固定质量集合为 **16/16正确：新12项工作流程＋明确复用的4份周报**，并有相称的恢复、授权和持久化保护证据。原high B2的“实际保存成功但旧失败残留”已通过两条实际完成链路关闭；本结论针对当前整个候选与适用固定集合，不以局部测试通过替代整体质量。此前15/16 FAIL、报告截断、旧合同失败及变慢样本仍是历史事实。本轮不是新测16项，也不证明每次模型首轮都正确、全产品绝对无回退或稳定端到端提速。

### Spec Coverage

- 逐个核对[冻结记录](../../artifacts/agent-response-latency/invalid-attempt-20261026/sampling-freeze.json)的477个源码资源与candidate-source，全部哈希一致。当前源码相对冻结仅有[最终差异](../../artifacts/agent-response-latency/invalid-attempt-20261026/final-source-delta.json)列明的task_items.py与feedback/items.py，最终副本及当前哈希一致。新12项原始job均无schemaFailure/recoveredSchemaFailure，不经过这两个新增分支；最终分支的证据来自定向固定响应检查，不能说真实采样直接覆盖了非法恢复。
- 恢复只针对有服务器Schema失败provenance且尚未执行的事项；逐项核对原消息／原文、来源修订、nodeScope、documents、expectedRevision、动作／目标及引用身份。独立计划必须明确被删字段为preserve，合法提案完整覆盖全部真实要求；旧attempt、outcome、barrier及候选／已选计划指纹共同约束调用局部证明。携旧ID与新建事项均保留原失败审计，不按同目标、同step或字段子集宽松清除。
- bind、需求选定及最终写入前均核对证明；最终binding检查、版本检查、source_check、perform、真实receipt和settle处于原lease事务锁内。未取消公司／成员、来源、租约／fence、确认、幂等或并发检查，无新增模型节点／重试。正常无Schema失败路径不增加恢复查询事务。旧checkpoint无服务器证明时保守不恢复。
- 同来源／副本续接只将已由实际action_dto认证的回执对应当前事项展示给原授权模型，再绑定实际所见快照；不是无条件覆盖历史快照。已解决的非法attempt仅按精确digest及同receipt退出活动范围检查；旧审计别名仅在recoveredBy指向同action／target／成功receipt的真实执行项时不进入collect投影，raw taskItems保留。另一真实正文需求、未完成创建、不同receipt或新增非法attempt仍受原检查约束。
- 工作合同精简及报告额度原有验收证据继续适用；预算三文件当前哈希与report-budget候选冻结一致。报告单次最多8000、任务总额度仍8000，实际剩余额度和模型能力取较小值；未扩助手预算、报告次数或显式推理档位。工具说明仅澄清保留字段省略、unchanged属于回执。

### Tests and Fixed Quality Evidence

- 审阅代码、原失败及最终日志，未重跑已通过测试：[32项绑定／恢复检查](../../artifacts/agent-response-latency/invalid-attempt-20261026/targeted-binding-final.log)通过；[真实worker完成双路径](../../artifacts/agent-response-latency/invalid-attempt-20261026/replay-worker-final-first.log)2项通过，实际经过process_job→delivery→persist_final→GET消息；冻结后[续接投影](../../artifacts/agent-response-latency/invalid-attempt-20261026/continuation-projection-final.log)2项与[最终完成投影](../../artifacts/agent-response-latency/invalid-attempt-20261026/finalize-projection-final.log)3项通过。计数存在交叉，不相加冒充独立覆盖。预算41项及此前合同／安全检查按既有证据复用。
- 直接交叉读取12条原始页面result、Job、BusinessAction、WorkItem、WorkRevision和wire。属性四字段准确，标题／原正文块及材料保持；正文只在末尾追加，原块ID／顺序／条件／备注及属性保持；创建各一条、指定标题正文和进行中状态。每条一回执、一次revision变化，最终succeeded、incompleteTask=false、taskOutcome=completed、空remaining／operationFeedback，无多余报告或成果。空材料夹具的保持断言不外推为非空材料渲染验收。
- 42个唯一真实模型请求直接按payload/job归属核对为21助手、8独立plan、13授权。创建high B1首次授权把当前messageId误作不存在的taskItemId，原始两份wire保留；既有拒绝／重试后最终一次创建正确，其额外调用及16.515秒均计入。最终用例成功不等于首轮全对，没有为该错误新增提示或重采。
- 复用的4份周报均来自report-budget候选，本轮没有新报告调用。重新核对持久四栏和每份两条源revision：完成仅核对12份，3份缺签字与归档前置条件保留，联系负责人／归档仍是未来动作，published_revision=0。报告本身均low，不把父助手high写成报告high。报告输出仍全部小于4000，本证据不能声称已经观察到超过4000的报告获救。
- 原12项只有聊天回执页面与DB读回；本次验收发现“均打开详情”的交接表述无对应证据后，实施方更正并补充[三类high B2只读详情](../../artifacts/agent-response-latency/invalid-attempt-20261026/detail-readonly/)。独立查看三张实际详情截图，并核对原账号／会话／回执、准确工作URL、GET200、详情DOM、正文及状态。前后五表完整记录一致，模型42→42；网络除三次登录POST外仅GET，无业务写请求。补证不改原样本或计时，原usableSeconds只到聊天回执可用，不包含详情打开。

### Regression Risks and Limits

本轮未发现需要返工的具体质量或保护回退。固定响应证明原故障及恢复边界，真实12项证明正常交付，两者不能互相冒充。原同来源／副本问题在旧候选有失败证据，完整原HEAD检查被DB连接耗尽挡在夹具阶段，不能声称HEAD已实测复现；DB503已有too many clients诊断，保留失败日志。历史两个授权夹具失败、旧收尾解析原因未定及Spec080未决项没有被本次PASS关闭，不能宣布全仓绿。

速度结论仍限于可核对的合同输入成本减少与逐场景观察。新12项使用不同时刻／源码的历史基线，只能描述性比较，不构成新的AB／BA因果证明；正文本批较快，但创建high两次12.915→16.515秒、10.196→13.233秒及报告low B1的28.849→56.014秒均保留。外部模型请求内部耗时无法分离，不称为纯程序开销；没有证据支持全面或稳定端到端提速。

### Required Rework / Resource State

无必需业务返工或进一步采样。此次独立验收只读代码／既有证据及补充详情，追加本文件；未修改业务／测试，未调用模型、重跑测试、操作浏览器、提交、推送、部署或清理。owned隔离资源按交接保留，cleanup-preview不是实际清理；后续操作须重新核对归属。范围满足且必要证据通过，停止验证。

## 扩展54项集合的独立验收

### Result

**FAIL** — 扩展集合实际为 **41项通过、6项失败、7项部分覆盖**，不满足冻结集合全部正确完成的质量门槛。三处新发现的系统缺陷已有正确修复和相称证据，未发现必须继续修改业务代码的具体问题；这与整体质量未通过并不矛盾。旧16/16结论仅适用于原集合，不扩展到本集合。没有新的同条件前后速度矩阵，不能声明全面提速或质量无下降。

### Spec Coverage

- 独立比较 [sampling-freeze.json](../../artifacts/agent-response-latency/expanded-20261026/sampling-freeze.json) 的894份源码／夹具指纹；当前生产源码相对本轮冻结仅变化 `report_context.py`、`tools/business/actions.py`、`actions/interactions.py`。三份最终源码均与 [final-checks.json](../../artifacts/agent-response-latency/expanded-20261026/real/final-checks.json) 哈希一致。工作区其余历史改动没有算作本轮新增修复。
- **工作上传材料：** `load_materials` 仍先验证原请求和所属任务，再调用 `agent_attachment`；后者验证附件归属、有效工作材料关联及工作访问权限。有聊天来源时继续复核父消息，没有消息来源的已授权工作材料不再读取空消息ID。提取revision和chunk一致性仍强制检查。审阅13个保护节点及不同父消息的3项定向修订，正常、未关联／移除／删除／跨归属／撤权／版本变化／缺chunk分支均有证据。D09原失败保留；修订L夹具后的真实报告实际读取12份材料、一次报告调用、48个事实断言成立，正常stop、输出3829 token，不能外推为实际超过4000的验证。
- **无规则生成：** 查询汇报待办的说明现在只在选择已有待办时要求传ID，普通按周生成无需该前置查询；执行器、权限矩阵和提交流程没有改变。原D07-submit的拒绝文本与矛盾工具说明保留。修复后的 [最终读回](../../artifacts/agent-response-latency/expanded-20261026/real/fixed-final-readback.json) 显示D07-submit-fixed最终completed、publishedRevision=2、管理员GET200；D09-fixed仍为草稿publishedRevision=0、管理员GET404。
- **同名工作选项：** 真实标题、对象ID和revision继续由服务器确定，仅本人工作在当前访问权限复核后使用summary或正文160字纯文本；模型伪造描述不被采纳。6个相关节点最终通过，包含越权及撤权拒绝。核对 [原始问题与受控重放](../../artifacts/agent-response-latency/expanded-20261026/real/C08-controlled-replay.json)，并实际查看 [页面截图](../../artifacts/agent-response-latency/expanded-20261026/real/C08-controlled-options.png)，两条同名选项已显示不同正文。该补证没有模型调用，只证明真实转换与显示修复，不冒充新的模型首试。
- **授权夹具没有放宽绑定：** `test_new_authorization_request_does_not_inherit_prior_repair_constraints[evidence]` 首次直接授权留下未执行proposed事项；随后查询改变证据，同一proposal再次调用judge，但旧事项不在本次模型所见快照中。生产 `bind` 仍要求快照一致，故STALE_BINDING拒绝符合合同。测试仍验证新judge调用、无旧repair输入和零业务写入，另两个proposal／input分支仍成功；不是删除有效断言来迁就错误，也没有修改生产绑定逻辑。公开execute重放等成功路径有独立既有节点覆盖。

### Tests and Evidence

- 对照原始JUnit及 [test-node-results.json](../../artifacts/agent-response-latency/expanded-20261026/local/test-node-results.json)，按节点最终结果去重为 **1955：1946 passed、9 skipped**；首次55个失败仍保存在节点历史。主批1437、补充501，新增保护节点按去重计数，不累加重跑。Web原始JSON为50个suite、**426/426 passed**。这些是本地受控检查，不是1955个真实模型流程，也不能抵消真实质量失败。
- [coverage.json](../../artifacts/agent-response-latency/expanded-20261026/coverage.json) 实有54个唯一基础场景，状态计数41／6／7。按 [budget-counts.json](../../artifacts/agent-response-latency/expanded-20261026/real/budget-counts.json) 的86条唯一消息分类、报告页2次初始生成和2次取消核对：**65次初始输入、90次总用户输入**，在80／160上限内；另1个C08受控任务明确排除，环境恢复和后续输入没有当作独立新场景。
- 直接读取 [trace.jsonl](../../artifacts/agent-response-latency/expanded-20261026/real/trace.jsonl)：279个唯一provider请求，279份wire输入，271份完整输出，8次attempt error。按实际请求的紧凑JSON编码复核279份输入SHA全部一致；记录中的可读payloadJson含格式空格，不能直接用该展示字符串计算wire哈希。授权、报告及原有重试均包含在279中，不能称为279个测试场景。
- 本次只读核对源码、冻结记录、原始输入输出、持久读回、JUnit和已有截图；没有重跑通过的检查、发起新模型请求或运行浏览器流程。验收文档为S0编辑，仅检查追加内容与diff。

### Issues and Limits

六项失败均保留：A04由未勾选推断尚未开始；B04泄露内部读取行号／字符范围；B06误判金额冲突、错算附件类别并暴露ID；D03输入含21和34但正常stop报告遗漏21；D05原有4次请求超时且外部耗时根因未明；G03 PPTX将“验收后支付”加强为“验收合格后支付”，并有本地Office中文缺字形的视觉验证限制。已核对A04／B04／B06原始回复及D03实际报告输入／正常stop输出，不以另一分支成功抵消失败，也不把D05直接归为网络或模型幻觉。OOXML文字存在不能代替中文渲染通过。

七项partial仍未闭合：A06未实际触发压缩；D10未注入计划中的精确报告子任务超时；E01夹具没有待更正的审核期限；E02真实流程未执行单选返回改选；F06错误action／target／member回执矩阵不足；F08未执行SIGKILL接管；F10原交错参数parser疑点未复现归因且4个opt-in传输节点跳过。这些是明确的证据／夹具缺口或尚未归因问题，当前没有足够证据指向一项必须继续修改的具体生产缺陷，不能据此追加泛化补丁或随机采样。

### Required Rework / Stop Boundary

**无必需业务代码返工。** 整体维持FAIL，不能宣传扩展集合通过。遵循已确认边界，纯模型遗漏／加强条件等仅留失败，不加提示补丁、审核模型或重跑到绿；不为消除partial扩大验证。若后续要宣称54项全部通过，须另行解决对应质量失败并补齐缺口，本次不预先承诺这一结果。

本验收只追加本文件，未commit、push、部署或清理，远端CI未查询。API8022／Web5202、单worker、两个owned schema及自有沙盒仍按实施交接保留；协调Agent可按已有清理脚本重新核验精确归属后清理本轮资源并报告实际结果，保留全部原始证据。此次独立验收至此停止。

## 七项缺口补测与超时归因的独立验收

### Result

**FAIL — 补测执行已完成，但发现一项必须修复的系统展示缺陷。** 七个要求分支均实际执行，执行完整度为 **7/7**；D10 在报告子任务失败时错误显示“已完成 1 项操作”，不能因最终重试成功而通过。独立验收口径为七项 **5通过、2失败**，全54项 **46通过、8失败、0部分覆盖**。实施台账的47／7尚未纳入此项发现，需要追加更正；原始证据和历史结论保留。A06为新确认的模型质量失败，D05为已定位客户端阶段的外部请求失败，二者均不因诊断完成改为通过。没有新速度对照，不支持全面提速结论。

### Spec Coverage and Evidence

- **源码边界：** 当前HEAD为 `6622a971bac05ef74f40bff7a7d626e0bfb3a8b1`。独立比较 [sampling-freeze.json](../../artifacts/agent-response-latency/gaps-20261026/sampling-freeze.json) 的468份指纹，差异仅为补正A06夹具后的 `cases.json`；冻结的产品源码未变。四个本轮脚本／测试文件均与 [source-hashes.json](../../artifacts/agent-response-latency/gaps-20261026/source-hashes.json) 一致，范围与 `source-delta.patch` 相符；没有将工作区此前大量dirty内容算成本轮新修改。故障准入仅加入Spec081，精确本机测试库、URL、schema、runId和环境所有权检查仍在。
- **A06：** 30条历史的只读preflight、真实压缩节点、三次真实摘要请求及随后主模型wire相互对应，估算上下文140610→11364，实际配置窗口80000。持久摘要整体及最终主模型输入保留早期“不上传第三方”和最新9000／2400／6600、验收后支付。最终原始模型输出为正常stop，但泄露messageId与transcript；实际系统输入已有“内部字段不进正文”，因此是模型质量FAIL，不能追加提示或采样到绿。`taskOutcome`和`taskInterpretation`均completed、remaining为空；`handlers.py:438`的既有纯文本生命周期解释了job.awaiting_input，不能将其误归因为模型要求等待。该证据仅证明受控低阈值下的生产压缩路径，不证明自然1M窗口触发。首个未来日期夹具失败仍保留并计入输入预算。
- **D10恢复部分成立：** [原失败读回](../../artifacts/agent-response-latency/gaps-20261026/real/D10-retry/before.json)、故障runtime与原始trace证明仅owned D10报告调用attempt0被无进展协程阻塞，现有 `request_with_deadline` 在60.000122秒终止，未发provider HTTP。原页面仅一次retry POST；同child `d8955538-ecd3-42f8-83f2-49e1e8f6eb14` 由attempt0/fence1恢复为attempt1/fence2。独立查看失败／成功父卡及报告页截图，并核对 [最终详情](../../artifacts/agent-response-latency/gaps-20261026/real/D10-final-details/result.json) 与DB：同action、同一报告，revision1→2、publishedRevision0、ReportRevision无额外手动写入，父结果最终completed。初次失败72.429秒、人工等待76.497秒、重试38.720秒，合计187.646秒；原driver的73.619秒仅为失败页可见时间。失败阶段完成数错误见下方必需返工。
- **E01：** 原工作revision1确有3工作日，真实M5／M7上传、模型提问、用户选择7工作日后，revision2仅改变第一正文块的期限；其余正文块、例外、属性与非空材料保持。原始interaction回答、唯一成功update action、详情GET200和实际截图一致，不是对已正确正文的空修改。
- **E02：** 原模型确实返回三道单选题；步骤DOM和截图显示自动下一题、返回第二题保留next_week选中、改为this_week再自动下一题。网络记录只有一次原interaction answer POST，最终每题一个optionId，返回唯一continuation。后续主题问题与原“主题与具体内容由你随后说明”的选项一致；第二次真实回答后仅创建《审核资料准备》一项，期限2026-11-01、系统内文字交付、本次不执行核对，详情GET200及截图一致。两次未提交的驱动错误没有伪装为额外真实样本。
- **F06：** 阅读四个反例及原失败JUnit：不同action／target、外成员404、真实generate_report入队而尚未完成，均不能清除原schema失败或推出completed。member将期望改为真实404契约并保留旧失败／未完成断言，未削弱权限检查；pending分支使用实际child回执，不以伪造成功文本代替。
- **F08：** 生产run_slots／claim搭配确定性业务命令，一个专用worker内三个任务分别停在写入前、提交后、交付后三处屏障，然后实际SIGKILL。新worker立即启动不抢未到期租约，约92秒后完成接管；源码断言最终3工作、3幂等回执、无重复。使用被杀worker的三个原fence调用实际lease守卫，均抛LostLease；这是受控进程故障与迟到写保护，不是三次模型或三个被杀worker。
- **F10：** 9个分片边界涵盖五种名称／参数切分和四种非法尾部；两条HTTP模拟流经真实harness/parser、四次原重试失败后进入awaiting_retry且正文withdrawn，再经原job retry恢复到唯一真实写入和一致SSE snapshot。原始分片events、失败状态及最终回执保留。4个opt-in Redis节点使用实际传输、独立reader进程、容量拒绝和自有容器重启，均通过。受控HTTP响应不能称为真实模型首试。历史report-budget的3次on_delta/ReplyCandidate错误缺少失败原始字节，具体非法前缀／工具索引／名称变化仍不可恢复；当前检查不能证明历史归因或纯模型错误。expanded的8个混合attempt error是另一集合。该限制明确保留，不借本轮通过关闭历史确切刺激归因。

### D05 Timeout Attribution

独立逐行核对原 [worker-resumed.log](../../artifacts/agent-response-latency/expanded-20261026/real/worker-resumed.log) 3695–3744与四个原call ID：前三次TCP分别56.581／61.200／84.298毫秒完成，TLS各约10秒ConnectTimeout，均没有发送HTTP；第四次TLS完成、请求头和体发出，约54.203秒未收到响应头，被既有60秒无进展deadline取消。四次均为初始助手模型，没有报告子任务、有效输出或报告工具执行。`transport.py`的connect=10、`runtime/model.py`的idle_timeout=60以及 `tasks/retry/types.py` 的四次上限、1／2／4秒等待与约99秒job耗时相符，没有证据要求加时或增加重试。

客户端层已定位；供应商入口排队、内部处理和链路细节仍需上游日志，不能凭新成功请求反推。没有新增D05采样或网络改动。[D05-diagnosis.json](../../artifacts/agent-response-latency/gaps-20261026/D05-diagnosis.json) 的 `apps/server/app/tasks/retry.py:run` 引用已失效，实际入口为 `tasks/retry/runner.py:run`，策略在 `types.py`／`policy.py`；派生诊断引用需更正，原日志不变。

### Tests and Budget

直接解析各原JUnit，并逐条对照 `local/results.json` 历史：**20个唯一节点最终全部通过**，包括4 Redis、1进程、4错误回执和11分片／恢复。初次allowlist拒绝、member404及两条恢复文本期望失败仍在；后续相应定向结果确实通过，未把重跑叠加计数。复用此前1946服务端通过／9跳过和426 Web通过，不据此宣称新的D10展示路径已覆盖。

原始trace有28个唯一providerRequestId、28份输入及28份输出；按实际紧凑JSON编码复核28份wire SHA均一致。5份初始admission包含坏A06及修正A06，另3次问题回答与1次报告重试，共9总输入、8消息任务；DB为29份ModelUsage，其中一次注入超时没有provider HTTP。累计 **70初始／99总输入／307 provider请求**，在80／160输入上限内。

本验收只读既有源码、证据、原始日志／请求、数据库读回和截图，没有调用模型、重跑测试或运行浏览器流程。只追加本文件，按S0检查追加内容和引用，不运行build／lint／typecheck。没有commit、push、部署、远端CI或资源清理。

### Required Rework

1. **修复D10失败阶段把报告入队计为业务完成的摘要。** 同时点 `before.json` 中父 `taskOutcome.state=blocked`、`completed=[]`，唯一 `generate_report` action为failed、子任务awaiting_retry、报告为空；但是父节点“报告生成入队”是succeeded。[progress.ts:53](../../apps/web/src/features/jobs/utils/progress.ts) 对所有成功operation节点计数，`:99`拼接“已完成1项操作”；`TaskProgress.tsx`把它用于终态摘要。实际 [failed-parent.png](../../artifacts/agent-response-latency/gaps-20261026/real/D10-retry/failed-parent.png) 清楚显示此矛盾。这是确定的程序展示缺陷，与本轮异步失败验收直接相关；入队成功不能代表报告生成完成。
   - 在现有完成／回执语义内修复摘要计数，保留节点层入队事实和失败原因；不得用隐藏整张失败卡、篡改节点执行历史或把failed action改成功规避。核对共享展示合同，不能按generate_report或中文节点标签硬编码；`taskOutcome.completed`也可能包含内容交付／建议确认，不能机械把其长度当业务操作数。
   - 使用已保存D10失败／成功payload做最小定向检查，覆盖报告入队／失败不报完成及恢复后正确完成；若还显示操作数量，混合已有真实成功操作也须准确。复用本轮真实重试与持久证据，页面补证可受控重放已有payload，不新增模型调用或再次制造60秒超时。
   - 追加更正coverage、implementation与D10派生一致性结论，保留本轮失败截图和原始before/readback，不能继续称D10质量pass或“无待修系统问题”。
2. 更正D05派生诊断中的retry源码路径；不覆盖原trace／worker日志，不因此新增采样或测试。

其余补测证据无需返工或重跑。新实施Agent完成上述最小修复后，由新的独立验收Agent只检查受影响部分；A06及六个旧质量失败继续保留，不能为清零失败修改模型提示。owned环境暂留供必要补证，清理由协调Agent在任务闭环后重新核验归属并执行；本验收不清理资源。

## D10 进度摘要返工的独立验收

### Result

**PASS — 本次进度摘要缺陷及 D05 派生引用返工通过，上一轮必需返工项关闭。** 原七项执行完整度仍为 **7/7**；复用上一轮独立验收的其他有效证据后，D10 当前质量恢复为通过，七项质量为 **6通过、1失败**，全54项为 **47通过、7失败、0部分覆盖**。整体质量仍为 **FAIL**；上一轮 D10 失败及原始页面证据不改写，本次没有新提速结论。

### Spec Coverage and Evidence

- **实现与边界：** 独立审阅四文件 diff。有 `taskOutcome` 时只采用实际结果状态，不再把成功节点或 `completed` 条目数当“项操作”；服务端 `outcomes.py` 确实还会加入内容交付与进展建议。取消优先显示“已中断”，无结果合同的旧任务保留既有计数。没有按报告名称、标签或案例特判，节点历史、业务回执、失败原因、权限和重试路径未被删除或改写。
- **页面与原载荷：** 实际查看 [失败](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/failed.png)、[处理中](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/processing.png)、[恢复](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/recovered.png) 三图，并核对对应 HTML、[重放脚本](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/replay.mjs) 和 [重放结果](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/replay-result.json)。三阶段均是同一原 message／parent job，结果与 action 分别精确匹配原 `before.json`、原 `firstMessage`、原最终详情；摘要为“暂时无法继续→正在处理→已完成”，不再出现操作完成数量。展开节点始终保留“报告生成入队／已完成”，失败原因和报告失败／生成中／成功卡与各阶段一致。
- **来源完整性：** HEAD仍为 `6622a971bac05ef74f40bff7a7d626e0bfb3a8b1`。[source-hashes.json](../../artifacts/agent-response-latency/gaps-20261026/source-hashes.json) 的原四份与新增四份源码指纹全部匹配，原四份与历史记录一致；本次四文件当前 diff 与 `ui-rework/source-delta.patch` 完全一致，两份补丁哈希均匹配。重放记录的三份原始载荷哈希均一致，预算文件也与重放前后哈希一致。
- **网络与证据性质：** [network.json](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/network.json) 共33条记录，仅一次 owned 登录 POST、其余32条 GET，无被拦截的业务写入尝试。脚本以原对象身份替换读取响应，未改真实任务或数据库。这是实际 React 页面上的受控快照重放，不是新真实模型端到端样本；新增业务 POST／模型请求均为0。首次驱动在登录前退出的历史保留。原真实超时、同 child 重试、唯一报告及 revision1→2 的独立证据继续有效，不重复采样。
- **D05引用：** [派生诊断](../../artifacts/agent-response-latency/gaps-20261026/D05-diagnosis.json) 已指向真实存在的 `apps/server/app/tasks/retry/runner.py:7`，该行确为 `run`。原前三次 TLS 10秒连接超时、第四次已发请求后无响应头至原60秒截止的归因与未知供应商内部原因均保留，没有修改超时、重试或网络行为。

### Tests and Limits

独立核对 [tests.log](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/tests.log)、[tests.json](../../artifacts/agent-response-latency/gaps-20261026/ui-rework/tests.json) 及测试断言：同一条定向命令共 **2文件、30测试通过**。覆盖入队与交付区分、各结果状态、部分完成含非操作事项、取消优先、旧任务兼容以及同一展开节点跨状态保留。复用已完成的格式化与测试结果，没有重跑测试、完整build／lint／typecheck、浏览器或模型流程。

累计仍为 **70初始／99总输入／307 provider请求**。A06内部字段泄露和六个旧质量失败继续保留；F10历史三次失败缺少原始字节，仍不能据本轮受控恢复证明其确切刺激或归咎模型。本验收只追加本文件；未修改业务代码或最终台账，未commit／push／部署／查询远端CI／清理资源。

### Required Rework

无本次代码返工项。协调Agent据本独立结论更新 `coverage.json`、`D10-consistency.json` 等最终状态，保留原FAIL与评估历史；随后重新核验owned资源归属并完成清理。该交付收尾不要求新增采样或重复通过检查。

## 输入契约与确定性统计的独立验收

### Result

**FAIL — 存在一项必须恢复的既有提示约束，真实回答质量也未通过。** 历史投影、附件程序统计、报告事实分组及隔离失败取证未发现本轮新增的功能缺陷；但不能把这些局部实现合格写成当前候选整体通过。最终真实分支中A01、G03 DOCX与PPTX可接受；A02、A04、A06、B04、B06完整三轮、D03继续失败。不能宣布全面提速或质量不下降。

### Spec Coverage and Evidence

- 独立核对 [wiring-sampling-freeze.json](../../artifacts/agent-response-latency/input-contracts-20261026/wiring-sampling-freeze.json) 的472份源文件，审阅时全部与当前源码一致；45份实际 `wire_input` 的紧凑JSON哈希均吻合。首批误改未启用的POLICY与后续真实main_policy接线版分别保留，不能合并成同一候选。输入、工作只读快照、报告草稿及文件下载沿 [evidence-index.json](../../artifacts/agent-response-latency/input-contracts-20261026/evidence-index.json) 回看原记录，没有用自动qualityStatus替代语义判断。
- `history.py` 仅删除模型材料投影中的空字段和feedbackProjection，保留用户原文及messageId；权威来源、权限与续接身份未变。`inventory_summary` 从同一个可见附件集合计算总数和kind，独立重复上传仍各计一项；当前输入与历史读取工具共用口径，text/userRequest/reply和分页合同保留，空转写才省略。程序不猜金额或冲突。
- `confirmed_by_work` 保留每条原始summary、状态、sourceId/revision/时间，并把本期最新完整body移入currentState；上游source_payload本来仅为最新状态附body，本投影没有额外丢弃旧正文。按workId分组不混合同名工作；原始持久来源、digest及生成后来源校验继续生效，输入版本参与缓存键。未新增模型审核、额外推理节点或预算。
- 失败观察器仅在显式隔离运行器接入，保存解析后的公开content/tool增量，64000字符／1024增量有界、已知密钥跨分片脱敏，私有reasoning不进入证据；失败写日志异常不覆盖原调用异常。非流及解析前失败不能据此声称原始字节完整，历史F10三次缺失分片仍不可恢复。

### Actual Quality and Office

| 分支 | 独立结论与原始依据 |
| --- | --- |
| A01 | PASS：仅输出1、2、3，无工具或工作写入。 |
| A02 | FAIL：新旧原回复均把“验收后支付”加强为“验收合格后支付”；规则与原条件已进入最终请求。不是可归因于新提示的退化，也不能因历史同错而通过。 |
| A04 | FAIL：不再由未勾选推断尚未开始，但无依据确定签字依赖外部负责人、本人不可控，并把提交补签要求说成期限暂停的必要依据；建议与事实边界未守住。 |
| A06 | FAIL：真实受控压缩保留只读／不上传第三方及9000／2400／6600、验收后条件，最终正文仍列messageId与UUID。 |
| B04 | FAIL：终止条款和保密义务内容正确，仍展示检索词、无匹配和全文覆盖检查。实际三次wire均缺少被本轮删除的旧读取范围约束；不可全部归为已收到完整旧约束后的模型错误。 |
| B06 | FAIL：末轮金额自洽、五份无金额材料及同名来源区分正确；第一轮仍展示received、revision与提取完整性，第二轮列全部附件UUID。不能以末轮改善替代整段三轮通过。音频已在首轮读取说明，不因末轮未重复它另造缺口。 |
| D03 | FAIL：实际报告输入完整包含本周期21和34，排除100和200，保存草稿仍漏21且未提交。该报告政策首批已经生效；保持失败，不追加报告采样。 |
| G03 DOCX／PPTX | PASS（本次两个文件）：已读完整来源、最终回复、OOXML文本并实际查看1页DOCX及2页PPTX渲染；下载200、原件SHA匹配。12／3、补签后归档、8000／2400／5600、验收后支付及联系供应商完整，无“合格”。“核对已完成，共核对12份”在全文中指已核对的12份，紧接明确补签后才能归档，未宣称归档或整项工作完成，不按单个“完成”关键词判错。 |

Office中文无方块、截断或重叠；[candidate-review.json](../../artifacts/agent-response-latency/input-contracts-20261026/office/candidate-review.json) 对应的是最终接线版真实下载文件。原缺字定位于验收用bundled LibreOffice的CJK字体配置，修复为进程级字体配置；未修改产品生成逻辑。结论限已记录转换器与字体环境，不推广到所有Office客户端；旧PPTX错误条件和旧渲染证据保留。

**历史漏判纠正：** 独立复核 [A02-historical-misclassification.json](../../artifacts/agent-response-latency/input-contracts-20261026/A02-historical-misclassification.json) 的原文件及SHA，expanded A02确有“验收合格后支付”，此前pass不成立。仅纠正这一历史槽位时，D10返工后的54项应为 **46通过、8失败、0部分覆盖**，原“47／7”是当时漏判台账，历史文件不覆盖。本次G03改善属于新候选证据，不倒写旧54项，也不伪装为新测全54项。

### Tests, Timing and Limits

独立解析原4份JUnit：targeted 97通过／2失败，fixed-contracts 50通过，observer 5通过，wiring 3通过；按节点与最终结果去重为 **151项通过**。旧失败保留，后续只修合同／观察器及实际接线后定向检查；本验收未重跑测试、build、lint、typecheck或真实模型。已读相关断言，不把常量存在等同于真实接线通过。

真实新增17初始／21总输入、45次chat HTTP及2次ASR；累计 **87初始／120总输入、352次chat HTTP**，原80／160上限及接线缺陷后的单次冻结扩展均留痕，余量0。历史单样本对照有升有降、工具路径有变化，DOCX旧续接与新初始生成不可直接对比；CORE与按需政策增长也已列明，不能把局部字符削减当成总token下降或因果速度收益。

A02原worker日志1377–1417行确认provider约2.864秒、首屏4.464秒、最终18.518秒；`model.end → persist.start` 为 **12.378206秒**，属于模型结束后的系统区间，不能归给模型／网络或单纯浏览器。独立审阅 [固定响应重放](../../artifacts/agent-response-latency/input-contracts-20261026/A02-system-attribution/replay.py)、[结果](../../artifacts/agent-response-latency/input-contracts-20261026/A02-system-attribution/replay-result.json) 和 [分段事件](../../artifacts/agent-response-latency/input-contracts-20261026/A02-system-attribution/events.json)：原公开回复经真实process_job、BoundedChatModel及PostgreSQL checkpoint完成，HTTP入口受控拦截，1次固定响应、0外部请求，回复与原件相同；对应区间 **0.109673秒**，该次SQL最长24毫秒。它没有复现原等待，不能证明历史不存在延迟或将具体原因定为DB锁、模型或环境；原等待根因仍未知，不据此猜测性优化或重采。

### Required Rework

1. **恢复主模型普通路径已有的读取范围／完整性检查输出约束。** [main.py](../../apps/server/app/agent/prompts/main.py) 本轮替换CORE时删除了原“正文不汇报读取范围或完整性检查”。[harness.py:42](../../apps/server/app/agent/harness.py#L42) 的初始system仅组装main_policy/persona/mode/clock；PUBLIC_REPLY_POLICY只用于该文件150行及response_repair的修复路径。本次B04三次实际system均没有这项旧约束。只恢复既有规则与保留本轮必要澄清，不按失败答案叠加新模板、审核或重试；对现有实际harness接线测试补对应断言，运行最小受影响检查即可，**不要求新增真实模型采样**。
2. 协调Agent据本节追加修正历史A02及本阶段的系统／模型归因，保留首试和旧台账。新独立验收只确认上述最小返工及其证据；其余已通过模块不重跑，A02系统时间间隔仍列未知限制。恢复提示不自动使B04或整个候选质量通过。

本验收仅追加本文件，未修改业务代码、未提交／推送／部署／查询远端CI、未清理owned资源。剩余明确模型错误按已授权停止边界保留；当前系统实施因第1项尚不能整体接受，修复后可单独评价系统实现，真实质量仍维持FAIL。

## 主模型既有输出边界恢复的最终独立验收

### Result

**PASS — 仅限上一节要求的最小系统返工。真实回答质量整体仍为 FAIL。** 实际 `main.py:CORE` 已恢复原“正文不汇报读取范围或完整性检查”，保留内部ID、数字、时间与条件约束；未增加模型节点、审核或重试。未发现此次返工的新缺陷，不要求继续补丁或采样。

### Evidence and Tests

- 独立审阅 [恢复补丁及结果](../../artifacts/agent-response-latency/input-contracts-20261026/prompt-restoration/result.json)、当前代码与既有harness测试。断言检查真实首条system消息，仍要求普通回答仅一次调用且无deliveryRepairs；原 [JUnit](../../artifacts/agent-response-latency/input-contracts-20261026/prompt-restoration/tests.xml) 和日志确认最小节点 **1项通过／2.33秒**。本验收未重跑测试或真实模型，复用上一节151节点及Office验收结论。
- 独立计算当前两份变更文件SHA，与返工记录一致；接线版冻结472份源码中仅main.py变化，其余471份一致。两轮冻结、原真实trace、预算与final-source-check的当前SHA均与返工前记录一致，新增真实输入、chat HTTP与ASR均为0；累计仍87初始／120总输入、352次chat HTTP，新增阶段原2次ASR单列。
- CORE为495→511字符，本次增加16；相对本阶段原435字符基线增加76。此为静态字符计数，不是token或性能改善证据。首批无效POLICY接线及随后删除旧输出边界的两项实施缺陷保留历史，不将修复前样本归为已收到完整约束后的模型错误。
- [历史覆盖纠正](../../artifacts/agent-response-latency/input-contracts-20261026/historical-coverage-correction.json) 已单列A02旧pass漏判；独立核对旧台账SHA未变。历史54项纠正为 **46通过、8失败、0部分覆盖**，不是重跑54项，也不以新G03文件改善倒写旧结果。

### Limits and Stop Boundary

恢复后的提示尚无真实模型采样，不能据此宣称B04输出已修好。上一节真实分支结论保持：A01、G03 DOCX／PPTX通过；A02、A04、A06、B04、B06完整三轮、D03失败。Office通过仅限已验收文件和渲染环境；速度样本有升有降，不能宣布全面提速、总token下降或质量全部正确。

A02原 `model.end→persist.start` 12.378206秒仍为原因未明的系统区间；0外部HTTP固定回答重放的0.109673秒未复现原等待，没有证据锁定可修复的固定缺陷，也不能归因模型／网络或标为已解决。本次不再重放。

本验收只追加本节，未修改业务代码、提交／推送／部署或清理资源。最小返工已闭环；自有资源由协调Agent重新核对归属后清理，原证据保留。

## B04 恢复约束后单次真实补验的独立验收

### Result

**FAIL — 检索过程仍进入最终正文。** 原文第45节、提前30日书面通知和未完成保密义务继续有效均被准确引用，但回答仍写“这几个词全文均无命中”“终止一词在全文其他位置没有出现”，并汇报全文覆盖结果。第45节属于合法条款定位；来源卡内的行／字符范围不作为正文泄漏依据。准确引文也不代表全部解释无偏差：“任何一方”“已在履行中”是原句未明确的补充或收窄。

### Evidence and Scope

- 独立核对 [冻结清单](../../artifacts/agent-response-latency/b04-restored-check-20261026/freeze.json) 与当前860份源码指纹，全部一致；原 `long.txt` SHA256 为 `5c3308fd953fe1a799e2b628e7c09705896f7ac355c506c2d50a823dd2c852e6`。仅原问题“找到终止条款并说明例外。”一次high流程，未修改业务代码或提示。
- 独立解析 [原始trace](../../artifacts/agent-response-latency/b04-restored-check-20261026/real/trace.jsonl)：4次实际wire的system均包含“正文不汇报读取范围或完整性检查”，模型均为 `deepseek-v4.1-flash`／high，参数与最近恢复前B04一致，首次工具schema完全相同。最后provider公开正文与数据库读回、[answer.txt](../../artifacts/agent-response-latency/b04-restored-check-20261026/real/B04/1-B04-1/answer.txt)及页面结果逐字相同；这次失败属于模型收到清晰约束后仍未遵循，未发现服务端追加该段过程文字的证据。
- 已实际查看 [展开来源卡截图](../../artifacts/agent-response-latency/b04-restored-check-20261026/real/B04/source-card.png)，并核对刷新正文和来源元数据。来源卡保留；首次只读取证驱动误用button定位的超时日志保留，后续读取同一结果，没有增加业务输入或模型请求。
- 原始记录为1个任务、4次模型请求、6次 `find_documents`、50217 input tokens，节点重试0；数据库仅1条消息、4条模型用量，无ASR、沙盒执行或业务操作。新增 **1初始／1总输入**，累计 **88／121、356次chat provider请求**，达到冻结上限。最终可用 **33.7795秒**，最近恢复前样本 **20.2467秒／3次模型**；非同期单样本且工具路径不同，不作提示因果、普遍变快或变慢的结论。

### Limits and Stop Boundary

本次只读独立验收，没有重跑测试、真实模型、Office或其他矩阵；记录属于S0文档追加，仅检查新增内容及引用。该单例失败不推导全场景发生率，旧失败与整体质量FAIL保持。没有新确认的系统缺陷，不要求继续叠加提示、审核、重试或补采。A02历史12.378206秒系统等待原因仍未知，本次未重新诊断。未提交／推送／部署／清理资源；协调Agent按新鲜归属核验清理本次自有资源，保留原始证据。

## CI 失败修复的独立验收

### Result

**PASS — 仅限提交 `39ecd24794ab30b22bc206f7ad33d1a1be152089` 的本次本地 CI 修复。** 原始40个失败节点均有当前契约下的通过证据；未发现新增业务行为、权限保护削弱或尚需返工的问题。远端运行 `40292076794` 仍是旧提交的失败结果；本次未提交、推送或触发新CI，不能称“远端CI已通过”。此前真实回答质量整体FAIL及B04失败保持。

### Scope and Evidence

- 独立核对当前diff与[原始CI日志](../../artifacts/agent-response-latency/ci-repair-20261026/remote-failed.log)：40项分为24项材料选择、9项材料授权、6项报告和1项循环依赖。生产改动仅将恢复快照守卫移入 `agent/actions/task_bindings.py` 并更新引用；两个函数的AST与原版本完全相同，新模块只依赖 `core.digests`，没有修改授权、来源、租约或写入规则。
- 材料夹具改为当前 `changed/preserved` 完整范围及 `PlannedWorkVerdict` 契约。`compact_plan` 仅编码固定夹具，结果仍核对实际数据库材料身份、目标、其他内容保持、修订和唯一写入，未用生产结果反推期望值。三份历史响应JSON与HEAD逐字节相同，原始解析测试保留；显式投影不是新的真实模型输出。旧第3变体缺少的范围字段现在由独立计划提供，因此改为成功；新增 `scope-conflict` 仍要求零材料／零操作／原修订、4次原授权预算、公开错误与可重试状态。权限拒绝、确认／取消和目标补问续接断言未删减。
- 报告测试对齐已经存在的单次生成流程，明确断言无二次审核；写作要求、完整来源及来源撤销检查保留。旧纠正／复审中断节点改为生成／保存中断，验证失败时原报告和修订不变、草稿阶段准确、重试仅保存一个新修订、保存阶段重试不重新生成、成功后再次重试返回409。未恢复额外模型审核或扩大预算。

### Tests and Limits

独立解析[原始失败清单](../../artifacts/agent-response-latency/ci-repair-20261026/failed-nodeids.json)、[节点映射](../../artifacts/agent-response-latency/ci-repair-20261026/nodeid-mapping.json)及JUnit：`reproduce.xml` 为3项失败；`targeted.xml` 为6项通过／16项失败后主动中断；`fixed.xml` 为115项通过、0失败，日志耗时66.86秒。按有效节点去重得到 **121项通过**，与[结果记录](../../artifacts/agent-response-latency/ci-repair-20261026/result.json)一致。全部40项原失败均映射到通过结果，包含5项材料名称及2项报告阶段更名；中断产生的无节点名空XML条目不计入测试数。旧失败日志保留。

此次涉及权限相邻契约，复用实施阶段的相关子系统检查，包括范围完整性／非法范围、授权修复、并发恢复快照、报告来源／权限撤销与架构依赖检查；本验收未重跑已通过测试、全量测试、build、lint、typecheck或真实模型。没有测试运行时源码哈希冻结：一致性依据是实际编辑／执行记录、协调Agent前后读取的报告diff及当前修改时间。6项报告通过后只修改两个材料测试；115项通过后没有源码修改，当前相关文件修改时间均早于对应测试启动。不能把这项证据描述为运行时源码哈希保证。

清理记录表明本次自有PostgreSQL容器、匿名卷及临时凭证已移除；独立只读查询确认记录的容器ID已不存在。卷与凭证清理依据实施记录，不声称独立恢复其已删除内容；未操作日常服务。本验收只追加本文件，没有修改业务或测试代码。无必需返工，按范围停止；121项定向通过不代表整个CI或真实模型质量通过。
