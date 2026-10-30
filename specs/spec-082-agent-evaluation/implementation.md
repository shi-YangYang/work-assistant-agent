# Implementation Report

最终框架独立验收为 PASS，见 [acceptance.md](acceptance.md)。共执行38个真实业务试验槽位，原34槽的4 FAIL/30 INCOMPLETE加新增4 INCOMPLETE不变；本报告后文保留分轮证据及当时限制。

隔离环境已收尾：确认8018/5198无监听，按ownership删除本次 `spec082_web_1652d0c298e2` schema、临时配置及52份试验凭证；共享Docker服务未操作。原始回复、轨迹、下载、截图和报告保留。清理凭据见 [cleanup-completed.json](../../artifacts/agent-eval/spec082-env/cleanup-completed.json)。后续新运行需重新准备隔离环境，不能使用已清理的旧metadata续跑。

实施及本轮有界验证完成，交独立验收；此报告不作最终验收判定。不提交、推送、部署，不改生产 Agent/prompt、Schema 或 CI。

## 改动

- `scripts/benchmarks/agent_eval/` 提供 list/check/plan/run/grade/review/report/compare，以及显式 calibrate/cleanup。旧入口在重依赖导入前分流，原参数保留。
- 目录登记13个代表用例（10个HTTP、3个browser），另有对象权限contract；512条历史来源逐ID登记，不把盘点当成本提交全量执行。原历史54项46通过/8失败未改。
- 冻结源码、完整用例/材料、模型参数和槽位；同一run只能续未开始槽位。独立试验创建不同公司分区和账号，任务内保留多轮；actual wire按providerRequestId关联。程序事实、离线模型初评和human/agent复核分开，评分追加版本并绑定原始证据hash。
- 类型化语义证据面包含id/path/kind/text，区分用户可见回复、实际UI、卡片投影及隐藏持久状态。模型引用证据ID，程序拒绝不存在的ID。human gate没有任何伪造签名。
- owned任务取消、子进程终止与当前试验超时归统一执行器；报告保留所有槽位和明确失败，配对比较核对当前每槽评分规则/模型，拒绝同目录自比。

## 实际结果与证据

本次代码基于dev `efe607eea4634e897cf64115f1307d9265db62ed` 加未提交修改；每轮manifest保存当时源码指纹，不能把后来的评分器修订当作当时业务执行源码。

| 范围               | 实际执行                                                                                                        | 当前结论                                                                           |
| ------------------ | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| HTTP v2            | 10用例、low/high，共24/24槽；权限拒绝每档3次                                                                    | 1 FAIL、23 INCOMPLETE、0 PASS                                                      |
| Browser v2         | 3用例、low/high，共10/10槽；确认/取消每档3次                                                                    | 3 FAIL、7 INCOMPLETE、0 PASS                                                       |
| 对象权限contract   | 知道具体ID的同公司peer/跨公司outsider，HTTP读/改/删、真实get_work_item工具、无泄漏/无修改，以及owned运行job取消 | 统一CLI的1槽、11断言PASS；无模型调用                                               |
| 原quote契约校准    | 9条真实离线模型调用                                                                                             | 9条匹配开发参考标签；只适用旧契约，不是human批准                                   |
| 当前类型化证据校准 | 5条真实离线模型调用                                                                                             | 正确等价、增添条件、已完成子进展、漏存材料、缺证据均匹配参考；5条CLI零调用重放通过 |
| 当前契约代表重评   | 同一保存证据的HTTP直接回答、实际沙盒计算、browser确认/取消各1槽                                                 | 三槽模型初评有效且逐项PASS，human gate仍未满足                                     |

最终主报告：

