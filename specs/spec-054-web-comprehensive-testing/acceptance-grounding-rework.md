# 输出简写误判修复验收

## Result

**PASS，仅针对本次误判返工。Spec 054 整体仍未全部通过。**

核对器现在保留忠实的输出简写，同时仍能检出冻结的日期及执行结果冲突。原 V03 经一次正常 API 重试恢复交付，不替换[此前首轮的 3 PASS / 2 FAIL / 1 BLOCKED](acceptance-grounding.md)，也不计为首次成功。

版本、证据 SHA 和分项结论见[机器验收结果](../../artifacts/spec054/20261008-grounding/repair-scope/acceptance/results.json)。本次验收未修改业务代码、重跑测试或调用模型。

## Spec Coverage

- 通用判据允许提取相关分支、移除调试标签、调整排版及保持关键条件的最小示例；实际值、顺序、异常、条件、版本和分支冲突仍须报告，没有针对题目关键词放行。
- 核对版本升至 43，版本参与请求摘要；旧版判定失效，当前版本相同输入仍复用缓存。权限、证据归属、一次语义修正预算、模型 low 强度和总期限未改变。
- 三份预先冻结的真实核对回放分别独立检查原句、实际参数及回执；没有把空 `issues`、`verified` 或数据库终态直接当作质量通过。

| 固定回放 | 结果 | 独立核对 |
| --- | --- | --- |
| V03 忠实简写 | PASS | `True / 42 / True False` 分别对应同一 Case A 的取消请求、返回值和任务状态。正文完整保留，未因日志标签或示例写法不同触发修正。 |
| S02 日期冲突 | PASS | 证据 10 的页面发布时间为 9 月 29 日，正文 9 月 28 日为活动报道日期；证据 9 列表亦为 9 月 29 日。核对准确引用并标记旧答案的错误发布日期。 |
| V03 输出冲突 | PASS | 证据 6 的实际代码有 TimeoutError 分支打印，但 stdout 只有 `E: inner returned 42`。核对准确标记旧答案声称实测抛 TimeoutError 的句子。 |

以上只验证核对判据，没有修正正文或重新执行源工具，不能替代完整用户任务成功率。证据：[冻结输入](../../artifacts/spec054/20261008-grounding/repair-scope/inputs-frozen.json)、[真实回放](../../artifacts/spec054/20261008-grounding/repair-scope/judge-only/results.json)。

## Tests

- 实施方执行的最小模块检查 **32 项通过**，包含旧版缓存失效与当前缓存复用；本次验收读取[保存的命令和输出](../../artifacts/spec054/20261008-grounding/repair-scope/controlled-results.json)，未重复执行。与前批用例重叠，不累加成额外 32 个唯一用例。
- 原 V03 的一次正常 API 重试在约 **91.8 秒**交付：Case A 返回 42、Case B 在协程开始前取消而抛 CancelledError，均与已有实测一致，附官方来源。仅新增一次核对；[8 条工具参数与回执前后完全相同](../../artifacts/spec054/20261008-grounding/repair-scope/v03-retry/tool-reuse.json)，未重跑代码或业务操作。
- [重试结果](../../artifacts/spec054/20261008-grounding/repair-scope/v03-retry/result.json)的 `taskOutcome` 为 `completed`，没有剩余事项或待回答交互。内部 `job.state=awaiting_input` 是既有纯答复兼容终态，不将其误记为本轮仍待用户补充。
- [数据库读回](../../artifacts/spec054/20261008-grounding/repair-scope/db-readback.json)：无活动任务，3 项初始工作仍为第 1 版，报告、业务操作、草稿、更新记录均为 0；11 条正式消息的持久来源与 API 一致，沙盒执行仍为原有 3 次。

三份判据回放共 **3 次模型请求，输入 18,349／输出 14,548 Token**；正常重试另有 **1 次请求，输入 5,228／输出 7,037 Token**，均有完整用量。费用未知。此前首轮与旧错修正回放单列保留；不能将本次 4 次成功调用等同于 4 个完整新任务成功。

## Remaining Issues

- Q03 的不可变／可哈希条件遗漏仍未解决；普通知识问答没有本轮工具证据，本次判据修复不提供普遍事实保证。
- S02 完整任务仍有外部检索／域名解析阻塞；固定旧日期错被检出，不代表外部可用性已恢复。
- 旧 V03 的整份答案经一次修正后仍残留取消时机错误，此前 FAIL 保留；本次负例只验证冲突检测，没有重新验收该整份修正。
- 新 V03 的“只有一种”“会破坏隔离语义”等泛化措辞仍不够严谨；G-COMPARE 的核心结论通过，但教学代码含裸异常、末尾口诀限定不足。保留这些质量限制，不为它们追加关键词修补或重跑到绿。

本次假阳性返工无新增必需返工项；上述未解决范围仍阻止对整个 Spec 给出无条件 PASS。

## Cleanup

**PASS。** [主环境清理](../../artifacts/spec054/20261008-grounding/cleanup.json)和[沙盒清理](../../artifacts/spec054/20261008-grounding/sandbox/cleanup.json)已记录：专用 API／worker、两个 schema、PostgreSQL、沙盒容器／卷／网络／临时镜像标签及私密凭据清除，8018／8021／15432 端口释放。没有活动执行或嵌套容器，日常沙盒保持不变，脱敏证据保留。

未 commit／push，未执行远端 CI。
