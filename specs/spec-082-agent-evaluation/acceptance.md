# 来源 manifest 绑定纠正：独立验收

## Result

**PASS — 三项离线迁移来源绑定的唯一技术阻塞已关闭。** 本次只验收该项追加纠正；34项来源映射、原始结果／评分／截图和共享机制沿用下方上一独立验收已通过的结论，不重复全量验收。此结论不表示34项业务全部通过，也不构成 human 批准。原 FAIL 及更早历史完整保留。

## 修复证据

- [纠正记录](../../artifacts/agent-eval/spec082-followup-binding-correction-v1/correction.json)明确只纠正旧迁移 manifest 的 `offlineMigration.sourceManifestSha256`，保留旧错误声明 `3f462c16a70502f6b7e781191428db93fe5aa4d23a4a1eec02f2bedc57733b8a` 和旧文件身份。源 manifest 的文件字节 SHA256 为 `6d92a482e25efd3bbecf2b2a96588763ff542bcd8dc67915ebb0f8dfb8b7087c`；canonical digest `95d9e42cb870d99c29e75084ef5acc1e2c88cd7e6ccff37632ae6dd2e4dd2d4d` 与 seal `29e3794e50bfdb8dd2c28141fb89e0ce953f8067b6d9066de56764ea1c51f443` 单列，未混用。
- s0013、s0014、s0019 分别绑定源／有效 result、冻结槽位、原／迁移 case 与 requirements、有效 grade、实际语义模型输入及原文。脚本核对 grade 的证据／requirements 哈希、模型输入中的要求及真实请求上下文，并验证三份 raw 字节相同；没有新模型调用、重新评分或人工签名。
- [新版台账](../../artifacts/agent-eval/spec082-followup-review-v2/ledger.json)及[复核入口](../../artifacts/agent-eval/spec082-followup-review-v2/review.html)可直接找到纠正与历史入口。独立抽核纠正文件字节 SHA256 为 `27341b3d8c8a9e02afa95b78c623f53ec66809e14723ccc450550ef542f6f9b6`，与新版台账一致；源 manifest、旧错误 manifest、旧台账和旧复核包的实际文件哈希也与纠正记录一致。

## 检查范围与结论限制

静态审阅 [check.py](../../artifacts/agent-eval/spec082-followup-binding-correction-v1/check.py)及[已保存 PASS 结果](../../artifacts/agent-eval/spec082-followup-binding-correction-v1/check-result.json)，未重跑该脚本或已通过的机制检查，仅做上述少量只读哈希核对。已保存结果证明执行当时3项绑定与588份文件快照校验通过；588份中包含33份临时 credentials.json，不能将其称为永久必需业务证据。来源／结果／评分及模型输入复核读取落盘产物，不依赖存活数据库或密钥。主 Agent 后续按 ownership 正常删除临时凭证和 schema 不推翻本次结论；原快照脚本会因已清理凭证缺失而不能原样重跑，须区分清理与业务证据损坏，不能为重跑保留密钥。

统计保持34项＝33项新真实槽＋1项旧证据处置：程序33 PASS／1 FAIL，语义32 PASS／2 FAIL，人工34 PENDING，最终2 FAIL／32 INCOMPLETE。两份周报范围疑点与初评矛盾、TXT标题差异、旧s0020多写FAIL均保留；人工仍须自行裁决。

本次仅更新本验收文件，按S0检查新增文档与引用；未修改业务／评测代码，未运行业务测试或模型，未提交、推送、部署或清理环境。没有本次修复的必要返工，验收至此停止。

---

# 上次来源绑定 FAIL 历史（已由上方纠正关闭）

# 34项未完成槽位后续处理：独立验收

## Result

FAIL — 当前唯一发现的必要返工为三项离线评分迁移的来源 manifest 哈希绑定错误；不是要求业务全绿或人工已经签名。其余本轮机制与保存证据未发现新的阻塞。

## Issues / Required Rework

