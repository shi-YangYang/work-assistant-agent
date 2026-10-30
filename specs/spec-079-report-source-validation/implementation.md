# 工作来源与周报校验：实现与验证

仅覆盖工作当前内容、进展与修改记录。报告二次审查及全产品验收矩阵未实施；本报告不是独立验收结论，整个 Spec 未完成。

## 主要改动

- 工作详情、修改记录、报告中的工作依据及业务工作来源不再显示内部第几版；旧 `?revision=` 链接继续定位准确快照。修改记录包含最近操作，以创建、状态变化、正文修改、勾选、材料和进展说明事件，不重复展开正文；缺相邻可见快照时不推断字段变化。
- 编辑进展先检查工作身份/权限及工作、进展预期修订，再验证文字、材料和工作属性。规范化后无变化时复用记录，工作/进展修订及业务时间不变；编辑较早进展不覆盖最新 summary。同文新进展仍是独立事件，材料顺序变化仍产生修订。
- 工作工具、实际 prompt、当前工作投影、保存证据及回执统一说明内部修订用于读取定位和冲突保护。增加 `unchanged`、`updateWorkRevision`，使旧进展的无变化保存仍能引用原不可变快照。
- 无变化回执使用 `satisfiedFields` 表明服务端已经核对达到请求值的字段，同时 `changedFields=[]`；任务需求覆盖及续接接受已满足的请求，工作卡显示“内容未变化，已保留原记录”，不冒充又发生修改。
- 通用冲突提示改称“读取当前内容”，保留原冲突码和恢复流程。文档、报告、私人成果合法版本语义不变。

## 涉及文件

- 后端工作：`modules/work/records/record_commands.py`、`service.py`、`agent/{agent_commands,projection}.py`。
- 工具/prompt/证据：`agent/tools/business/{actions,work,work_records}.py`、`agent/prompts/{main,policies}.py`、`agent/completion/evidence/work_receipts.py`。
- 回执与续接：`modules/operations/receipts.py`、`tasks/feedback/work_requirements.py`、`agent/actions/task_items.py`、`core/versions.py`。
- Web：工作详情/历史/正文、`utils/history.ts`、报告工作依据、业务来源卡、工作操作卡、共享冲突组件和 API 默认冲突文案；共享契约 `packages/api-contracts/src/index.ts`。
- 定向测试：工作记录、工作动作、工作历史/详情/勾选、助手操作卡。
- 真实入口：复用 `scripts/benchmarks/work-checklist/launch.py`，增加 `current-content.py` 固定三步旅程，不允许覆盖既有尝试目录。

## 验证

验证级别 S3，仅工作持久化、回执/续接及受影响 Web 子系统；未运行全仓测试、完整 build 或全量 lint。

### 程序检查

- `npm run test:server -- tests/server/modules/work/test_work_records.py tests/server/modules/work/test_work_checklists.py tests/server/modules/work/test_work_conflict_refresh.py tests/server/agent/execution/test_work_record_actions.py tests/server/agent/execution/test_work_record_tool_access.py`：首次 22 通过、59 fixture 错误，原因为本地 PostgreSQL 未运行。按项目既有 Compose 启动 PostgreSQL/Redis，无 reset 或迁移日常数据。
- 上述限定路径加 `--lf --tb=short`：先前失败的 59 项全部通过，23 项未重复运行。
- `npm run test:server -- --tb=short tests/server/agent/execution/test_work_record_actions.py::test_unchanged_progress_receipt_keeps_original_snapshot_after_newer_progress`：新增回执测试 1 项通过。
- 增加 `satisfiedFields` 联动后，`npm run test:server -- --tb=short tests/server/agent/execution/test_work_record_actions.py::test_unchanged_progress_receipt_keeps_original_snapshot_after_newer_progress tests/server/agent/execution/test_work_plan_completion.py tests/server/tasks/test_plan_feedback_recovery.py`：45 项通过。
- `npm run test:web -- tests/web/dom/work/work-history.test.tsx tests/web/dom/work/work-records.test.tsx tests/web/dom/work/work-checklists.test.tsx`：首次 26 通过、2 个旧标签/API mock 参数断言失败；同步断言后仅重跑 `work-records.test.tsx`，11 项通过。
- 工作历史事件摘要与 no-op 卡片调整后，`npm run test:web -- tests/web/dom/work/work-history.test.tsx tests/web/dom/assistant/business-action-card.test.tsx tests/web/assistant/business-actions.test.ts`：17 项通过。
- 本次修改的 TS/TSX 使用已安装 Prettier `--write` 整理。`npm run typecheck:web` 通过；共享类型和卡片变更后重新通过。
- `git diff --check` 通过。

