# Acceptance

## Result

**FAIL**。实际执行覆盖了主要流程，但必需入口存在失败、阻断和证据缺口，不能称为完整回归通过。此结论不要求把模型失败重跑到绿，也不授权修复产品。

被测提交为 `ade2d904759e29720b04f48fc1d680e8a0afb746`，范围为 Spec 中的 `0ec9e229..ade2d904`。独立验收未修改业务代码、未调用模型、未重跑测试套件、未清理资源。检查了新增测试脚本、单条断言诊断变更、覆盖索引、原始请求／回复／轨迹、数据库读回、下载文件及代表截图。验收文档本身按 S0 检查。

下文证据路径均相对 `artifacts/recent-changes-regression/`；`journal.jsonl#N` 表示该日志的 `index=N`，不是 Markdown 行号。过程与原始失败保留在该目录，私有环境、凭据和 SQL 备份不得公开。

## Spec Coverage

实施覆盖表原记 8 个功能 PASS、12 个 FAIL，77 个子项中 60 PASS、13 FAIL、4 BLOCKED。独立核对发现部分 PASS 声明超出证据，以下是验收结论；不能直接用原计数宣称通过率。

| 范围 | 独立结果 | 已验证与限制 |
| --- | --- | --- |
| F01 登录与隔离 | FAIL（部分未测） | 员工、同公司他人、管理员、另一公司分别登录及旧链接拒绝有证据；但每次 `open` 都新建浏览器 context，没有同一 context 退出／换号后的会话、缓存及错误隔离证据。 |
| F02 卡片 | FAIL（部分未测） | 工作、成果、附件主操作、下载、键盘、375px 移动模拟与尺寸样本成立；没有从真实消息点击周报卡／“查看当前报告”的操作记录，`report-card` 的 PASS 不成立。 |
| F03 创建工作 | PASS | low/high 分别创建一项工作，回执对应实际对象；初始详情与刷新存在。低档成功点击在 `cases/browser/journal.jsonl#7`，#5 是选择器失败。 |
| F04 工作编辑 | FAIL | 正文、清单、属性、材料和两档助手 nextStep 写入成立；无变化保存产生新修订。独立进展增改没有现有 Web 入口，保持 BLOCKED，不能自动定性为新增回归。 |
| F05 历史 | PASS | 实际历史与当前切换、保留旧链接及只读内容成立；旧历史由前置 fixture 提供，实际浏览器 #6 展示 revision 1，#3 返回当前 revision 2。过期写入为独立确定性证据。 |
| F06 附件 | FAIL | 六类资料两档均读到指定数据，七类原件下载哈希一致，PDF 第 2 页桌面／375px 渲染成立；PDF／图片引用仍显示“来源未核实”。 |
| F07 成果／文件 | FAIL | high 文字与 CSV、同 ID 续改、独立 Python XLSX 成立；low 首次导出缺少沙盒配置，未交付可下载文件，后续成功不能覆盖。 |
| F08 提问框 | FAIL（尺寸证据不完整） | 真实单选、两题自定义、前后切换、刷新续接、取消成立；1／5题及1／5选项越界为确定性契约证据。320／390px 仅检查已回答历史，未证明活跃输入／提交控件布局。 |
| F09 决策与读取 | FAIL | 两档明确工作请求、官方网页检索及提问均实际运行；文档引用失败及完整输入缺失限制归因。 |
| F10 恢复与幂等 | FAIL | 刷新等待／回答及若干受控身份、并发检查成立；same_source_copy 重放持续冲突；报告／授权自然失败未恢复到成功。 |
| F11 报告来源 | FAIL | 同名异 ID、无独立进展的正文来源和成功报告可对照；当前周两档助手子任务没有报告正文，不能判状态演变后的输出正确。时间边界另有确定性证据。 |
| F12 四入口 | FAIL | 页面、待办和真实到期调度已成功；助手 low/high 都进入实际报告子任务但没有成功正文。报告专用调用均为 low，未观察到额外报告事实审核节点。 |
| F13 周期 | PASS | 本周、上周及跨月跨年取数／请求／展示相符；空周期返回422，换周期清错；375px操作及320／390px日期控件成立。 |
| F14 候选／提交 | FAIL | 手改保留→候选→采用 revision 4→提交→管理员团队读取成立；low 改写被失败空报告阻断，high 授权输出失败，均未成功改写。 |
| F15 删除重建 | FAIL | 页面删除后新 ID 成功且仅一项有效；助手创建新 ID 后生成失败；被删除报告的可恢复待办状态为 cancelled/report_deleted，Web 没有准备按钮。 |
| F16 日报退出 | PASS | 现有迁移与旧参数／任务／租约／调度拒绝检查通过；可销毁 schema 的备份、实际迁移及恢复逐表一致。浏览器上下文中的旧日报请求为真实 HTTP 410，不能称作已存在日报页面按钮操作。 |
| F17 错误恢复 | FAIL | 工作列表断网错误及联网自动恢复成立；首次离线加载报告 lazy 模块后，联网点击“重新加载页面”仍失败。关闭等组件证据与真实页面证据须分列。 |
| F18 权限／确认 | FAIL | full 写入、high 待确认取消、独立确认后恰好一条工作、重复按钮消失、越权拒绝成立；low 切模式被拒后实际仍为 full；新增证据授权契约检查持续失败。 |
| F19 镜像与依赖 | PASS | API／worker／runner／control 构建、依赖边界、worker Office preflight、真实旧 DOC 与沙盒回执成立；nested Docker runtime 复用已有镜像，不是全部镜像重新构建。 |
| F20 观测 | FAIL | 22条初始消息、97次模型尝试、64次工具派发与41次 worker 开始事件相符；早期缺 system/developer 正文，整次运行没有完整工具 Schema，不能完成纯模型归因。 |

