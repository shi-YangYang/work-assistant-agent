# 本地 Agent 评测机制：实施方案

## 对应 Spec

[需求与验收标准](spec.md)。实施已启动：本地真实业务模型调用和离线模型评审均需实现并验证，不设置费用预算前置条件；仍冻结执行范围、超时及证据。

## 材料评审的证据传递修复

三次复测中的 `mixed-materials` s0001/s0002 已保存真实模型输入，但离线评审只收到回复、状态和断言摘要，缺材料正文而返回unknown。修复共享证据组装，从实际调用记录提取带来源路径的输入上下文，单独标为模型收到的资料，不能冒充公开交付。保留来源身份、版本及原文；不从测试期望补造材料，不传入整段系统提示、工具Schema、私有推理或凭证，缺证据继续待判。

按S2验证受影响的证据提取、类型和绑定，使用保存的真实记录及缺失/无效来源等小范围反例；不运行全套测试或重新执行业务。修复后仅对原s0001/s0002各追加一次真实离线初评，保留旧unknown、原始记录及评分版本。由新的独立验收Agent检查共享机制、证据来源和这两份新评分；人工复核门禁不变。不处理另外发现的正文/进展参数互斥问题，不提交、推送或部署。

```text
scripts/benchmarks/agent_eval/
├── grading.py               [修改] 输入资料证据与公开输出分开组装和引用
└── input_evidence.py        [新增] 从本次真实调用提取文字资料及来源路径
artifacts/agent-eval/spec082-source-evidence-fix/
├── check.py / checks.json   [新增产物] 本地显式定向检查及结果，不进入CI
├── result.json             [新增产物] 原记录绑定与两份追加初评
└── acceptance.json         [新增产物] 独立验收
```

修复已通过[独立验收](../../artifacts/agent-eval/spec082-source-evidence-fix/acceptance.json)。10项定向检查通过；只对两份原记录各追加一次真实离线评分，均引用材料原文与公开回复并判PASS，196份既有产物未变，业务模型新增调用为0。[新旧评分与绑定](../../artifacts/agent-eval/spec082-source-evidence-fix/result.json)保留原unknown；当前正式12槽的程序与离线初评均为12 PASS，人工仍12 PENDING。

## 失败用例的三次独立复测

原6条FAIL对应4组用例和模型档位：`local/mixed-materials` high、`browser/B05` low、`local/authorized-fields` high、`local/download` low。每组在当前冻结版本独立执行3次，共12槽；旧B05 low的3次失败单独保留，不与新版本混算。仅用于观察复现与归因，不修改业务提示或扩大为全矩阵。

- 新建owned环境，每槽使用独立账号、公司和会话；保留相同输入、材料、初始条件、实际模型、effort、超时和评分标准，默认串行。运行前冻结完整计划与源码，运行中不修改。
- 每槽一次完整业务流程及一次离线模型初评；产品内既有重试属于该槽，逐次留痕。成功、失败、超时和评分异常均保留，禁止追加调用追绿。
- 逐槽展示实际回复、工具顺序、耗时、程序断言、离线初评、人工待判与错误诊断；按组展示本次通过次数及原因变化。3次全过只代表本轮未复现，不抹除旧失败，也不证明长期可靠。
- 只保存本次产物和必要结果链接，由新的独立验收Agent检查冻结条件、12槽覆盖和结论依据，不重跑业务或已通过机制检查。核对完成后清理本次owned资源，保留脱敏证据。

本次范围为本文件的运行约定与 `artifacts/agent-eval/spec082-fail-repeat3-*` 下的新增计划、原始证据和汇总；无需修改生产代码或评测源码，不提交、推送或部署。

首次运行因启动漏设 `PAA_EVAL_FULL_INPUT=1` 而暂停。独立验收发现暂停生效前第5槽也已完整执行，实际为5个已执行槽缺实际输入证据、7槽未开始；此前4/8/16的披露错误需追加纠正，不能改写冻结计划与原始记录。修正owned进程采集配置后另建v2的12槽计划，先核对首槽证据完整再继续其余11槽。实际共17次业务执行，额外5次仅由采集缺陷产生，不因业务结果好坏追加试验；v2各组3次单独统计。旧运行前4槽已有初评，第5槽未评分，均保留原样，不再新增调用。