- [HTTP JSON](../../artifacts/agent-eval/spec082-http-v2/report-20261030T023922022698.json) / [HTML](../../artifacts/agent-eval/spec082-http-v2/report-20261030T023922022698.html)。唯一确定性FAIL为mixed-materials high的任务终态失败。
- [Browser JSON](../../artifacts/agent-eval/spec082-browser-v2/report-20261030T023922109611.json) / [HTML](../../artifacts/agent-eval/spec082-browser-v2/report-20261030T023922109611.html)。B05 low三次均有awaiting_retry；high三次完整确认、取消及读回，B06 low/high均真实提交问题回答200并续接。
- [统一CLI权限contract](../../artifacts/agent-eval/spec082-contract-cli-final/report-20261030T023846824383.json)。工具租约及取消检查用直接seed的受控job，不冒称真实模型任务。
- [当前校准清单](../../artifacts/agent-eval/spec082-calibration-evidence-v2/manifest.json) / [CLI重放](../../artifacts/agent-eval/spec082-calibration-cli-replay/summary.json)。所有标签明确为developer reference，无human签名。

沙盒证据在HTTP `trials/s0023/result.json`、`s0024/result.json`：实际run_python，company_sandbox_execution从queued提交到succeeded，结果338350。TXT下载另属s0015/s0016，通过下载大小/hash和文件解析检查，没有把TXT当沙盒证明。

HTTP与browser重叠运行，共用owned worker，实际worker concurrency=3；观察到最多2个活动job。首个browser发起至worker启动约0.69秒，没有把445秒总耗时归因排队。B05错误有模型节点provider_error、上游HTTP200及请求ID；旧SSE观察未保留错误信封正文，不能进一步断言网络或纯模型语义原因。这批运行不作为串行AB提速证据，价格未知、费用不冒称账单。

## 留存的框架失败及修正

1. 首批观察器仅在旧spec074条件安装。HTTP原20槽完成7槽、第8槽已开始；browser原6槽第1槽已开始。发现后停止调度并通过owned API取消2个活动job，均200；原manifest、未开始分母及[取消证据](../../artifacts/agent-eval/spec082-env/cancellation.json)保留。修复后另建v2运行，不覆盖原件。
2. 初版评分解析异常会丢raw：修复为先存raw/usage，再解析；仅对17个受影响槽新增一版评分。其后确认旧prompt允许actual JSON片段，而parser只认叶子字符串，属于契约歧义，不归咎业务模型。已改类型化证据契约，只做3个代表业务证据重评和5个校准；未重跑全部评分追绿。当前主报告仍混合旧版本与新版本，旧错误保留INCOMPLETE。
3. 对象权限夹具初次缺Idempotency-Key而422；v2第一次把create DTO和detail DTO额外history字段误当修改，只离线回算并保留旧结果。正式CLI现先读完整detail为before，11断言通过。
4. loaded-source校验初次将含password/secrets的路径作为JSON键，被通用脱敏器替换hash；已改path/sha256条目列表。拒绝记录留在contract-cli日志；最终CLI运行实际通过源码及ownership准入。业务API/worker已重启加载这一观察器修订，未增加业务模型调用。

## 本地验证

- `agent-evaluation.py check`：目录、失败优先级、human gate、不可覆盖/篡改、假成功回执、缺证据、HTML转义、超时/取消、owned子进程终止、生产DB地址拒绝、私有推理过滤、无效评分raw/usage留存及类型化证据ID校验通过。
- [配对/复核定向检查](../../artifacts/agent-eval/spec082-env/compare-check.log)：独立schema同profile比较、当前每槽评分不匹配、旧复核绑定失效及自比拒绝通过。
- 格式化仅修改的JSON/材料Markdown；`git diff --check`通过。未运行全量测试/build/lint/typecheck；CI未修改/触发。新增自检在scripts下且须显式调用。

## 使用与环境交接