新增断言覆盖：无变化编辑及幂等重放、文字规范化、较早进展的 summary 与时间不变、同文新建、随附状态变化、工作/进展旧标识拒绝、越权拒绝、无效材料拒绝及复制文件回滚、已绑定材料复用、材料顺序变化、原历史内容保留，以及 no-op 的原进展证据、需求完成和卡片文案。

### 真实模型流程

本地测试库隔离 schema `spec079_web_2716aa576327`，合成账号；8019 独立 API/worker，未使用生产账号、正文或服务。本地已保存配置为 `deepseek-v4.1-flash`，low/high 各一次三步流程：创建含计划工作 → 明确记录一条进展 → 只读查询。每步保留真实回复、工具次序、模型请求/耗时、SSE 与数据库证据，没有替身或重复采样。

| 档位 | 创建     | 记录进展 | 读取核对 | 模型请求数 |
| ---- | -------- | -------- | -------- | ---------- |
| low  | 11.02 秒 | 25.18 秒 | 7.89 秒  | 3 / 5 / 2  |
| high | 12.56 秒 | 26.21 秒 | 10.00 秒 | 3 / 3 / 2  |

两项工作最终均处于进行中，正文计划完整保留；各有一条指定进展，读操作无写入。数据库共 2 个工作、4 份不可变工作快照、2 条进展。没有模型新增节点；表中包含现有主模型与授权/变更计划等实际请求，不能解读成每步只调用一次模型。

真实观察与限制：

- low 记录进展的首次工具调用遗漏 `expected_revision`，服务器拒绝；模型随后读取真实标识再保存，数据库只出现一条进展。保留首次失败，没有绕过防冲突。
- low 最后一句自发称“正文仍是最初版本”。没有显示内部第几版或要求用户提供版本号，但正常措辞仍未完全摆脱版本概念。保留该模型措辞问题，未追加 prompt 补丁、过滤输出或重跑。high 没有此措辞。
- 两档只读任务均为 `awaiting_input / phase=complete / taskOutcome=completed / incompleteTask=false`，这是 `tasks/processing/handlers.py` 对无业务写入普通回复的既有状态语义。初版评测仅认 `succeeded` 导致原始 `jobSucceeded=false`，原文件保留；修正入口的完成判定并在 `assessment.json` 按真实状态重新评估，未重发请求。
- 工具返回/正文已核对；本次真实流程通过 HTTP→API→worker→模型→数据库执行，未进行真实浏览器截图验收。no-op、越权及并发异常由确定性测试覆盖，未声称真实模型触发了这些分支。
- 单次 low/high 样本不能说明普遍性能或措辞稳定性；未做改动前后速度对照。

证据均位于 `artifacts/report-source-validation/phase-a/`（Git 忽略）：`assessment.json`、`low/1..3/result.json`、`high/1..3/result.json`、`trace.jsonl`、`configuration.json`、`contract-sizes.json`。密钥不写入报告或证据；隔离凭据文件权限 0600。实际工作能力 prompt 为 262→375 字符，三个工作工具 Schema 大小记录在 `contract-sizes.json`，不将字符数称为 tokenizer token 数。

可复现命令（新尝试必须使用新证据目录及隔离 schema，不能覆盖本次结果）：