`artifacts/agent-eval/spec082-followup-offline-fields/manifest.json` 的 `offlineMigration.sourceManifest` 指向 `spec082-followup-33/manifest.json`，但声明的 `sourceManifestSha256` 为 `3f462c16a70502f6b7e781191428db93fe5aa4d23a4a1eec02f2bedc57733b8a`。实际原文件字节 SHA256 为 `6d92a482e25efd3bbecf2b2a96588763ff542bcd8dc67915ebb0f8dfb8b7087c`，评测器 canonical digest 为 `95d9e42cb870d99c29e75084ef5acc1e2c88cd7e6ccff37632ae6dd2e4dd2d4d`，内嵌且验证有效的 seal 为 `29e3794e50bfdb8dd2c28141fb89e0ce953f8067b6d9066de56764ea1c51f443`，均不匹配。原 manifest 与冻结 `plan-33.json` 完全一致；三份 `sourceResults` 与原 raw 的哈希均正确、内容未变。因此不能据此断言原运行被篡改，但不能验收为已可靠绑定原评分规则的迁移。

仅需追加纠正记录，明确采用的哈希口径、正确来源 manifest、原错误迁移声明及有效评分之间的关系，并让复核入口引用该纠正。保留旧 manifest、raw、grade 和错误声明，不覆盖旧证据；无需新业务或模型初评调用。新的独立验收只核对这一来源绑定。

## Coverage / Tests

按 S2 只读核对 diff、定向检查脚本和已保存通过日志；没有重复执行已通过的定向测试、33项业务、24项诊断或全仓检查。独立校验34项来源集合、原报告/原结果/有效结果/评分哈希以及所有引用附件；33个新槽与原来源的 case/model/effort/trial 一一对应，结果数量为33。核对最终六项证明所绑定源码哈希仍等于当前源码；三项离线迁移的 raw 与新运行原件完全一致。检查 `run --slots` 保留冻结分母并跳过已开始槽。未修改业务或评测代码、未提交/推送/部署、未清理环境。

403原快照保留，零写结论来自主表及子表提交账本；缺capture及实际写入不能PASS。列表DTO缺content使用匹配revision的完整旧提交，逐提交越权恢复反例仍FAIL，缺初态/中间内容仍不能证明授权。异步报告仅豁免绑定目标的一次revision+1完成，额外create/delete和缺child capture的定向证据保留。上述通过结论来自源码审阅与保存的正反例，不冒充本验收重新执行。

## 业务结果与人工事项

台账的34项分母、33次新业务加1项旧证据处置及保存等级统计可核对：程序33 PASS/1 FAIL，模型初评32 PASS/2 FAIL，人工34 PENDING，最终2 FAIL/32 INCOMPLETE；三项迁移的来源说明须先完成上述纠正。原HTTP s0020保留原子create契约、实际create后update的正向多写证据，不能因旧capture不全免除FAIL。原4个provider FAIL未混入此范围。

两份周报均含旧fixture与新工作；复核包同时突出low/high的范围疑点及原初评一PASS一FAIL、后次均PASS的矛盾，不以后次PASS抹除问题。TXT low请求“发布检查”而实际标题“发布检查备忘录”，保留初评FAIL供人工裁决。所有语义项仍待实际人类确认，本验收不作人工签名。进程50428/50445/50473的命令仍分别指向本次owned API/worker/Web，留给主Agent按ownership收尾。

---

# Acceptance

## 当前 Result

**PASS — 框架有界验收通过，逐 durable commit 授权字段漏判的唯一剩余阻塞已修复。** 本次由新的独立验收 Agent 核对该修复及局部回归；其余五项沿用第二次独立验收已通过的结论，不重复运行。前两次 FAIL 及原反例全部保留于下文。

此结论只表示评测机制通过验收，不表示 Agent 业务质量全部通过，也不是 human 语义批准。原34槽的4 FAIL、30 INCOMPLETE及新增4槽的4 INCOMPLETE保持不变；新增四槽离线模型初评PASS不替代人工门禁。

## 当前 Spec Coverage 与修复证据