## Tests

复用并核对已有日志，没有重新执行通过项：

- `deterministic-web.log`：5个文件，43项通过。
- `deterministic-server.log`：69通过、5失败。停止本轮 worker 后仅检查原失败子集，`deterministic-server-worker-stopped.log` 为4通过、1失败；这支持竞争干扰解释，但不是整套重新通过。
- `faults/permissions-concurrency-migration.log`：57通过、1失败。`faults/identity-replay.log` 和 `faults/auth-diagnostic.log` 保留两个具体失败的最小诊断，不得合并为全绿。
- 已有定向格式／lint、Web typecheck／build 日志通过。单条测试修改只把 `replay['id']` 改为 `replay.get('id'), replay`，保留 ID 相等要求，没有降低业务断言。
- `faults/migration/result.json` 与 `restore.log`、迁移脚本的逐表行比较共同支持恢复一致；原错误表名造成的脚本失败保留，未当作产品失败。
- 独立核对533个索引文件的存在、字节数／SHA以及覆盖引用，索引哈希均匹配。变更文件映射与实际 Git 范围一致。`manifest.caseSha256` 对应格式化前的 JSON；按原 JSON 序列化可还原匹配，未发现场景语义变更，但应注明散列规范。
- 独立读取七类原件及下载字节、CSV行内容、XLSX100行平方与338350汇总；桌面和移动下载 XLSX 相同。CSV含UTF-8 BOM，按 `utf-8-sig` 读取正常。此检查验证文件本身，不仅复述 `file-validation.json`。
- 检视桌面PDF第2页、375pxPDF第2页、375px活跃两题框、320px周期选择截图。手机证据是 `isMobile/hasTouch` 的浏览器模拟，没有宣称真实手机设备验收。

真实模型请求使用 `deepseek-v4.1-flash`：provider轨迹中41次 reasoning low、31次 high、25次 `enable_thinking=false`；7次报告专用请求均为 low。97次是所有节点和有限重试的尝试总数，22条才是初始用户消息，不能混称97个独立样本。没有相同输入对照基线，不作普遍提速判断。

## Issues

### 产品行为失败

1. **无变化保存制造修订**：`cases/browser/journal.jsonl#10–12` 只打开编辑器并保存，revision 1→2，历史显示“工作内容未变化”；独立读回包含新增空段落和属性规范化。记录为用户未改正文但产生修订，不能说原始 JSON 完全相同。
2. **删除后的可恢复待办无入口**：`cases/reports2/journal.jsonl#74、#77` 及 `readback-final.json` 中 `7d1d582d-999d-4270-aef9-7d6cc6d06d99` 为 cancelled/report_deleted。`ReportObligations.tsx` 对 cancelled 不展示准备按钮；未实际重建，不能用后端恢复测试替代。
3. **离线首次加载报告页无法由页面按钮恢复**：`cases/browser2/journal.jsonl#75、#78–80` 和 console 记录表明恢复网络后仍为模块加载失败。这是在 Vite 开发服务观察到的产品前端恢复问题，尚未证明生产构建部署同样失败。工作列表自动恢复是另一条成功路径。