命令详见[setup](../../docs/setup.md#本地-agent-评测手动)。示例：

```sh
.venv-server/bin/python scripts/benchmarks/agent-evaluation.py list --suite core
.venv-server/bin/python scripts/benchmarks/agent-evaluation.py check
.venv-server/bin/python scripts/benchmarks/agent-evaluation.py calibrate --source-user admin --ids equivalent,added-condition,absent-evidence --output artifacts/agent-eval/new-calibration
.venv-server/bin/python scripts/benchmarks/agent-evaluation.py grade --run <已有运行目录> --slots s0001 --source-user admin
```

为独立验收保留owned环境：`artifacts/agent-eval/spec082-env/metadata.json`，schema `spec082_web_1652d0c298e2`，API `127.0.0.1:8018`、Web `127.0.0.1:5198`。本次进程PID：API25716、worker25720、Web13128（清理前应核对仍为这些命令）。Postgres/Redis及sandbox runtime/control是本次启动的已有本地容器，未删除或重建。

[cleanup预览](../../artifacts/agent-eval/spec082-env/cleanup-preview-final.json)列出原环境及所有试验凭证；未执行apply。清理前停止本次进程，使用CLI cleanup并列全运行目录后显式`--apply`；它调用既有ownership清理器并删除每个trial的credentials.json，不自动停止共享Docker服务。

## 尚有限制，供独立验收判断

- 512条盘点主要标记选入/未覆盖及旧契约需审阅，尚未逐条完成语义去重和过时修订；旧graph/专项长文、图文、ASR等保留原入口，未全部进入统一run适配。不能宣称历史全量适配完成。
- 本批代表性覆盖不等于Spec表中全部边界均有有效反例；移动端、真实provider/工具故障注入及全部并发/租约边界尚未作为新统一目录逐项运行。
- 程序断言检查实际创建数量、每轮最大副作用、确认取消后的状态、下载、实际sandbox及证据完整性；自由正文的所有字段/条件保真仍需语义复核。Browser admin无权读取个人周报，相关不变性断言如实INCOMPLETE。
- 当前五个校准及三个代表业务重评分只证明新证据引用契约可用，不能证明评分模型对所有任务准确。其余旧评分未为美化统计重算；全部必需语义项仍待真正human复核。
- 原始SSE错误正文缺失、首批wire缺失及历史未知成本不可追补；没有伪造字段。当前整体质量为FAIL/INCOMPLETE，框架是否满足完整Spec由新的独立验收决定。

## 必要返工实施结果

本段替代前述框架实现限制中已修正的部分；原业务失败、评分及人工待审仍保留。由新的独立验收 Agent 判断是否满足 Spec，不以本报告代替验收。

- 收尾：异常、外部取消、超时及执行器返回部分错误统一收尾；保留 accepted.jsonl、first.jsonl 与已落盘 turns。清理必须逐个证明已知 job 终态并读取关联 message，登录/GET 失败不再凭空列表成功。`spec082-rework-cleanup/result.json`：新建受控 leased job 经新 cleanup 实际取消；其它账号登录错误保留，拥有者已证明该 job 为 cancelled。该夹具零模型调用。
- 副作用：按成功的 durable `company_business_action` 回执 ID 去重，创建再删除、多次 update 不再折叠为净变化；逐轮 allowedFields 与取消前后完整快照检查。缺完整提交观察、changedFields 或遇未知持久操作均为 INCOMPLETE；worker start/end 不足以证明观察完整，不用于升级 PASS。当前旧真实产物不具备完整提交覆盖声明，相关硬断言继续 INCOMPLETE，不靠重跑追绿。
- 沙盒：绑定当前 receipt/jobId、sandbox execution ID，必须 structured succeeded、关联 result.executionId、exitCode=0。failed 为 FAIL，queued/缺终态为 INCOMPLETE。旧 s0023/s0024 离线结构化检查均 PASS，无新沙盒执行。
- 文件与评分：grade/report 核验 evidenceFiles 每项存在且 SHA256 一致，共享 `agent_eval_grading.py` 纳入 grader_source。缺失/修改文件拒绝评分/报告，不沿用旧 PASS。
- contract：catalog 声明11个 expectedCheckIds，验证遗漏、重复、未知ID、每条观察证据与 requiredEvidence。旧11项观察只在独立追加的 migration 结果中显式映射证据类别；原 manifest/result 未改。
- 覆盖：512项保留每个 sourceId 的原 request/oracle、itemSha256、来源及处置，8个精确重复关联 canonical；313项保留专项，191项明确旧 summary/update oracle 需迁移审阅，未虚称它们已按新框架执行。新增24个显式诊断适配，逐个记录精准 pytest node 或 vitest 命令，23组 Python 契约加1组移动/状态DOM检查均实际 PASS；这些不是模型理解通过。入口 `diagnose --output <new-directory>`，不会进入默认CI。

### 新证据与有限实测

| 产物目录（均位于 artifacts/agent-eval） | 实际证据及结论                                                                                                                                                                                                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `spec082-rework-diagnostics`            | 冻结24项；长文分页、像素装配、同内容不同ID、旧版本、材料保存/noop/字段权限、清单/进展周报、空源、删除再生、来源撤权/修订、上下文、提交后恢复、并发工具、固定网页/工具失败及移动DOM。24项 PASS；参数化节点可包含多个断言。                                                |
| `spec082-rework-probes-final.txt`       | 异常/超时/取消保留partial、登录失败清理INCOMPLETE、create-delete、多update、缺字段/未知操作、沙盒失败/queued、contract遗漏/重复/未知、文件修改/删除及共享grader依赖探针 PASS。                                                                                           |
| `spec082-rework-offline`                | 原manifest/case/result哈希与有效新规则分别留存；2个沙盒、1个权限contract离线迁移结果。不是新业务执行。                                                                                                                                                                   |
| `spec082-rework-gaps`                   | 新冻结4槽：2600段长文+PNG理解、真实官方网页读取，各low/high一次。实际模型输出预算48217/ZX-914/红7蓝3差4；实际web_fetch成功且cacheHit=false，TaskGroup版本3.11及官方链接。4次实际离线模型初评逐项 PASS；总报告4 INCOMPLETE（完整写入观察/human gate未满足），无人工签名。 |
| `spec082-rework-mobile-v4`              | 正确admin账号打开旧B05真实会话，390×844 viewport；既有完成/取消状态与正文、composer点击填写清空、刷新后相同会话、无水平溢出3项 PASS，截图保留；未发送新消息。                                                                                                            |
| `spec082-rework-cleanup`                | 新受控运行job的真实取消结果及accepted；零模型调用，复用已owned账号，不删除共享容器。                                                                                                                                                                                     |

移动v1错误URL显示空首页，其conversation-refresh曾误判PASS，明确废止；v2为错误账号无权限，v3为登录后team路径未纳入等待条件。三份原产物保留，不作为关键交互通过证据。最终v4验证正文包含原请求且刷新一致。真实页面亦保留“暂时无法继续/已取消/已中断”等原状态，没有为了展示统一替换成成功。

新增实测仅4业务模型槽及4离线模型评分，不重跑原34槽、512历史矩阵或已经通过的24项契约。`network-integration-observations.json`保留实际web_fetch的结构化来源/时间/cacheHit与工具结果，不能以模型自述或complete-wire-calls替代联网事实。

### 本地命令及边界

```sh
.venv-server/bin/python scripts/benchmarks/agent-evaluation.py diagnose --output <新的产物目录>
.venv-server/bin/python -m scripts.benchmarks.agent_eval.rework_checks
.venv-server/bin/python scripts/benchmarks/agent-evaluation.py plan --suite gaps --config artifacts/agent-eval/spec082-env/eval-config.json --output <新的计划文件>
.venv-server/bin/python scripts/benchmarks/agent-evaluation.py grade --run artifacts/agent-eval/spec082-rework-gaps --mode model --source-user admin
node scripts/benchmarks/agent_eval/mobile.mjs <旧browser trial目录> <新的产物目录>
```

诊断实际运行使用ownership校验后的同一专用schema环境变量；pytest setup按独立公司隔离。新增CLI完整 `check` 通过。JSON/MJS使用已安装Prettier格式化；Python不在项目Prettier支持范围，未引入新格式器。未运行全量测试/build/lint/typecheck，未触发CI、commit/push/deploy。新增4槽及cleanup环境凭证保留供独立验收，后续清理预览须包含新增run目录；旧预览不是当前完整清单。

仍有明确限制：旧191项oracle分类是逐项原契约留存及迁移审阅标记，不是191项语义改写已完成；diagnose复用精选节点，不等于每个历史ID皆有统一run执行器。完整提交观察尚未添加到真实runner，故授权/副作用证据不足项如实INCOMPLETE。真实模型仍需人类复核。这些限制交独立验收判断，不能把“保守未判”说成全面覆盖或业务PASS。

### 新运行的完整提交观察

上述“新runner尚无完整提交观察”的限制已解决；仅旧38槽仍没有新版观察闭合证据，不回填旧raw。

`trace.py` 为每个实际 worker execution 创建 captureId，after_commit 保存实际 ORM 提交行的 transactionId、行数及内容hash；start/end闭合记录同一账本。评分器重新计算所有提交行hash并核对每个capture首尾；缺行、缺尾、重复/不匹配账本、rollback或未覆盖的直接SQL写入均不能证明完整。SQLAlchemy Engine另检测目标表非ORM flush写入，标unsupported，不通过人工bool声明完整；savepoint不当成最终commit。每轮完整before/readback和已成功回执共同参与授权字段判断，实际content的字段差异也需授权，不能仅信回执changedFields。主对象实际提交亦参与操作计数，不能被缺少business action掩盖。

`spec082-rework-commit-capture/result.json` 是真实专用DB、零模型的受控验证：实际创建WorkItem、WorkRevision、成功BusinessAction后，完整观察+创建计数+字段授权PASS；删除任一保存commit行拒绝完整性；直接SQL更新被识别unsupported；离线把readback加入未授权nextStep会FAIL。可重复入口：

```sh
.venv-server/bin/python -m scripts.benchmarks.agent_eval.capture_check --metadata <owned metadata.json> --output <新的产物目录>
```

新版CLI另校验runtime_start中已加载trace.py指纹；保留的API/worker进程仍是旧observer，下一轮新run需要由owned launch重新启动。未借旧进程宣称新观察器已加载。受控探针直接加载了本次新版observer并实际执行SQL，无需为此重跑业务槽位。

191项现明确标为obsolete-oracle并保留确切旧expected/summary-update契约及replacementDiagnosticIds，8项精确重复含canonical，313项保留专项逐项指向对应契约诊断。replacement是确定性不变量覆盖，不冒称每条业务任务语义等价或已全量改写。原件、历史结论与所有新失败继续保留。

补充证据：`spec082-rework-commit-capture/field-authorization-counterexample.json`固定反例中回执只声称title，但完整前后content的status也变化、仅授权title，实际判FAIL。文件校验亦直接核对每条下载回执path/sha256；必需browser证据没有截图hash清单时拒绝新grade/report，旧已保存报告仍保留历史性质，不能声称旧截图已补绑定。最后定向完整性探针见`spec082-rework-probes-integrity.txt`。

### 逐提交字段授权返工

`facts.py` 的授权判断按 trace 中实际主对象 durable commit 的顺序维护每个对象的 content 前态，逐次累计真实变化字段并保存 transactionId/objectId/revision/changed 证据。WorkItem 与 Report 都使用实际模型的 content 映射；不依赖特定字段名称。后续恢复原值不能抵消前次越权。只有实际 insert 可以从空内容开始，update 缺初态或任一中间 content 缺失均不能证明字段授权完整；缺内容同时使下一次比较前态失效。保留原 capture/事务/hash 校验、提交计数、回执检查和最终读回交叉检查。

按共享评分逻辑 S2，仅运行同一离线定向脚本（零网络、零模型、零数据库）：

```sh
PYTHONPATH=. .venv-server/bin/python artifacts/agent-eval/spec082-rework-commit-fields/check.py
```

原越权后恢复反例的授权结果由错误 PASS 改为 **FAIL**；合法连续两次 title 更新为 **PASS**；缺初态 content、缺首个中间提交 content 均为 **INCOMPLETE**。四个输入均保留完整有效 capture 账本，次数断言仍为两次 Update、PASS。新结果及完整输入在 [result.json](../../artifacts/agent-eval/spec082-rework-commit-fields/result.json)，绑定原反例及本次 facts.py 的 SHA256；原验收反例未修改。

Python 不在项目格式器覆盖范围，未安装格式器。仅检查本次 diff，未重跑统一 check、24项诊断、38个真实槽或离线模型。未提交、推送、部署、重启服务或清理 owned 环境；此处为实施验证，等待新的独立验收。