- `facts.py::mutations` 按实际主对象 durable commit 顺序，以对象ID维护 content 前态，累积每次提交的变化字段；`status` 先改后恢复仍留在授权核对集合中。真实 insert 才能建立空初态；update 缺初态或中间 content 时整体字段结论降为 INCOMPLETE，后续比较不会跨缺口使用陈旧前态。
- 静态复核确认当前修复继续使用原有 job/capture/transaction/hash 完整性门禁、实际提交次数、成功回执和最终快照交叉检查。WorkItem/Report 共用 content 差异逻辑；本次执行证据是 work 固定轨迹，不宣称新执行了 report 或真实业务流程。
- 已读取 [定向脚本](../../artifacts/agent-eval/spec082-rework-commit-fields/check.py) 和 [完整输入与结果](../../artifacts/agent-eval/spec082-rework-commit-fields/result.json)。脚本保留原反例，合法对照只去除越权status变更并重算提交账本；两个缺证据对照分别删除初态或中间 content。四例均有有效capture覆盖，Update计数均为2、bounds均PASS。

| 固定轨迹                                               | 授权断言结果 | 独立核对                                                    |
| ------------------------------------------------------ | ------------ | ----------------------------------------------------------- |
| 只允许title，两个提交先改status再恢复，回执仅声称title | FAIL         | 两次提交的changed分别为status/title及status，恢复不抵消违规 |
| 两次合法title更新                                      | PASS         | 每次提交仅title变化                                         |
| 缺初态content                                          | INCOMPLETE   | 首次比较缺前态，整体不升级PASS                              |
| 缺首个中间提交content                                  | INCOMPLETE   | 该次及下次比较都缺完整前态                                  |

只读重新计算结果所绑定的SHA256：原反例为 `11d288f0f5d2cb6645e822fae8ce7bea11a32e23dcc3f1066750eb030ff82455`，当前facts.py为 `2e50f8cf9cd7182d4bbb705c5fb74d622a7df26390f31e5a27acb9259c51d234`，均与保存结果一致。原错误PASS产物未覆盖，新结果另存。

## 当前 Tests / Regression Risks / Required Rework

本次仅阅读相关实现、定向脚本及四个已执行结果，并核对源码/原输入hash；没有无故重复定向脚本、24项诊断、38个真实业务槽、模型校准或完整测试/build/lint/typecheck。仅更新本验收文件，按S0检查文档差异；未修改业务代码，未调用模型、提交、推送、部署、重启服务或清理环境。

本次限定范围无剩余框架返工。512项逐来源处置、24项契约/DOM诊断、真实typed-evidence校准、移动B05会话及其他五项修复的覆盖与限制仍以下方第二次验收为准。旧业务raw缺新版capture协议不能补造；原provider失败原因仍未全部确定，所有必需语义项仍待真正human复核。owned环境与凭证由协调Agent按ownership处理，不能把本验收视为已清理。

---

# 第二次验收历史记录（唯一阻塞已由上方修复证据关闭）

## 当时 Result

**FAIL — 副作用授权仍存在一个已复现的错误 PASS 路径，需要有界返工。** 这是框架缺陷，不是要求业务模型全绿或人工签名后才允许交付框架。以下为全新独立验收的当前结论；初验六项 FAIL 原文保留于后文。

## 当时 Spec Coverage