### 未决失败与环境限制

- **回执重放**：`faults/identity-replay.log` 的 same_source_copy 返回 conflict、无 ID；独立无 worker 环境仍复现。须先确认旧回执复用契约，不把 KeyError 修成诊断后称修复完成。
- **授权新证据**：`faults/auth-diagnostic.log` 首次 allowed，新增证据后返回“事项尝试已变化”。测试期待允许，当前实现拒绝；产品／测试契约未决，不能归咎模型。
- **来源引用**：low/high 六文件答案中 PDF第2页3600、图片37均正确，但最终引用未核实。缺完整早期指令和工具 Schema，不能确认是模型语义错误或上游装配缺陷。
- **报告与授权输出失败**：low/high 助手报告子任务以及重建子任务输出为空／length，high改写授权达到4次 invalid_response 上限。`readback-final.json`、`failed-jobs.json`、相应 job trace 支持失败；缺失输入证据使归因受限，不自动标为纯模型错误。
- **low文件与模式**：首次导出时隔离环境未配置沙盒；low确认场景切换被忙会话拒绝后，以实际 full 执行并产生工作。两者首试保留，不能用后续独立沙盒／high确认样本覆盖。

### 测试证据需要修正

- **消息周报卡未测**：F02 `report-card` 标为 PASS，但所有 journal 中没有从消息点击该卡或“查看当前报告”；直接 `goto /reports/...`、报告列表和团队页均不是该入口。应先改为 NOT_RUN。
- **同一浏览器换号未测**：F01现有他人拒绝有效，但 `run.mjs:open` 先关闭 context；不能证明同一前端实例中错误／缓存不会跨账号残留。拆出该子项为 NOT_RUN。
- **问题框尺寸声明过宽**：F08的320／390截图是已回答历史，不含活跃输入／前后题／提交控件；“pending five-question visual is component-only”也不符合所引测试，现有 DOM 测试是3题，5题为后端契约。保留已通过的交互及契约项，单列未覆盖布局。
- **引用错误**：F03成功点击使用 `cases/browser/journal.jsonl#7`，不是#5；F12页面跨年生成使用 `cases/reports/journal.jsonl#20` 及 network 中 `cb2a3805-c608-484c-8d31-e16784ee58c7`，#28是空周期422；F15页面实际确认删除是 `cases/reports2/journal.jsonl#51`，#49仅打开确认框。

## Regression Risks

实际落库证据支持：候选报告 `6b792848-55ae-402c-a16d-465958aebbc8` 采用并提交第4版；管理员实际读取该提交快照；成果 `f3958441-2221-4e37-846b-594fd2785a98` 保持同 ID 修订到2；沙盒执行 `ddde85e3-531b-4ab6-b2ed-cf220b6a234b` 成功并产生可下载 XLSX。它们不能推导其他失败入口通过。

当前清理未执行。schema清理验证本地测试数据库、精确 search_path 和 marker；进程验证PID完整命令；Redis验证容器ID后使用 `docker rm -f`；镜像验证ID并避免外部容器使用，不执行镜像force/prune。**compose `down -v` 目前只依赖项目名，未对本轮容器、网络及卷逐项预检，不能描述为已逐资源验证归属。** 这是清理前安全核对缺口，不是已经误删的证据。

## Required Rework

测试与证据修正可在既有授权内完成，产品修复由用户决定：