复测与计数纠正已通过独立验收，[结果记录](../../artifacts/agent-eval/spec082-fail-repeat3-env/results.md)链接正式12槽、旧运行及追加纠正。程序12 PASS、离线初评10 PASS/2 unknown，人工12 PENDING；不能称业务最终全通过。本次owned环境已清理，业务源码与评分标准未改。

## 未完成槽位的后续处理

范围固定为 HTTP v2 的 23 个 INCOMPLETE、browser v2 的 7 个 INCOMPLETE，以及 rework-gaps 的 4 个 INCOMPLETE。保留旧报告、原始输入输出、失败和耗时；原 4 个明确 FAIL 不并入这 34 个，不重启历史 512 项矩阵。

- 先核对旧证据和当前断言。旧 HTTP/gaps 缺新版提交观察的闭合记录，旧 browser 缺截图哈希清单，均不能补造为执行时已采集。当前评分器还揭示 authorized-fields high 首轮 create 后 update 的次数问题，需要核对请求是否明确授权了工作进展、工具是否支持单次完成，区分用例假设与业务缺陷。
- 修复确定的评测输入、角色、读回、取消终态、文件绑定或评分契约问题。旧 quote 评分与新类型化 evidence 契约必须区分；有效原证据能离线重评就不重复业务调用。新评分保留输入、原文、解析错误及可用的上游诊断，不吞掉故障原因。
- 缺少执行时证据的槽位，在新 owned 环境按同一用例、真实 low/high 和原重复次数建立有来源映射的新计划。先确认真实入口的采集闭合，再执行其余必需槽位；冻结后不改运行源码。明确为系统或夹具缺陷时修复后只追加受影响槽位，不能无理由重跑到绿。
- 业务与离线模型均真实调用；不增加线上模型审核、prompt 补丁或预算。确认正确输入下的纯模型错误后只记录失败。未知上游故障保留诊断，不假定网络或模型幻觉。
- 为全部 34 项形成逐槽处置和新旧证据链接，分别展示程序断言、离线语义、人工待复核及最终状态。技术项完成不自动满足 human gate，不伪造人工批准。独立验收检查修复与证据；验收后清理本次 owned 环境，保留产物。

本次预计原位修改范围（依实际根因收敛，不默认修改全部文件）：

```text
scripts/benchmarks/agent_eval/
├── adapters.py / grading.py / report.py   [按需修改] 真实读回、评分诊断及未完成原因
├── evidence.py / facts.py                [按需修改] 证据绑定和有效业务事实
├── cases/representative.json             [按需修改] 已确认的过时用例假设
└── checks.py / rework_checks.py          [按需修改] 本地显式定向反例
scripts/company/web-acceptance/agent-audit/
└── browser.mjs / trace.py                [按需修改] 取消、截图和提交采集
specs/spec-082-agent-evaluation/
├── spec.md / plan.md                     [修改] 本次处理边界
├── implementation.md                    [修改] 逐项处置和真实证据入口
└── acceptance.md                        [修改] 新独立验收，保留历史
artifacts/agent-eval/                     [新增产物，不入 Git] 34项台账、冻结计划、新证据和复核材料
```

以上属于评测子系统 S2；只验证实际修改影响的机制和这 34 项必要真实证据，不新增 CI，不运行全仓检查。

## 涉及模块与实施顺序