| 初验问题             | 返工复核结果与依据                                                                                                                                                                                                                                                                                                                               |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 首批覆盖与逐来源处置 | 本轮要求已补齐。inventory 共512条：313保留专项、191 obsolete-oracle保留原expected契约及replacementDiagnosticIds、8精确重复。24个显式diagnose适配已有24 PASS产物（23组pytest XML及1组vitest），仅证明契约/DOM。新增gaps四槽保留长文图片和真实web_fetch原始输出；四次离线初评PASS，整体仍4 INCOMPLETE。没有把512条都称为已迁移语义或当前运行PASS。 |
| 异常收尾             | 已修正。bounded_trial异常、超时、外部取消及partial错误均进入收尾并保留落盘结果；cleanup按已知job及message逐一求证，不再以登录失败后的空列表成功。受控真实DB零模型的spec082-rework-cleanup/result.json记录job取消成功及两个账号HTTP错误，没有隐瞒错误。依据静态路径与既有故障探针，不重复执行。                                                   |
| 副作用次数与字段授权 | **部分修正，仍FAIL。** after_commit账本、capture闭合、行hash重算、主对象实际提交计数、直接SQL/rollback降为INCOMPLETE均已存在。受控DB正常创建、漏行拒绝、直接SQL缺覆盖及最终字段差异反例已有证据。但逐提交字段授权未实现，见下述最小反例。                                                                                                        |
| 沙盒结构化状态       | 已修正。按当前turn receipt/job关联company_sandbox_execution，核对executionId、终态和exitCode；不使用succeeded字符串命中。原s0023/s0024离线迁移产物的real-sandbox-execution均PASS，原338350计算证据保留，未重跑沙盒。                                                                                                                             |
| 外部文件及grader指纹 | 已修正。grade/report均调用verify_files，逐下载path/sha256及evidenceFiles重算；browser缺截图hash清单拒绝，旧raw没有补造。grader_source包含共享agent_eval_grading.py。既有修改/删除探针记录PASS；本轮静态确认调用链，不重复运行。                                                                                                                  |
| contract覆盖         | 已修正。expectedCheckIds要求11项完全匹配，遗漏/重复/未知及缺观察/requiredEvidence均INCOMPLETE；report重新核对。独立migration保留source manifest/case/result哈希，原11项实际HTTP/工具拒绝、前后不变及取消证据保留，未覆盖旧raw。                                                                                                                  |

移动端仅采用spec082-rework-mobile-v4：390×844，真实B05旧会话正文、完成/取消/中断可见、composer填写清空、刷新一致及无横向溢出。v1错误首页的历史PASS无效，v2/v3亦不作为通过依据。当前typed-evidence校准的5份真实模型原始输出及usage存在：等价表达/已完成子进展PASS，新增条件/材料遗漏FAIL，缺证据unknown；referenceLabelSource明确不是human approval。

## 当时 Issues / Required Rework

**P1：逐提交发生的越权字段修改会被最终净差异抵消。** `scripts/benchmarks/agent_eval/facts.py` 的 `mutations` 已按 durable commit 统计两次更新，但授权字段仍只合并业务回执changedFields及整轮before/readback的content差异，没有重放各次提交的实际content。

本轮新增零模型、零网络最小反例：初始title=old/status=in_progress，只授权title，允许两次update；第一提交实际title=new/status=done，第二提交status恢复in_progress；两条成功回执均只声称changedFields=[title]。每次提交均含完整事务行及正确hash，capture首尾闭合。实际结果commit_coverage=true、work-bounds=PASS、work-authorized-fields=PASS（changed仅title），但第一次持久提交已经越权，正确结果必须FAIL。

可回算完整输入与结果：`artifacts/agent-eval/spec082-acceptance-v2/transient-unauthorized.json`。这是固定轨迹反例，不宣称真实业务已发生越权，也不是新业务模型调用。

必要返工仅限：依据初态与按顺序实际提交的主对象content/关联修订，逐对象逐提交重放字段变化并逐次检查授权；恢复原值不能消除已发生违规；缺少可核对前态或字段证据时INCOMPLETE。保留现有次数/文件/沙盒/收尾修正，用此反例及合法两次title修改的对照进行最小定向验证。无需新真实模型、重跑34+4槽、重跑24诊断或512历史矩阵。

## 当时 Tests 与结论限制

本轮只追加上述一个离线反例执行，其他已通过且未变检查仅审阅实现与保存证据；未运行全套test/build/lint/typecheck，未调用模型，未提交、推送、部署或清理环境。未改业务代码。

原HTTP 24槽1 FAIL/23 INCOMPLETE、browser 10槽3 FAIL/7 INCOMPLETE仍保留；新增4槽仍INCOMPLETE。原4 FAIL涉及mixedmaterials high与B05 low三次provider_error，根因未全部确定，不在本Spec顺手修产品。没有human批准，Agent复核不能替代人工。旧槽没有新capture协议，不能回填或宣称新观察器已用于旧实测。新版CLI确有已加载trace.py指纹准入；主Agent实时观察服务进程及8018/5198监听已不存在，旧报告“仍运行”只是历史快照。owned schema及凭证由主Agent后续处置，本验收未重启服务。