1. 更正上述覆盖状态、证据引用和散列规范；保留原始首次结果，不改写失败为成功。
2. 若补全仍可执行的真实入口，只对现存消息周报卡做点击／返回、URL与只读API核对；同一浏览器退出并登录另一合成账号，验证旧链接拒绝和旧错误／内容清除。无需新模型调用，不重跑已有业务生成。
3. 活跃问题框320／390布局只在已有合法待答对象可复用时补浏览器证据；否则明确 NOT_RUN。可用确定性组件补充布局证据，但须标明证据类型，不能冒充真实模型页面流程；不重发已回答／已取消首试。
4. 清理前新增或执行只读 compose归属预检：核对实际容器ID／项目和service标签、镜像ID、挂载卷、卷／网络标签与本轮资源清单，异常时先停止全部清理；保留结果后由主Agent清理本轮资源。不要执行生产或日常资源操作。
5. 产品修复需求分别交用户决定：无变化保存、待办重建入口、离线模块恢复；回执与授权失败先确认契约。模型相关不补提示、不加审核节点、不提高重试预算，不为全绿追加采样。

完成上述证据修正后仍须保留整体 FAIL，除非必需失败已按新授权解决并获得新的对应验证，或用户明确接受剩余问题。清理完成结果由主Agent追加，不伪称已完成。

## 增量独立验收

**FAIL（整体）**。首次 Required Rework 1–4 的测试与证据返工已满足；这不改变产品流程失败、未覆盖项和归因缺口。此次由新的独立验收 Agent 审查 `rework-report.json`、返工后的浏览器驱动与清理脚本、原始及新增证据；没有修改业务或测试代码，没有重跑模型、业务流程或既有测试套件，没有执行清理。

### 返工核对

| 返工项 | 结果 | 本轮独立核对 |
| --- | --- | --- |
| 覆盖、引用与散列 | 满足 | F03 成功卡片点击为 `cases/browser/journal.jsonl#7`；F12 页面生成是 `cases/reports/journal.jsonl#20`，网络返回任务 `cb2a3805-c608-484c-8d31-e16784ee58c7`；F15 确认删除是 `cases/reports2/journal.jsonl#51`。`manifest.caseSha256` 保留原值，按新增序列化说明可重新计算匹配，`semanticSha256` 也匹配当前场景语义。 |
| 同一浏览器换号 | 满足 | `cases/rework-browser/journal.jsonl#7、#9` 加载 employee 的正文及错误，#11 实际退出、#12 用 realEmployee 登录，#13 显示新账号自己的会话；所有页面快照的 `contextSerial` 均为1，期间没有再次 open／销毁 context。#16、#18 及网络记录证明旧工作／会话为404、仅通用拒绝，旧正文和错误没有串入新账号会话。驱动从私有凭据填入密码，日志命令只保存角色；对10个合成密码值核对，新 journal／network 均未泄露。 |
| 真实消息周报卡 | 满足，限入口 | #20 展示 high 原消息，#21 点击“查看当前报告”，#22 只读 API 和 `readback-rework.json` 均指向 `c2c5433e-78de-429c-9fc4-ea145ffa6cfd`，归属一致、revision 1、四栏空正文、任务 `awaiting_retry`；#23 点击返回原会话。截图与记录一致。这里只补足打开／返回，不代表报告生成成功。low 卡因原报告已删除而无入口，#10 点击失败保留；#1 登录遮挡导致的脚本失败也保留。 |
| 问题框尺寸声明 | 满足修正要求，布局仍未覆盖 | 读回恰有3个交互：2 answered、1 cancelled，无合法待答对象。F08 的320／390px 活跃输入／导航／提交控件为 NOT_RUN；375px 活跃双题及320／390px 历史展示分别保留。5题为服务端契约、DOM交互为3题，未再声称活跃5题视觉通过。 |
| 清理前归属检查 | 满足 | `cleanup.py` 在首次 signal／compose down 前加载并验证3个 schema 的本地测试数据库、精确 search_path 和 marker，预检全部记录 PID 命令、compose 容器完整 ID／项目与服务标签／镜像 ID／精确卷挂载及网络 ID、卷和网络标签与外部引用、Redis ID／名称、镜像 tag→ID。任何预检不符即抛错终止；最后版本的实际只读执行记录为 `cleanup-preflight-rework-final.json` 中 PASS、`applyRequested=false`、`cleanupExecuted=false`。 |

### 首试保留与验证限制