1. **盘点与冻结目录。** 登记既有 business/persona/task-consistency/work-records、agent-audit、权限/文档/沙盒和 Spec 076～081 样本。逐项核对当前契约及来源，标注过时和重复。将仅在历史产物中的必要样本脱敏迁入 `cases/`，保留原件；全量盘点不等于全量运行。校正当前评分投影与真实卡片的差异。
2. **统一契约与计划。** 定义用例索引、套件、运行计划、试验、断言、人工复核及报告协议。目录引用既有用例，不复制夹具逻辑；新格式采用版本字段和严格验证。先提供 `list`、`plan`，列出能力覆盖、预计调用和必要服务，均不调用模型。
3. **适配现有执行器。** 现有 `agent-evaluation.py` 保留旧参数，新增统一子命令。通过适配调用既有 graph、HTTP、browser、sandbox 运行器；运行器报告实际支持的层级，缺能力返回 INCOMPLETE。复用环境 ownership 校验和现有 trace/SSE 观察，不重写生产 Agent。
4. **证据和运行边界。** 冻结运行目录，校验服务运行源码一致性；所有试验槽位提前登记。完整记录生产内重试、子任务和离线评分调用，不新增费用或Token配额。扩展隔离观察器捕获实际发送输入及失败阶段，仅在评测进程启用。取消时终止本次任务，保留证据并清理自有资源。
5. **评分、复核和报告。** 程序断言先执行，语义采用离线模型初评与人工复核；以独立已标注正/负样本校准。评测输出 JSON 与可离线浏览的 HTML，按能力、模型、试验和失败原因筛选/跳转原始证据；报告不执行回复中携带的 HTML/脚本。人工结果附操作者、证据引用和评分版本，不直接覆盖旧评分。
6. **提供本地使用入口。** 目录校验、评分器自检、真实流程和报告均由本地 CLI 手动执行。新增机制自检放在评测目录，通过 `check` 子命令显式调用，不放入默认 CI 测试搜集范围；不修改 CI 工作流，不新增定时任务。
7. **有限真实验收。** 冻结代表用例与 low/high 槽位、关键三次可靠性采样；按 Spec 的真实链路要求执行。独立验收查看所有失败/未决，以及每个通过能力族的代表原始证据。框架缺陷修复后仅复验受影响部分，Agent已确认纯模型失败停止工程修复并留档。

## 数据流与协议

### 用例与套件

`catalog.json` 存索引及关联模块，`suites.json` 存组合、必需项、重复次数与执行等级。用例主体仍归原文件；跨文件重名用 `命名空间/原ID`。评分期望只交给评测器，不传给被测Agent。

示意字段（设计，不是已存在的 Schema）：

```json
{
  "id": "work/create-preserve-conditions",
  "revision": 1,
  "source": { "file": "cases/work.json", "id": "create-preserve-conditions" },
  "family": "work",
  "split": "development",
  "execution": "real-browser",
  "role": "employee",
  "models": ["configured-low", "configured-high"],
  "assertions": ["one-work-created", "only-authorized-fields", "conditions-preserved"],
  "requiredEvidence": ["model-input", "reply", "tool-results", "database-diff", "browser"]
}
```

不以模型配置别名充当实际配置证据；运行计划解析成 provider/model/parameters/effort 后冻结。用例关联受影响模块，用于选择相关套件，不引入自动意图分类模型。

### 试验结果

每条结果包含 `runId/caseId/caseRevision/modelConfigId/trial/turn`、执行状态、断言清单、证据链接、质量结果、原因类别、耗时与usage。执行状态和质量结果分开：业务任务 succeeded 仍可能质量 FAIL；环境预检失败是未执行，不能伪造模型失败。

人工复核与离线模型评分采用独立记录，绑定证据哈希；有明确失败时整体 FAIL，无明确失败但证据/复核不足时 INCOMPLETE，全部满足才 PASS。结果聚合以冻结计划为分母；重复次数与任务数单列。

### 命令设计

统一入口拟采用：

```text
agent-evaluation.py list --suite <name>
agent-evaluation.py check
agent-evaluation.py plan --suite <name> --config <local-config>
agent-evaluation.py run --plan <frozen-plan> --metadata <owned-environment>
agent-evaluation.py grade --run <run-dir>
agent-evaluation.py review --run <run-dir> --decisions <review-file>
agent-evaluation.py report --run <run-dir>
agent-evaluation.py compare --baseline <run-dir> --candidate <run-dir>
```

所有命令均在本地手动执行；`check` 只运行本地确定性自检，`plan` 只展开和估算；`run` 才能产生业务模型费用，`grade` 支持并默认执行离线模型初评，程序校验先行，缺模型配置不得冒充已完成语义评估；明确选择程序评分模式时列出待人工项。已有 `--suite business --source-user ...` 等旧调用仍可用，但新验收统一走已冻结计划。运行器可使用既有远程模型服务，不要求部署本地模型。

## 拟改造目录

`新增` 为扩展既有业务/测试目录，`修改` 均原位进行；不移动 Agent 治理目录，不创建第二个产品运行框架。