```sh
.venv-server/bin/python scripts/company/web-acceptance/environment.py prepare --suite spec079 --purpose web --output artifacts/report-source-validation/phase-a/environment.json --web-origin http://127.0.0.1:5199 --api-url http://127.0.0.1:8019
.venv-server/bin/python scripts/company/web-acceptance/agent-audit/configure.py --metadata artifacts/report-source-validation/phase-a/environment.json --source-user admin
.venv-server/bin/python scripts/benchmarks/work-checklist/launch.py --metadata artifacts/report-source-validation/phase-a/environment.json --source /Users/yang/project/work-assistant-agent --trace artifacts/report-source-validation/phase-a/trace.jsonl api
.venv-server/bin/python scripts/benchmarks/work-checklist/launch.py --metadata artifacts/report-source-validation/phase-a/environment.json --source /Users/yang/project/work-assistant-agent --trace artifacts/report-source-validation/phase-a/trace.jsonl worker
.venv-server/bin/python scripts/benchmarks/work-checklist/current-content.py --evidence artifacts/report-source-validation/phase-a
```

本任务自有 API/worker 已停止；保留隔离 schema 与证据供独立验收。数据库/Redis 保持运行，没有停止用户日常基础设施。未 commit、push、部署或查询远端 CI。

## 已知限制、待确认事项

- 由新的独立验收 Agent 判断阶段 A；low 模型措辞问题必须纳入结论，不能宣称模型永远不提版本。
- 报告二次审查删除、正文保证方式和全产品验收范围仍待主 Agent/用户确认，本阶段未实施。

# 阶段 B 实施报告

覆盖创建纠错后的状态收束、完整工作来源及报告生成／助手改写取消二次事实审查。阶段 A 的内容和原始限制保留；以下取代其中报告部分“尚未实施”的状态。本节为实施证据，独立验收结论由验收 Agent 给出。

## 主要改动、关键取舍

- 结构校验尚未进入意图授权便失败时，服务端登记原请求、来源和未执行事项，让下一次既有授权回合通过 `failedItemCandidates`／`recoveringItem` 关联纠错。后置 `ValueError` 复用本次已有精确绑定；不新增模型调用、不按标题或 step 合并。同名副本、来源令牌、私人成果及共享附件继续隔离。实际保存回执统一收束事项和失败反馈。
- 原失败工具节点只在同一服务端事项已成功、成功结果与事项具有相同回执、且无残留阻断结果时显示“已恢复”。原节点的失败状态及错误诊断仍留在任务日志；原始 output 释放后仅保留服务端事项 ID，以便刷新仍保持一致。模型自报完成或其他事项成功不能证明恢复。
- 周报来源包含周期内创建、正文／清单／属性和进展变化的本人未删除工作，不再要求 `WorkUpdate`。同工作保留必要的状态演变与有效进展，最新周期快照携带完整正文及清单勾选状态，历史事件携带身份、修订和时间；相同时间戳按修订排序。周期后内容、已删除或已纠正进展不进入当前生成依据，已发布报告仍读取自己的不可变历史证据。
- 生成及助手改写生产路径不再调用 `verify_report`，也不再依据判词纠错。模型自由归纳四栏，程序验证字段、类型、长度、来源及保存条件；明确清空已有报告的授权编辑仍允许，生成空报告仍拒绝，提交原规则保留。没有增加关键词判官或摘录模板。
- 新草稿以契约版本和来源摘要恢复；旧 `review/correcting/corrected_review/ready/rejected` 草稿重新生成一次，不信任旧判词。保存前保留租约、公司锁、报告锁、来源重查、候选、幂等和已保存回执保护。助手改写在授权后再次核对来源摘要。备用评测用 `verify_report` 和旧辅助代码保留，未删除其他用途的模型节点。

## 涉及文件

- 创建恢复：`agent/actions/{operations,task_items}.py`、`tasks/feedback/outcomes.py`、`tasks/nodes/node_state.py`。
- 报告生成与来源：`agent/reports.py`、`modules/reports/generation/{sources,results,validation}.py`（`validation.py` 新增）、`modules/reports/service.py`。
- 报告改写及说明：`agent/actions/{operations,intent}.py`、`modules/operations/targets.py`、`agent/prompts/{main,policies}.py`、`agent/tools/business/actions.py`。
- 定向测试：任务事项恢复、报告来源契约／可靠性／回执／重生成／空来源、助手报告上下文／改写、工作记录来源／已发布材料证据。
- 新增 `scripts/benchmarks/report-source-validation.py`：固定两个正文／清单工作、low/high 生成及改写旅程，拒绝覆盖已有采样目录；样本和预期就近在该脚本定义，无独立用例文件。

