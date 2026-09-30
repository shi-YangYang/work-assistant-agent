# 证据策略验收

## Result

**工程验收 PASS；可选回答质量样本 4/6 达标。**

两条技术问答仍有超出证据的概括，保留失败结果作为可选评测样本，不作为业务功能或发布的阻断项。模型、提示词或工具明显调整时按需复测，不加入日常必跑检查。原 [acceptance.md](acceptance.md)、[rework-acceptance.md](rework-acceptance.md) 及历次失败保留，不把工程通过等同于全部回答准确。

## 最新修复与复测

- 新增 `read_execution`，按公司、用户及会话读取已保存的代码、输出和退出状态，重查来源权限；不连接沙盒、不重新执行。历史目录只注入有界摘要。
- `web_fetch` 支持字面关键词定位及命中分页，返回原文坐标；无命中不冒充正文，保留原网络限制。
- 显式事实核验使用精简输入和有界推理，保留缺失解释的修正能力；不允许据此要求业务操作。输出上限为 4000，普通回答不新增审核，沿用原有纠错次数。
- **93 个后端用例与 33 个纯网页用例通过**。后端首轮 88 通过、4 失败；修正会话 fixture 和精简输入对应断言后，相关 16 项通过。新增格式重试用例先因未开启 fixture 节点重试失败，启用真实节点路径后通过；生产重试策略未改。不累加重复次数。见 [首轮](../../artifacts/spec044/evidence-tools/controlled/pytest.log)、[受影响回归](../../artifacts/spec044/evidence-tools/controlled/corrected.log)、[格式重试首轮](../../artifacts/spec044/evidence-tools/controlled/retry-contract.log)、[修正后](../../artifacts/spec044/evidence-tools/controlled/retry-contract-corrected.log)。
- 使用原配置 `deepseek-v4.1-flash`，固定 3 场景、6 条真实消息，只保留首次结果。**28 次模型调用，390,887 输入／19,972 输出 tokens，用量无缺失**。不是全量重新验收，也不作为严格性能对照。
- 新的独立验收 Agent 只读核对代码、测试日志、实际工具证据与答复，未修改实现或重复调用模型。

| 场景 | 结果 |
| --- | --- |
| S04 两轮、F04 首轮 | PASS：区分清除取消状态与正常返回，保留可能性；未把 `wait()` 纳入统一的超时异常结论。 |
| F04 第二轮 | FAIL：真实无限循环实验有效，但“捕获后不传播、继续跑 → 永远不结束”的概括遗漏有限运行后返回的分支。 |
| 运行时反例首轮 | FAIL：反例正确，但实际搜索达到 15 次命中就停止，答复却称扫描 200 万个；“机制不依赖具体小版本”超出实际 3.12.14 实验依据。显式核验仍未发现这两处问题。 |
| 实验追问 | PASS：两次 `read_execution`、零次 `run_python`，约 16 秒交付，明确实际环境和适用范围。 |

[首次答复](../../artifacts/spec044/evidence-tools/http/first.jsonl)、[完整工具参数与原文](../../artifacts/spec044/evidence-tools/source-evidence.json)、[实际用量](../../artifacts/spec044/evidence-tools/usage.json)、[清理记录](../../artifacts/spec044/evidence-tools/cleanup.json) 已保留。隔离 API、worker、schema 和私有凭证已清理；日常服务未停止或改配置。

以下为前一阶段结果，不用新结果覆盖历史失败。

## Spec Coverage

| 范围 | 结果 |
| --- | --- |
| 策略及运行边界 | 工程检查通过。证据规则用于生成及原有按需核验，没有新增通用审核、API／schema 或权限路径，也没有题目关键词路由。 |
| 普通概念、礼貌改写 | 首轮 PASS。直接交付，无搜索、沙盒、审核或业务写入。部分回答发生协议修复，不能统称一次模型调用。 |
| 明确不运行／不联网 | 首轮及定向复测 PASS。共享列表结果正确，无工具或审核，未声称实测。 |
| 数据计算 | 首轮 PASS。`1299.99 / 1.13 * 0.9` 最终为 `1035.39`，与真实 Decimal 执行输出一致，无业务写入。 |
| 材料条件及压缩改写 | 首轮 PASS。保留重复／首次查询差异、可能性、规模和命中率及未测试范围。输入为用户粘贴文字，不代表真实上传或 `read_document` 流程通过。 |
| S04／F04 | 首轮及定向复测 FAIL。实际原文已读取，答复仍扩大条件或可能性，详见下方。 |
| 运行时反例 | 整体 FAIL。反例及环境有真实回执，后续已恢复交付；但重复实验和跨版本泛化仍有失败证据。 |
| 核验原文协议修复 | 工程回归通过。错误引用可在既有一次 `finish_task` 协议修复中纠正；当前原话的明确核验仍进入原审核，连续错误仍失败，后置校验保留。受控用例确认修复不重执行实验。 |