```text
specs/
├── README.md                                  [修改] 登记规格
└── spec-082-agent-evaluation/
    ├── spec.md                                [新增] 需求和验收标准
    ├── plan.md                                [新增] 接入和验证方案
    └── implementation.md                      [新增] 实测证据、限制与交接
scripts/benchmarks/
├── agent-evaluation.py                        [修改] 统一 CLI，兼容旧入口
└── agent_eval/                                [新增] 仅离线评测编排
    ├── cli.py                                 [新增] 本地命令分派、冻结运行与评分版本
    ├── calibration.py                         [新增] 真实离线校准及零调用重放
    ├── cleanup.py                             [新增] 显式owned环境与试验凭证清理
    ├── cancellation.py                        [新增] 本次试验超时、取消和owned任务/子进程清理
    ├── permission_contract.py                 [新增] 显式对象ID的HTTP/工具隔离契约
    ├── inventory.json                         [新增] 512条历史来源逐ID盘点
    ├── contracts.py                           [新增] 严格协议、计划与运行边界
    ├── catalog.json                           [新增] 用例索引/来源/模块映射
    ├── suites.json                            [新增] 回归/诊断/采样配置
    ├── cases/                                 [新增] 脱敏迁入及补缺用例
    ├── adapters.py                            [新增] 复用既有执行器
    ├── evidence.py                            [新增] 冻结、指纹、试验与续跑
    ├── grading.py                             [新增] 断言编排与人工复核协议
    ├── checks.py                              [新增] 本地显式自检，不被CI搜集
    ├── calibration.json                       [新增] 评分器正负/未知样本
    └── report.py                              [新增] JSON/HTML与配对比较
scripts/company/web-acceptance/
├── environment.py                             [按需修改] 既有隔离环境复用
└── agent-audit/
    ├── run.py                                 [修改] 接收冻结计划/统一结果
    ├── launch.py                              [修改] 冻结运行源码及依赖证据
    ├── trace.py                               [按需修改] 证据关联与脱敏
    ├── report.py                              [修改] 提供已有事实摘要
    └── browser.mjs                            [按需修改] 实际UI证据适配
tests/server/_support/agent/
└── agent_eval_grading.py                       [修改] 复用评分、校正可见投影
docs/setup.md                                  [修改] 使用入口和环境要求
artifacts/agent-eval/<run-id>/                   [运行产物，不入Git]
    ├── manifest.json                          冻结计划与指纹
    ├── trials/                                公开轨迹、快照、文件和UI证据
    ├── grades/                                带版本的程序/语义/人工结论
    └── report.{json,html}                      结果、覆盖与对照
```

既有其他 benchmarks、专用用例和测试保持原位，通过本地适配接入；只有出现具体接口不兼容才原位调整并更新此树。CI 工作流不在本 Spec 修改范围内；新增 eval 自检仅通过 `check` 运行，核对默认测试搜集入口不会隐式执行它们，保留现有代码测试。运行产物和实施/独立验收记录仅在实际发生时产生。

## 验证计划

文档阶段 S0：只检查 diff、相对引用、范围和待确认决策，不运行测试。实施阶段按模块风险安排最小必要验证：

| 范围          | 验证要点                                                                                            | 证据                                                 |
| ------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 目录/结果协议 | 重复ID、过时引用、缺预期、模型静默降级、已失败槽位覆盖、源码漂移被拒绝                              | 本地 `check` 定向自检                                |
| 评分和门禁    | 真实成功、假回执、越权、遗漏条件、无依据增条件、子任务失败、等价表达、评分器无效/未知、恶意评分指令 | 固定正负样本；不调用真实模型也能验证程序聚合         |
| 隔离/恢复     | 生产地址拒绝、错误ownership、取消/中断、超时、追加证据、未开始槽位续跑                              | 既有环境与受控故障检查                               |
| 真实接线      | 读取回答、工作、周报、文件下载、提问/确认续接和权限拒绝，low/high配置实际生效                       | 真实输入输出、API/worker/数据库、相关浏览器/文件证据 |
| 旧命令兼容    | 保留旧调用参数及可读结果；历史数据缺证据不自动PASS                                                  | 参数/结果适配检查，复用旧证据                        |
| 速度对照      | 不同输入/模型/评分版本被拒绝，失败保留，样本量透明，费用不明标未知                                  | 固定报告样本；真实run中同步计时，无需另起速度矩阵    |
| 本地执行边界  | CI 无新增 eval 步骤，默认测试入口不会执行新增自检或真实评测                                         | 检查工作流和测试搜集配置，不触发 CI                  |

