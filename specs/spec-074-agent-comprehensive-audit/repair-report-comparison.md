# 报告回执返工：真实模型定向对照

## 范围与结论

本次新增代码只修改报告操作历史投影与上下文缓存升级：`references.py` 保留有界版本字段 `reportSnapshot`，`context_store.py` 升级旧缓存并避免旧摘要遮蔽新回执。修后源码与上一轮快照仅这两个 Python 文件不同。

原冻结 T29 low/high 各4轮，共8轮真实复验，没有替换问题、强制工具调用或重跑到通过。最终两次提交续跑的真实 HTTP 输入都含当前提交报告的 `reportSnapshot`；版本、发布版本、四个内容字段均与数据库一致。此前“风险为空却声称提交四条风险”的错配本轮未出现。

按原任务完成标准为 **7/8轮、1/2完整用例通过**：low第2轮风险修改被来源核对拒绝，未完成保存；模型诚实说明未保存，最终提交也准确说风险为空。数据/回复一致性 **8/8轮通过**。不能把诚实拒绝写成任务已经完成，也不能据一次复验承诺所有模型错误消失。

## 固定条件

- 同一原始8个输入、工作fixture、low/high、人设及权限；服务/模型配置与原baseline完全一致。
- 新owned schema `spec074_web_bd708ecfab8a`，API8028，独立账号、会话和媒体目录，worker并发1；没有触碰日常服务。
- 14个共享HTTP/模型观察驱动SHA与before/after一致。
- 冻结源码：`/private/var/folders/36/c4plv9vs1bl3ck8hmc7jstjh0000gn/T/spec074-repair-report-v2-yq0yl59p`。
- Python树SHA-256：`247d9671276b7ca38e58e6fbc0666d17fa0f8d0a7d658e4f0b9d84a54db78bfc`。
- 原before/after结果原样保留；本轮位于独立`after-v2/`。本轮采样北京时间 2026-10-17 22:42:12—22:46:41；原 before 为 21:31:10—21:52:45，v1 为 22:04:18—22:21:51，均在同一业务日/周。后续搜索复验已另记日期，未混入此表。

## 耗时与真实模型请求

| 强度       | 原baseline秒 / HTTP | after-v1秒 / HTTP | after-v2秒 / HTTP |
| ---------- | ------------------: | ----------------: | ----------------: |
| R-T29-low  |         184.10 / 30 |       139.56 / 18 |       113.25 / 21 |
| R-T29-high |         161.13 / 24 |       118.14 / 20 |       156.94 / 21 |

两种强度总耗时：原baseline345.23秒 → v1 257.70秒 → v2 **270.19秒**。v2比原baseline短21.74%，比v1长4.85%；原baseline共54次模型HTTP，v1为38次，v2为42次。v1 low没有前两轮真实报告写入，不能把它当同质量性能基准。

high首轮70.67秒比v1的27.76秒明显更长，模型请求7次对5次；这是一次小样本的实际往返差异。代码没有新增固定模型核对入口，两种强度最终提交链路均仍为5次真实模型HTTP。不能把这次数字泛化为稳定提速或稳定降速。

## 逐轮完成度与耗时

| 强度/轮        | before秒 |  v1秒 |  v2秒 | v2 HTTP | v2完成度       | 数据/回复一致性 |
| -------------- | -------: | ----: | ----: | ------: | -------------- | --------------- |
| R-T29-low / 1  |    81.10 | 22.60 | 40.33 |       7 | PASS           | PASS            |
| R-T29-low / 2  |    56.42 | 28.59 | 37.84 |       6 | 未完成风险保存 | PASS            |
| R-T29-low / 3  |    21.70 | 39.88 | 15.39 |       3 | PASS           | PASS            |
| R-T29-low / 4  |    24.88 | 48.49 | 19.69 |       5 | PASS           | PASS            |
| R-T29-high / 1 |    62.69 | 27.76 | 70.67 |       7 | PASS           | PASS            |
| R-T29-high / 2 |    38.87 | 51.19 | 41.97 |       6 | PASS           | PASS            |
| R-T29-high / 3 |    37.87 | 19.46 | 20.48 |       3 | PASS           | PASS            |
| R-T29-high / 4 |    21.70 | 19.73 | 23.82 |       5 | PASS           | PASS            |

## 字段与HTTP证据

| 强度       | 最终报告                               | revision / publishedRevision | 最终风险内容                        | 最终HTTP observationId                 |
| ---------- | -------------------------------------- | ---------------------------- | ----------------------------------- | -------------------------------------- |
| R-T29-high | `6101f8c6-d00e-47b4-b1c1-0ac7853ca657` | 3 / 3                        | 保留第2轮已保存的风险内容，回复一致 | `1cd41ac1-f182-4bb9-b30c-b50cb6a7e4a5` |
| R-T29-low  | `79a0bee8-357f-43b7-8982-2be7cbf74ba7` | 2 / 2                        | 空，回复也明确为空                  | `01fdc79b-ffab-44f5-969a-3ec37a2e21b8` |

这些证据来自 `upstream_http_start.input.messages` 的真实发送内容，属于 assistant 操作历史中投影的回执；不是仅检查服务端准备变量或返回给前端的卡片。`report-inputs.json` 逐请求保留job、observationId、消息SHA、card/snapshot及与实际持久化字段的比较。快照均注明 `source=business_action_receipt`；历史生成版本与当前提交版本分别保留，未伪装为同一份最新可变内容。

## 仍有的限制

- low风险修改未完成：第二次提案仅复述未完成事项，核对模型仍认为不能当作阻碍，要求用户补真实信息。未改授权、未屏蔽拒绝、未把空字段补成虚构风险。
- high允许“未登记截止时间、待跟进”的风险措辞，并明确其推导性质。两种模型输出/核对行为存在波动，本轮没有为追求全绿修改判定规则。
- 原全量对照中的DOC范围断言、长文范围断言、搜索缺少一家来源等结果没有在本次重跑，仍保留原结论；不能用这8轮推算新的全量通过率。

## 证据

- [本轮manifest](../../artifacts/spec074/20261017-repair-comparison/after-v2/manifest.json)
- [逐轮事实及耗时](../../artifacts/spec074/20261017-repair-comparison/after-v2/facts.json)
- [实际HTTP报告字段证据](../../artifacts/spec074/20261017-repair-comparison/after-v2/report-inputs.json)
- [语义与完成度评估](../../artifacts/spec074/20261017-repair-comparison/after-v2/semantic-review.json)
- [业务表读回](../../artifacts/spec074/20261017-repair-comparison/after-v2/readback.json)
- [此前完整对照](repair-comparison.md)

## 资源清理

本轮 API/worker 均已停止，专属 schema、私有环境与凭据目录已删除。无沙盒执行资源；命名空间 Redis 键为0。冻结源码及脱敏证据保留用于复核。见 [清理结果](../../artifacts/spec074/20261017-repair-comparison/after-v2/resource-cleanup.json)。

实施评估已完成，最终验收由独立Agent核对。