---

# 初验历史记录（以下结论不代表返工后仍有六个问题）

## Result

FAIL — 框架尚有必要返工。此结论不以业务模型必须全绿、人工必须已经签名或历史512项必须重跑为条件。

业务质量结果另计：HTTP v2 24槽为1 FAIL/23 INCOMPLETE；browser v2 10槽为3 FAIL/7 INCOMPLETE；对象权限contract为1槽11断言PASS。没有human批准，不能将任何Agent复核标为人工验收。原始失败与旧评分继续保留。

## Spec Coverage

已具备本地统一CLI、冻结计划/槽位、隔离账号、实际wire、真实low/high样本、追加评分及human gate、真实离线模型校准、JSON/HTML报告、配对评分配置检查。diff未涉及生产业务实现或CI，新增自检不进入默认pytest搜集。保留旧CLI分流，未重复运行旧付费入口。

抽读HTTP s0001、s0013、s0017、s0022、s0023/s0024及browser s0001、s0004、s0007、s0009：直接回答、周报、注入材料、明确provider失败、沙盒结果338350、确认/取消、问题回答200与刷新证据均实际存在；检查到对应主Agent low/high wire。部分辅助调用没有reasoning_effort，不能将全轨迹所有调用都笼统标成low/high。抽读不是全量语义复核。

## Issues / Required Rework