不为了框架建设重跑所有280项business或80项历史audit。先接入、预览选集，再执行必要真实链路；旧失败可用于评分器校准，不能冒充新Agent实测。代表真实验收中的模型失败仍为FAIL，但只要机制正确捕获和归因，可独立判定框架实现是否满足Spec；业务缺陷另列，不偷偷降低门槛。

真实评测先冻结计划与超时边界，有限采样完毕后停止。验收 Agent 新建且使用 high，只读审查实施结果和必要证据；不重复已通过且代码未改的检查，不替实施 Agent 修改业务。发现框架缺陷才按返工范围创建新实施/验收 Agent。

## 风险与迁移

- 历史用例可能对应已删除日报、旧版本展示、旧授权字段或过时模型参数：适配到当前契约并记新修订，保留原件和旧结果；不删除有价值的断言。
- 旧评分器对 UI 的投影不必然等于当前页面：用真实浏览器文本校准，不能以隐藏数据补齐用户交付。
- 模型评分可能漏判/误判：默认程序硬判定与人工复核；离线初评必须保存原始回答、引用和未知状态。
- 多层观察器可能漏计重试或增加耗时：复用现有观测，明确计时边界；不把采集开销改善当作产品提速。
- 跨轮数据、共享内存或测试库加密配置可能互相污染：复用隔离manifest、默认串行、禁止并行运行会冲突的旧套件。
- 无业务数据库 migration；不改线上 Schema/API，不迁移用户数据。新机制出问题可停止新CLI，原测试入口仍保留。

## 交付与停止条件

交付可执行目录和统一CLI、当前有效用例/能力覆盖、必要真实流程证据、框架独立验收和Agent实际质量结果。必须分别列出通过、失败、未执行/待判及适用提交。范围完成且相称检查通过后停止，不追加完整矩阵、不自动提交/推送/部署。

## 返工后的实际增补目录

```text
scripts/benchmarks/agent_eval/
├── cancellation.py          [修改] 所有异常路径收尾及partial恢复
├── facts.py                 [新增] durable副作用、结构化沙盒、contract覆盖
├── evidence.py              [修改] 文件SHA校验及共享grader指纹
├── grading.py / report.py   [修改] 严格事实与附件证据门禁
├── cli.py                   [修改] diagnose与grade证据绑定
├── adapters.py / contracts.py [修改] 图像二进制材料冻结与执行
├── permission_contract.py   [修改] 接收回执及必需证据类别
├── diagnostics.py / diagnostics.json [新增] 24个精准现有节点适配
├── rework_checks.py         [新增] 仅显式运行的缺陷反例
├── mobile.mjs               [新增] 已有真实会话窄视口只读交互
├── inventory.json           [修改] 512项原契约、逐ID处置和重复关联
├── catalog.json / suites.json [修改] contract必需ID、weekly rubric修正、gaps套件
└── cases/
    ├── representative.json [修改] 每轮明确字段授权
    ├── gaps.json           [新增] 长文图片理解及真实联网各low/high
    └── materials/
        ├── long.txt        [新增] 2600段固定材料，末尾预算/批次
        └── chart.png       [新增] 固定红蓝柱形图数值
```

诊断契约、真实业务模型、离线模型初评、人工复核各层独立记账。当前真实4槽仅补代表缺口，不重启原矩阵。具体命令、证据与尚未完成的历史oracle迁移边界见implementation报告；不修改原始失败，不把完整提交观察缺失升级成PASS。

提交观察增补（均本地eval范围）：`agent-audit/trace.py` 修改真实SQL提交账本/capture闭合及非ORM写入缺口检测；`agent_eval/facts.py` 修改账本hash验证、实际主对象提交计数和完整字段差异；`agent_eval/capture_check.py` 新增零模型owned DB验证入口；`agent_eval/cli.py` 修改已加载observer指纹准入。历史raw不升级为新协议。