## 验证

验证级别 S3，限定任务身份、报告来源和写入保护。未运行全仓矩阵、build、lint 或全量 typecheck；本阶段没有修改 TS/TSX。

必要检查及失败处理如下，原始日志均在 `artifacts/report-source-validation/phase-b/`：

| 日志                        | 结果与解释                                                                                                                                                                             |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests1.log`                | 首批 47 通过、27 失败；26 项因默认专用测试库缺已有 `cancel_reason` 列而在 fixture 阶段失败，1 项暴露无效正文在绑定前抛错。修复统一捕获路径，后续只在新隔离 schema 验证，不迁移日常库。 |
| `tests2.log`、`tests3.log`  | 先前失败项分别 23 通过／4 失败、2 通过／2 失败；先隔离真实配置与测试临时密钥见证冲突，再修正已移除二次审查后的旧调用位置断言。                                                         |
| `source-tests.log`          | 新来源契约初始 4 项通过。                                                                                                                                                              |
| `tests4.log`                | 相关报告／任务集合 58 通过、3 失败；两项旧审查调用次数断言及一项已发布历史证据投影发生变化。修正断言和历史投影。                                                                       |
| `tests5.log`                | 仅上述失败及此前未通过项 5 项通过，49 项未重复运行。                                                                                                                                   |
| `tests6.log`                | 后置失败复用绑定、共享附件隔离及旧快照来源 3 项通过。                                                                                                                                  |
| `clear-test.log`            | 清空已有报告与生成空报告边界 1 项通过。                                                                                                                                                |
| `boundary-tests.log`        | 同 step 同标题独立创建、授权后来源撤销阻止改写 2 项通过。                                                                                                                              |
| `same-time-states-test.log` | 相同时间戳的完成后重新打开仍保留状态序列，1 项通过。                                                                                                                                   |
| `node-recovery-test.log`    | 已知错误参数重放、独立副本、授权纠错及保存回执、节点恢复与原日志保留、异回执及残留失败不恢复，1 项通过。                                                                               |

测试集合包含 `test_operation_attempt_recovery.py`、`test_authorization_evidence.py` 的既有隔离断言，以及相关报告租约、并发编辑候选、保存回执、来源权限、旧草稿五种阶段和修改历史保护。首次失败日志保留，不将中途失败抹成一次全绿；未受后续修改影响的通过项未为全套结果而重跑。清空边界测试执行时重复调用了一次，无新增结论；之后未再重复。

## 真实模型流程与证据

独立 schema `spec079_web_07bc5c6fa71c`、合成账号、8018 API／独立 worker。两个合成工作均没有 `WorkUpdate`：一个已完成且正文说明三份资料已归档，另一个进行中，清单为“收齐议题”已勾选、“发送议程”未勾选，并含会议室未确认的阻碍和下一步。low/high 各一次生成和一次助手改写，没有重新采样；high 生成按原保护形成候选，随后通过真实 API 采用再改写。

| 助手档位 | 生成总耗时 | 生成模型请求（助手／报告） | 改写总耗时 | 改写模型请求 |
| -------- | ---------- | -------------------------- | ---------- | ------------ |
| low      | 30.74 秒   | 4 / 1                      | 15.04 秒   | 4            |
| high     | 32.19 秒   | 3 / 1                      | 24.55 秒   | 5            |

实际模型均为 `deepseek-v4.1-flash`。助手请求分别采用现有 low/high 配置；报告专用路由实际两次均为 `reasoning_effort=low`，未替换模型或提高预算。上述助手请求包含原有意图授权及其有界重试，不能宣称整条助手流程只有一次模型调用。

实际持久化均成功：报告有两个来源、仍未发布；生成和改写均保留已归档、已收齐议题、未发送议程、会议室未确认的事实，没有观测到把整体筹备说成完成。实际节点／调用中没有 `report_fact_review`。来源正文与清单在真实模型输入中存在，数据库 `WorkUpdate` 数量为零。

保留的行为及限制：

- low 生成仍先查汇报待办和报告再执行；原样记录，未追加提示补丁或重发。
- high 改写首次意图授权发生一次 `ProviderError`，已有有界重试后成功。有限核对显示 provider 传输记录成功、随后 `ModelUsage.error_code=invalid_response`，但 `validationCauses=[]`，具体原因待归因，不能认定为某字段的纯模型错误。未发起额外模型请求调查，也未重跑该样本。
- 真实事故的无效嵌套参数通过程序重放验证恢复；没有声称本次模型重新触发同一错误。没有修改真实员工工作、旧会话或报告。
- HTTP→API→worker→模型→数据库及候选采用已实测；没有真实浏览器截图／DOM操作，不宣称完整浏览器 E2E。报告页、调度和待办使用共享生成路径，但没有分别跑新的真实模型入口样本。
- 状态演变、来源纠正／删除、跨周期边界、旧草稿及并发撤销等由确定性测试验证，未声称真实模型触发所有异常。没有改前性能基线，单次样本不能证明普遍速度或语义正确率。

证据位置：`phase-b/assessment.json`、`real/{low,high}/{generate,rewrite}/result.json`、`real/fixtures.json`、`real/high/adopted.json`、`trace.jsonl`、`configuration.json`、`api.log`、`worker.log` 和 `real-run.log`。以上都在 Git 忽略的 artifact 目录；隔离凭据保持私有，不写入 Git。

复现固定旅程使用新目录及隔离 schema：

```sh
.venv-server/bin/python scripts/company/web-acceptance/environment.py prepare --suite spec079 --purpose web --output artifacts/report-source-validation/NEW_RUN/environment.json --web-origin http://127.0.0.1:5198 --api-url http://127.0.0.1:8018
.venv-server/bin/python scripts/company/web-acceptance/agent-audit/configure.py --metadata artifacts/report-source-validation/NEW_RUN/environment.json --source-user admin
.venv-server/bin/python scripts/benchmarks/work-checklist/launch.py --metadata artifacts/report-source-validation/NEW_RUN/environment.json --source /Users/yang/project/work-assistant-agent --trace artifacts/report-source-validation/NEW_RUN/trace.jsonl api
.venv-server/bin/python scripts/benchmarks/work-checklist/launch.py --metadata artifacts/report-source-validation/NEW_RUN/environment.json --source /Users/yang/project/work-assistant-agent --trace artifacts/report-source-validation/NEW_RUN/trace.jsonl worker
.venv-server/bin/python scripts/benchmarks/report-source-validation.py --evidence artifacts/report-source-validation/NEW_RUN
```

自有 API／worker 已停止，隔离 schema 与证据保留给独立验收；用户日常服务未停止，日常 worker 由主 Agent 后续重启加载改动。未 commit、push、部署；未触发或查询远端 CI。全产品扩展不在本次实施范围。

# 阶段 B 返工：连续无效创建参数的身份关联

## 主要改动、关键取舍

修复验收重放中的两次不同 Schema 错误：显式传回服务端事项 ID 的 `create_work` 续试，在当前消息、未绑定回执及全部既有来源／对象／副本身份校验通过后，保留在同一事项的 `invalidAttempts` 中。该记录仅表达待核对的续试声明；首次 `attemptedOperation` 不被下一次无效提案覆盖，原始工具失败和诊断继续保留。

原有意图授权输入携带完整尝试链，仍核对真实用户指令、全部提案和完整待保存内容，必须确认同一原子事项后才可返回原 ID。不同内容的独立同名工作不能仅凭调用者 ID 恢复；受控拒绝测试确认没有写入，另一个独立成功也不清除原失败。新增说明用于新数据契约，不增加授权节点、模型调用或重试次数。授权节点缓存身份包含尝试链摘要，新增失败提案后不能沿用未见该提案的旧授权结果。

硬身份检查逐份核对历史提案，不能借先补来源、后删除／替换来源绕过校验。不同目标、副本、来源令牌、私人成果条目和共享附件仍分开；已成功事项不吸收新失败。真实保存回执仍是完成和节点“已恢复”的唯一依据，`outcomes`／节点展示的业务代码未改动。

尝试链最多保留 8 份不同提案（含首次）；达到上限后保守登记新的未完成事项，不截断证据后宣称恢复。无显式 ID 的不同无效提案仍独立登记，不能仅凭同名或 step 自动合并。这些边界不增加既有执行预算。

## 涉及文件

- `apps/server/app/agent/actions/task_items.py`：仅增加显式无效创建续试的服务端校验、有界提案留存，以及对全部历史提案的身份校验。
- `apps/server/app/agent/actions/intent.py`：将完整尝试链纳入既有授权关联合同和授权节点缓存身份；报告相关已有修改保留。
- `tests/server/tasks/test_task_identity_recovery.py`：将验收事故重放固化为显式／省略最终 ID 两种回归，补充直接受影响的独立内容拒绝、硬身份隔离、上限和成功事项保护。
- 本报告追加返工证据。无目录新增、移动或删除，原计划目录树继续适用；未修改验收结论。

## 验证

按 S3 身份授权边界执行，但范围只覆盖连续错误及直接受影响的隔离检查。使用已有独立 schema `spec079_baseline_2fddbd294c01`，fixture 自建公司和账号并按既有流程清理。没有启动额外服务、迁移日常数据库或调用真实模型。

准确执行命令：

```sh
.venv-server/bin/python scripts/company/web-acceptance/environment.py exec --metadata artifacts/report-source-validation/phase-b-checks/environment.json -- env -u PAA_MODEL_KEY_FILE .venv-server/bin/python -m pytest -q --tb=short tests/server/tasks/test_task_identity_recovery.py -k 'multiple_malformed or malformed_continuation or malformed_chain or same_step_and_title_new_create or recovery_candidates_never_swap_shared or distinct_copy_does_not_clear' > artifacts/report-source-validation/phase-b/rework-multiple-invalid.log 2>&1
git diff --check -- apps/server/app/agent/actions/task_items.py apps/server/app/agent/actions/intent.py tests/server/tasks/test_task_identity_recovery.py specs/spec-079-report-source-validation/implementation.md
```

结果：**14 passed, 20 deselected in 4.48s**；首次运行即通过，没有重跑。事故的两个无效提案均返回同一服务端事项，最终只创建一项工作、保存一个实际回执，最终 `derive=completed`；两次原失败节点展示已恢复但持久诊断仍为原始失败。不同硬身份不合并；不同内容同名工作在授权拒绝后不写入，独立成功后仍保留 partial；超上限失败及已成功事项的保护通过。diff 检查通过。本次 Python 文件不在项目 Prettier 覆盖范围，没有运行全仓格式化、测试、build、lint 或 typecheck。

## 已知限制、待确认事项

这是受控授权模型与真实业务持久化的确定性回归，不证明实际模型能够始终正确识别所有同名语义关系；完整语义关联仍由原有授权回合负责。已通过的报告检查、阶段 A/B 真实 low/high 样本及 high 授权 `invalid_response` 待归因记录均未改动、未重跑。

业务修改保留未提交，交给新的独立验收 Agent。未 commit、push、部署或触发 CI；未修改日常数据或重启日常服务，worker 后续由主 Agent 重启。

# 阶段 B 返工：授权尝试链与保存事务的并发保护

## 主要改动、关键取舍

- 授权读取时记录输入中可关联事项的快照，模型返回后由 `bind` 在现有 `lease` 持锁事务内比较。授权期间新增或改动尝试时返回冲突，旧授权不覆盖该事项；冲突不写成永久语义拒绝屏障，后续正常调用仍可重新核对完整尝试链。
- `authorize_intent` 把本次成功绑定的事项 ID 和快照摘要写入调用私有的 `binding`，由 `operations._execute` 原样带入最终持锁业务事务。在任何保存／复用回执之前重新比较该快照，变更则拒绝本次写入。实际工作、回执和事项 `receiptId` 继续在同一事务保存，提交后新无效提案沿既有规则分到独立事项。没有将共享 `context.task_item_keys` 或全局标记当作保存授权证明，没有增加模型节点或重试次数。
- 绑定纠正提案之前，将尚无尝试链的首份失败提案保留到 `invalidAttempts`，避免绑定后发生并行追加时丢失原提案。原始工具失败和诊断不被删除，原对象／来源／副本／附件检查不变。

## 涉及文件

- `apps/server/app/agent/actions/task_items.py`：持锁绑定快照比较、最终快照校验助手，以及首份失败提案保留。
- `apps/server/app/agent/actions/intent.py`：读取快照、传递本次调用私有绑定凭据、并发冲突返回。
- `apps/server/app/agent/actions/operations.py`：最终保存事务检查凭据，并使用凭据内事项 ID。
- `tests/server/tasks/test_task_identity_recovery.py`：固化授权等待与绑定后至保存前两个并发窗口，各覆盖独立内容与同一请求纠错；后者验证普通新调用看到完整链并恢复成功。
- 仅追加本实施报告，未改独立验收结论。原计划目录树继续适用，无目录新增、移动或删除。

## 验证

按 S3 身份并发边界处理，检查限定为原事故等价重放（允许保守拒绝写入）、绑定后窗口及直接受影响的正常恢复。沿用 `phase-b-checks/environment.json` 隔离 schema 和 fixture 公司／账号；未迁移日常库、未访问日常工作或旧会话、未调用真实模型。

```sh
.venv-server/bin/python scripts/company/web-acceptance/environment.py exec --metadata artifacts/report-source-validation/phase-b-checks/environment.json -- env -u PAA_MODEL_KEY_FILE .venv-server/bin/python -m pytest -q -s --tb=short tests/server/tasks/test_task_identity_recovery.py -k 'concurrent_malformed_attempt or multiple_malformed_create_attempts' > artifacts/report-source-validation/phase-b/rework-concurrent-invalid.log 2>&1
.venv-server/bin/python scripts/company/web-acceptance/environment.py exec --metadata artifacts/report-source-validation/phase-b-checks/environment.json -- env -u PAA_MODEL_KEY_FILE .venv-server/bin/python -m pytest -q -s --tb=short tests/server/tasks/test_task_identity_recovery.py -k 'concurrent_malformed_attempt or multiple_malformed_create_attempts' > artifacts/report-source-validation/phase-b/rework-concurrent-invalid-preserved.log 2>&1
git diff --check -- apps/server/app/agent/actions/task_items.py apps/server/app/agent/actions/intent.py apps/server/app/agent/actions/operations.py tests/server/tasks/test_task_identity_recovery.py specs/spec-079-report-source-validation/implementation.md
```

首次 **6 passed, 32 deselected in 3.14s**。读取原始证据发现绑定后追加会以正确提案替代首份错误提案；补充原提案保留和准确链内容断言后，同组受影响检查 **6 passed, 32 deselected in 3.13s**。没有重跑未受影响的来源／副本／附件矩阵。

最终日志保存实际授权所见事项、并发追加后的完整尝试链、拒绝结果和持久化反馈。两个窗口都没有新增工作或业务回执，两个原始参数失败继续保留，最终为 blocked；同一请求经普通新调用重新授权后保存成功并 completed。显式／省略最终事项 ID 的原串行两次错误恢复均通过。diff 检查通过；这些 Python 文件不在项目 Prettier 覆盖范围，未执行全仓格式化、测试、build、lint 或 typecheck。

## 已知限制、待确认事项

以上使用受控授权响应和真实隔离数据库验证事务边界，不证明真实模型总能判断语义关系。未增加真实模型采样，已记录的 high 授权 `invalid_response` 原因未定及既有有界重试恢复限制不变。未改报告业务、模型 prompt 语气或 UI，未重启日常服务，未 commit、push、部署或触发 CI；等待新的独立验收 Agent。

## 交付检查

新的独立验收已给出本次阶段 B 系统实现 PASS，详见 [验收记录](acceptance.md)。随后仅将既有 `test_tool_failure_contract.py` 的授权包装函数同步为接收并转发本次调用的 `binding`，没有修改业务逻辑或降低断言。单独执行 `test_business_step_saved_during_authorization_has_same_terminal_contract`：**1 passed in 1.75s**，验证另一个请求先占用同一步骤时仍返回原有不可重试冲突；未重复其他已通过检查。
