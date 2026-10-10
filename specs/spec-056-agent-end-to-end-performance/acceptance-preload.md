# 紧邻业务回执预载独立验收

## Result

**PASS — 仅限本次紧邻业务回执工具定义预载代码范围。**

验收范围为 `catalog.py`、`context_store.py` 与 `test_tool_receipt_preload.py`。独立审查当前源码、相关依赖和既有测试证据，三文件 SHA256 与[实施结果](../../artifacts/spec056/receipt-preload/implementation-result.json)一致。未修改业务或测试代码，未调用真实模型，未重复运行已通过检查。

此结论不是整个 Spec056 的性能验收：受控对照证明少一次工具发现轮，不能证明真实端到端耗时降低 20%。真实基准仅待补充 max 工作创建→修改两轮，不恢复已停止的大矩阵。

## Spec Coverage

按当前 [Spec](spec.md)、[Plan](plan.md)、[测试矩阵](test-matrix.md)及[实施报告](../../artifacts/spec056/receipt-preload/implementation.md)验收。一般知识、逻辑和写作字数偏差按最新范围仅记录观察，不作为本次返工条件；完整传输、真实成果、权限和幂等边界继续保留。

| 要求                       | 审查结果                                                                                                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 仅紧邻上一用户回合         | `previousMessageId` 从过滤前的同会话来源顺序确定。上一回合普通、失效或被删除时不回溯寻找更早业务。                                                                        |
| 真实直接回执               | 上一消息私有 `toolReceiptIds` 与当前服务端复核后的 `currentActions` 取交集；历史继承卡和文字伪造均不能触发预载。仅成功回执及被实际报告子任务接受的 running 回执符合条件。 |
| 失败与确认边界             | 失败卡、待确认卡不预载；报告子任务 queued/running/succeeded 可支持 accepted 回执，失败子任务不可。定义可见不表示报告完成或发布。                                          |
| 用户、公司、会话和角色隔离 | manifest 保持 owner/company/conversation 过滤，来源与动作继续经过现有访问复核，定义继续经过当前 `allowed_tools` 过滤。其他用户、公司、会话和角色变化负例已覆盖。          |
| 不继承版本与授权           | 只预载 work/reports 定义，不复制旧 revision、read_versions 或 authorization_outcomes。工作修改重新读取最新版本，独立授权拒绝仍阻止写入；报告提交仍待 HTTP 确认。          |
| 无关消息不重放、不积累     | 紧邻已有回执时可见定义，但无关普通答复无授权、无写入；该普通回合之后不再继承旧组。当前 UI 工作/文档 seed 与同任务组缓存边界保持原行为。                                   |
| 无新增查询与提示词元数据   | 复用 manifest 已有 Message、BusinessAction、Job 查询；旧缓存 stamp 差异走现有重建。`previousMessageId`、`toolReceiptIds` 不进入模型正文，无 schema/API/依赖变更。         |

## Tests

本项涉及上下文与工具权限交互，沿用实施者已完成的相关子系统定向验证，不扩大到完整项目。正式证据为原始 XML 与机器结果；首次失败保留，不计作成功或隐去。

| 证据                                                                                           | 原始结果            | 最终计数方式                         |
| ---------------------------------------------------------------------------------------------- | ------------------- | ------------------------------------ |
| [initial-tests.xml](../../artifacts/spec056/receipt-preload/initial-tests.xml)                 | 11 passed，5 failed | 保留首批 11 个成功场景。             |
| [tests.xml](../../artifacts/spec056/receipt-preload/tests.xml)                                 | 5 passed            | 仅重试先前失败的 5 个夹具场景。      |
| [initial-authorization.xml](../../artifacts/spec056/receipt-preload/initial-authorization.xml) | 1 failed            | 保留新增授权负例首次失败。           |
| [authorization.xml](../../artifacts/spec056/receipt-preload/authorization.xml)                 | 1 passed            | 修正拒绝访问返回形式断言后的该负例。 |

最终为 **17 个不同场景通过、0 个剩余失败**：新预载测试文件 16 个场景，加既有 current UI seed 1 个场景。首次失败来自 published_revision 初值、pending 卡参数、空报告无 child、拒绝读取返回纯文本等夹具或断言假设；最终断言仍检查真实对象状态和拒绝行为，没有修改业务行为迎合测试。

受控 work 与 reports 对照均为主模型调用 **3→2**，独立授权 **1→1**、真实读取 **1→1**、业务回执 **1→1**。工作旧回执 revision=1，外部变更后读取 revision=2，更新为 revision=3 并保留 blocker；报告在确认前保持未发布。负例还覆盖跨用户读取拒绝、授权拒绝后对象不变、失效/继承/伪造回执、失败报告子任务及无关普通消息清除预载。

未重复执行既有 148 项、SSE 7 项、授权 12 项、usage 4 项及上述已成功场景。实施结果记录 4 个独立测试 schema 均已删除；本次独立验收未创建数据库资源或执行清理。

## Issues

本次代码范围没有发现需返工缺陷。证据引用采用实际存在的 XML；实施报告关于日志存储的误记已由协调 Agent 修正，不影响测试结论。

## Regression Risks

- 尚无真实端到端 20% 改善证据。已有 max 样本先用约 2.49 秒发现工具，再在已可见 work 的调用中约 417 秒超时，不能将该主要停顿归因于 loader。
- [schema-size.json](../../artifacts/spec056/receipt-preload/schema-size.json)仅是当前工具 schema 字符统计，不是 token 或线上请求包测量；本项没有实施提示词去重，也不宣称相应收益。
- 该 PASS 不替代此前交付/传输验收记录或未来真实两轮结果审阅，也不授权扩展基准矩阵。

## Required Rework

本次预载代码无需返工。协调 Agent 可继续唯一已授权的 max 工作创建→修改两轮真实验证；结果返回后另行审阅真实成果、开销与资源清理，整体性能目标继续保持未证实。