1. **P1：首批覆盖及迁移处置未完成。** `catalog.json:1`、`inventory.json:4`及实施报告“尚有限制”：仅13个代表任务加1个contract；大部分历史项只有统一的uncovered说明，没有逐项接入/重复/过时/缺证据处置；也没有能力诊断套件。这与Spec §1/§2及首条验收标准有差距。不要重跑512项；按下表登记来源、明确有效断言和真实执行层级，已有证据只作同版本或历史证据，不转成新提交PASS。旧ASR/桌面样本可明确列为非目标，不要求新增相关实测。
2. **P1：异常退出跳过owned任务收尾。** `cancellation.py:64-67`在execute抛错时直接传播；`cli.py:60-61`再变为空turn结果，没有调用cleanup。已用零网络协程异常探针确认cleanup调用0次。接受请求后读取失败/trace处理异常可留下业务任务。统一finally收尾异常、超时、取消路径；保留accepted及部分结果；`cleanup_owned:35-57`的登录/GET失败不能被空outcomes的all()判作cleaned，必须对已知job逐一证明终态或INCOMPLETE。只需离线故障探针和受控owned job，不需业务模型。
3. **P1：可确定副作用只算净变化，不能证明授权/幂等。** `grading.py:51-55`按前后对象集合计数。同轮create后delete、同对象多次update均会抵消或压为一次；授权字段也未逐字段验证。零模型探针中禁止写入、trace含create→delete而最终快照相同，所有hard断言仍PASS。改按实际提交回执/对象修订去重计数，并核验每轮允许字段、取消后完整对象/历史不变；缺提交证据给INCOMPLETE。用固定轨迹反例验证，不重跑已完成业务槽位。
4. **P1：沙盒成功依赖字符串命中。** `grading.py:71-73`只要任一事件JSON含`succeeded`即PASS。探针中run_python结果`status=failed,error="expected succeeded, but failed"`仍判PASS。改为绑定当前task/execution ID的结构化终态及结果；明确failed给FAIL，只有queued/缺终态给INCOMPLETE。以现有s0023/s0024保存证据及固定失败/queued反例离线验证，无需再调用模型或沙盒。
5. **P2：附件证据和评分依赖未闭合校验。** `adapters.py:154`保存evidenceFiles hash，`cli.py:82-89`和`report.py:12-24`只核验result JSON，不核验其引用的下载、截图等文件；重新grade的download断言又读取当前磁盘文件（`grading.py:78-82`）。文件丢失/被改仍可沿用旧PASS或以同一evidenceSha得到不同判断。应对必需文件缺失/哈希变化拒绝或INCOMPLETE，并把实际使用的共享`tests/server/_support/agent/agent_eval_grading.py`纳入grader指纹（目前仅BASE/*.py）。用临时复制的小产物修改/删除探针即可，勿修改原始证据。
6. **P2：contract证据要求被短路。** `grading.py:19-20`直接返回checks，跳过catalog的requiredEvidence和预期断言覆盖；`report.py:23-24`又直接aggregate。现有对象contract的11项实际通过可保留，但框架不能因返回一个PASS就认为所有必需权限/工具/取消检查齐全。声明预期check IDs/证据并核对遗漏、重复与未知ID；最小离线删项反例即可。

### 首批覆盖的有界补齐清单

| 缺口                                                                | 可复用来源和最小处理                                                                                                                                                                              | 是否需要新模型调用                                                                                  |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| 材料长文分页、正文与图片、同名不同ID/旧附件/新版本                  | `document-understanding.py`；`test_document_ranges.py`；`test_document_vision.py`中的pixels、same_content、old_ranges、saved_material测试。登记契约层及真实理解层，不能把像素装配测试称为理解通过 | 契约不需；复用现有专项真实证据并明确历史/缺失，只有未被现有真实证据覆盖的代表理解任务需要有限新槽位 |
| 选定材料保存、清单状态、无变化无新增历史、未授权字段                | `test_work_materials.py`的noop、update_edit_preserves_unmentioned_materials；`test_material_selection_workflow.py`及现有工作样本，接入来源/精确断言                                               | 确定性不需；语义无法从当前证据判断时保持INCOMPLETE                                                  |
| 周报已完成进展与项目状态、无规则手动、空周期、删除再生成、来源变化  | `tests/server/modules/reports/`、`test_work_materials.py`的report来源快照，以及已有周报真实来源。当前local/weekly只有2轮，但catalog仍写第四/第五轮提交删除，须修正过时rubric并另登记缺失场景      | 可离线校正/适配；当前已有真实周报无需重跑                                                           |
| 上下文压缩、改口、故障重试/中断恢复及幂等/租约/并发                 | `tests/server/tasks/test_*recovery.py`、`test_task_retry.py`和既有graph案例；现有B05/B06保留。接入可控故障的contract/replay，不以自然发生provider_error替代恢复断言                               | 默认不需；真实模型续接已有样本不能要求重复                                                          |
| 权限撤销与来源修订                                                  | `test_material_authorization_contract.py`、`test_work_materials.py`的removed_material/report source version；明确ID权限contract只覆盖其已做部分                                                   | 不需新模型                                                                                          |
| 移动端关键交互、失败/完成/刷新可见性                                | 复用browser-cases和当前B05/B06结果，增加移动viewport的确定性UI层适配与结果；失败状态/刷新用固定回复或已有证据，明确层级                                                                           | 可用固定输入，无需重跑低/高矩阵                                                                     |
| 搜索需要/不需要、固定网页与真实联网边界、工具错误恢复、文件修改反例 | 现有web research、deliverables、专用benchmark来源；当前unavailable-web不等于覆盖成功检索。补登记对应反例、证据要求与执行层级                                                                      | 固定网页/工具/文件契约无需；确实缺真实联网集成证据时只新增必要代表槽位                              |

完整盘点可按每个来源的技术契约分类后逐ID标记，不要求逐条运行或进行512次语义模型评审。未具备适配的有效必需场景应补适配；明确不支持或缺环境的场景要有可执行预检/INCOMPLETE结果，不能以统一uncovered文字替代覆盖。

## Tests

仅执行一轮必要离线探针（零模型/零网络/临时目录）：复现沙盒假PASS、净变化抵消假PASS、异常路径cleanup零调用。只读核对最新报告与代表原始样本；没有重复check、全量测试、build、lint、typecheck、付费校准或业务矩阵。文件hash和contract短路问题为静态路径确认，尚未额外执行故障探针。未提交、推送、部署或清理owned环境。

## Regression Risks

human gate目前防止整体轻易PASS，但不能代替程序硬断言；否则人工批准后仍可能放过可确定的错误。修正仅影响离线评测，不应顺手更改业务Agent/prompt。原业务FAIL/INCOMPLETE及旧评分保留；修正评分仅追加受影响版本。必要返工通过后停止，不为追绿扩展采样。