## Tests

- 首版相关检查 **59 项通过**，见 [unit-tests-rerun.log](../../artifacts/spec044/rework-evidence/unit-tests-rerun.log)；通用规则调整后，相关 **7 项通过**，见 [controlled/tests.log](../../artifacts/spec044/evidence-strategy/controlled/tests.log)。这些是受控流程验证，不能证明真实模型答案准确。
- 最终协议改动的 **42 个独立用例均有通过证据**。首轮 40 通过、2 个受控终态预期失败；按既有异常处理修正为精确的 `failed`、有效收尾错误及不泄漏候选答案后，相关 6 项通过。生产代码没有为测试放宽行为；保留 [首轮日志](../../artifacts/spec044/evidence-strategy/protocol-controlled/tests.log) 和 [修正后日志](../../artifacts/spec044/evidence-strategy/protocol-controlled/corrected-tests.log)，不将重叠执行次数相加。
- 真实模型首批冻结 **8 场景、12 条消息**，5 场景通过、3 场景失败；有具体修改后仅复测 4 场景、7 条消息，再对同会话的失败追问发送 1 次。累计 **20 条消息、110 次模型调用**，实际输入 **1,612,857**／输出 **63,353 tokens**，用量无缺失。不同时间的执行不作为严格性能对照。
- [首批原始结果](../../artifacts/spec044/evidence-strategy/http/first.jsonl)、[定向复测](../../artifacts/spec044/evidence-strategy/refined-http/first.jsonl)、[协议修复后追问](../../artifacts/spec044/evidence-strategy/protocol-followup.json) 均独立保留；[完整证据](../../artifacts/spec044/evidence-strategy/evidence-complete.json) 含实际来源、代码、输出、节点及用量。任务终态不替代语义判定。

## Issues

### S04／F04：来源存在，推断仍越界

S04 首轮再次把“真正抑制”取消与 `uncancel()` 绑定，且称超时没有独立状态；实际原文分别限定于清除取消状态，并提供 `Timeout.expired()`。定向复测虽然改善作用对象描述，仍总述“超时最终表现为 `TimeoutError`”，同一回答又纳入 `asyncio.wait()`；实际读取的中文页 offset 12000 明确该函数超时不引发 `TimeoutError`。未通过不能因措辞部分改善而取消。

F04 定向复测仍从“抑制异常、`cancelled()` 为 False”推出“任务仍在运行”“`asyncio.run()` 就等不到循环自然结束”，遗漏协程捕获后正常返回的分支；又把来源中的 `might misbehave` 写成“连带会使这些结构化并发组件的表现异常”。正常结束与已取消是不同状态，来源的可能性不能支持必然结论。首轮及复测均未通过。

### 运行时反例：交付恢复，证据范围及停止策略仍有缺口

首批两轮均未交付答案：先在多次实验后发生既有核验输出失败，追问又因核验原文不匹配失败。定向复测第一轮交付了 Python 3.12.14 的正确反例，但声称结论“不随版本改变”，超过实际验证范围；首个实验已有反例，此后仍为寻找更简洁案例追加两次实验。

协议修复后，同一追问在 29.91 秒内成功交付，环境和输入范围与 stdout 一致，并明确不能推广所有版本；仍重新执行了一次已有实验。记录为 **3 次模型调用、1 次沙盒执行、1 次协议修复**，不能声称已消除不必要重跑。保留证据没有该次 `finish_task` 错误及修正参数，因此只确认真实追问恢复交付；提前引用守卫的具体纠错路径由受控测试证明。

## Regression Risks

提示规则未形成可靠的语义保证。已通过场景未无故重跑，不能将其首轮结果称为最终版本全量验收；也不能将工具执行成功、审核空问题或任务完成状态解释为答复准确。

本次未执行新的全量测试、浏览器全流程或跨版本实验。历史外部验收限制不变，未查询远端 CI。

## 可选质量改进

后续重点仍是概括不能超出实际分支、统计与版本范围。新工具解决了证据获取与复用缺口，不能保证模型正确解读证据；不继续堆叠具体题目提示或无修改重跑到通过。

[清理记录](../../artifacts/spec044/evidence-strategy/cleanup.json) 确认本轮 schema、私有凭证、自有进程、沙盒容器及卷均已清理；原始脱敏证据保留。验收没有另行操作用户数据库或服务。
