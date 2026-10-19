# 搜索工具链精简独立验收

## Result

**FAIL**。阻断项仅为新增搜索增量字段的恢复一致性缺口。真实 AFTER 对照尚未执行，不对回答质量、搜索收敛或耗时改善作结论。

## Scope

审查冻结基线 `7a52b760e1a81cd8e80e5beb8cc971ff55f49671` 上四个产品文件及三个相关测试的差异。搜索服务、调度、重试、预算、权限、安全校验、合法分页与显式刷新实现未改变；研究策略和工具描述合计由 4,022 字符减至 1,700 字符，没有增加模型步骤。

来源处理边界符合预期：保存的搜索摘要仍标记为 `search_snippet`，最多 400 字符；升级到 `page_text` 后删除旧摘要，后续低等级来源不能覆盖正文回执。未发现地址的失败回执不产生可引用来源，失败也不生成正文或自动宣称任务完成。`newEvidenceCount` 表示搜索结果的增量，不是任务完成状态。

## Required Rework

**P2：同一成功搜索在恢复重放时丢失 `newEvidenceCount`，发给模型的工具消息不能保持一致。**

调用链依据：

1. [`middleware.py`](../../apps/server/app/agent/runtime/middleware.py#L136) 先执行 `tool_node`，再调用进度处理 `end()`。
2. [`tool_nodes.py`](../../apps/server/app/agent/runtime/tool_nodes.py#L106) 编码原始 `ToolMessage`；[`node_execution.py`](../../apps/server/app/tasks/nodes/node_execution.py#L223) 持久化该输出，恢复时直接解码复用。
3. [`tool_progress/service.py`](../../apps/server/app/agent/runtime/tool_progress/service.py#L74) 只在非重放时计算新增证据数，事务结束后才向返回消息追加字段；该值没有保存在调用记录中。相同 `progressId` 恢复时 `prior.result` 已存在，计算被跳过，返回原消息便缺少字段。无增量提示也无法原样恢复。
4. [`model.py`](../../apps/server/app/agent/runtime/model.py#L96) 以包含完整消息的请求 payload 计算模型节点身份。因此，只要恢复路径需要重新构造这个工具结果，下一轮请求身份就与首次不同；在已有后续模型回执但图状态需要回放的故障窗口，存在无法复用该回执、增加模型调用的风险。

这是代码级确认的消息不一致与对应恢复风险，未用真实故障复现额外模型调用，不能称已观察到重复收费。旧进度提示已有相似限制，本次新增字段把影响扩大到所有成功搜索，应在交付前处理。

建议最小返工：在现有进度记录的同一事务中保存首次增量数及研究工具提示；相同调用重放时原样复用，不重新计算增量、不重复累计证据或停滞，旧记录缺少字段时保持兼容。无需新增模型、网络调用或数据库事务。

## Tests and Evidence

- 已核对 [`junit.xml`](../../artifacts/spec074/20261019-search-chain-module/junit.xml)：相关模块 84 项通过。
- 已核对 [`review-junit.xml`](../../artifacts/spec074/20261019-search-chain-module/review-junit.xml)：预审调整后恢复与进度模块 34 项通过。
- 描述长度与回执样例见 [`metrics.json`](../../artifacts/spec074/20261019-search-chain-module/metrics.json)。摘要回带属于事实数据，最长失败回执可能比旧版长，不能把描述缩短等同于所有消息都缩短。
- 这些是实施阶段的确定性检查，独立验收没有重复执行。现有检查未覆盖上述新字段在相同调用重放时的消息稳定性，需增加一个直接验证该边界的定向回归。
- 同题 links/body/chat × low/high、真实服务调用、独立账号和冻结源目录已登记于 [`manifest.json`](../../artifacts/spec074/20261019-search-chain/manifest.json) 与 [`cases.json`](../../artifacts/spec074/20261019-search-chain/cases.json)。本次审查时 AFTER 尚未执行，不以模块通过代替性能或质量验收。

验收只新增此报告，没有修改业务源码、运行额外模型或提交／推送。返工后应由新的独立验收 Agent 审查修复和真实对照结果。