- 以首次索引为基线核对增量：533项中529项字节未变；`coverage.json`、`manifest.json`、`resources.json` 的原快照与旧散列一致，`private/api-sandbox.log` 仅追加，其原始字节前缀散列仍一致。所有原始 case、journal、trace、模型／工具 ledger 未改写。新索引为568项，35个新增文件和4个变更文件的当前字节数／散列均匹配。
- `readback-final.json` 与新读回的工作表差异是原有 `fixtures/legacy-history.json` 前置对象；按 ID 比较更晚的 `readback-legacy.json` 与 `readback-rework.json`，全部业务表内容一致。新增浏览器网络记录共60条，全部 GET（56个200、4个404）；没有重试、生成或其他业务写入。初始消息仍为22／24预算，模型尝试97、工具派发64；没有新增模型请求。
- 复核了 `rework-lint.log` 和最终只读预检证据，未重跑已通过的 ESLint、Web类型／构建或后端套件。文档追加按 S0 检查。没有以复用日志冒充本轮重新执行。
- compose 完整 ID 是返工时补录，非创建时捕获。其创建日志散列与文件时间、日志中的 Created 事件、容器／卷／网络创建时间（差不超过5秒）、原记录镜像 ID 和 compose 挂载计划可相互核对。此证据足以限定本轮清理对象，但不改写其补录性质。

### 剩余问题与清理交接

原产品失败继续保留：无变化保存产生修订、删除后的可恢复待办没有 Web 重建入口、离线首次加载报告模块后页面按钮未恢复；回执重放和新增证据授权的契约尚未确认。low 文件交付、助手报告生成／改写／重建、来源引用及完整模型输入／工具 Schema 缺口仍未解决。F08 活跃320／390px控件仍未测，不能宣称全量通过或纯模型归因完成。

主 Agent 可以使用当前已审查脚本对本轮资源执行清理，执行时必须由 `--apply` 再做全部预检，并使用新的证据文件名；任何不符先停止，不能跳过检查或扩展到日常5174／8000、共享 PostgreSQL或其他项目。Redis 的 `docker rm -f` 仅限重新核对 ID 后的本轮容器；镜像删除核对原 ID 并保留被外部容器使用的镜像，不使用 force／prune。该判断不代表清理已经完成；实际动作、保留资源及结果由主 Agent随后追加。

## 清理与最终状态

主 Agent 在上述独立复核后执行已审查脚本，`cleanup-preflight-apply.json` 再次完整预检 PASS，`cleanup-apply.log` 记录命令退出0。`cleanup-result.json` 核对 Web／API／worker 原进程已停止，5198／8018／6398／8028 均无监听；本轮 compose 容器、Redis、三个卷、网络、三个隔离 schema 及临时媒体目录已清理。日常5174／8000和共享 PostgreSQL服务未操作。

删除6个本轮镜像标签；`spec080-4eba6f5e4965-runtime:dev` 与外部容器 `/paa-company-runtime-1` 使用同一镜像 ID，保护规则保留该标签，未强制删除或清理共享缓存。实际保留原因见 `cleanup-image-results.json`。

原始回复、轨迹、截图、下载文件和私有迁移备份保留。清理删除3份合成账号凭据并更新3份环境元数据，清理日志单独保存；清理前索引另存 `evidence-index.before-cleanup.json`，最终索引注明这些清理差异，不将其误称为首试篡改。

最终覆盖表为7项功能 PASS、13项 FAIL；79个子项中61 PASS、13 FAIL、4 BLOCKED、1 NOT_RUN。这些是不同粒度的覆盖计数，不是模型成功率。**整体仍 FAIL**；没有新增模型采样、业务修复、commit、push或部署。

## 三项产品缺陷的后续修复

`87e2061` 已修复无变化保存产生修订、删除周报后的待办生成入口、首次离线加载报告模块后的页面重载恢复。待办按该周是否存在有效周报提供生成或打开入口；权限、租约和幂等约束保留。

定向后端检查69项、Web检查10项通过；真实 Chromium 接入隔离 API／数据库，完成不改正文保存、删除后从待办重建、离线恢复三条流程。证据见 `artifacts/three-fixes/verification.json`、`browser-results.json` 及对应日志。生成入口验证到新报告和 queued 任务实际落库，没有调用模型，不能据此宣称报告正文生成成功。隔离服务和数据已清理。

以上只关闭对应三项系统缺陷，未重跑已通过检查，也未重新执行完整回归。原整体 FAIL、首试失败、剩余未决及未覆盖项继续保留；前文计数仍表示原回归结果。
