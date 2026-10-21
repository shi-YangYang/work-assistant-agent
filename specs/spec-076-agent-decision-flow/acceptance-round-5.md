# Acceptance — 写后读取的团队来源路径

## Result

FAIL。新的独立验收 Agent 对冻结 v5 发现一类共享数据域映射遗漏。只读源码及已有证据，只运行一个不访问数据库的最小控制边界探针；未修改业务代码、调用真实模型或重复已通过模块检查。

## Issues

`decision_effects.py` 的报告域只开放个人 `query_reports/query_report_obligations`，遗漏管理员使用的 `query_team_business/read_team_source`。实际支持管理员删除员工报告，但成功删除后按原请求查询剩余团队报告时，即使引用真实删除回执仍返回 `exploration_closed`。个人无 ID 报告查询会拒绝管理员，不能作为替代。

团队目录返回 `objectType/objectId/token/revision`；当前范围扩展只认个人目录 `id/revision`。因此问题是共享“读取工具 → 数据域 → 实际来源”映射不完整，不能只加工具名或单个管理员场景放行。

## Required Rework

- 在受影响工作／报告域内支持团队目录和分页，只允许后续读取真实返回的相应来源 token。
- 不跨域开放、不接受伪造或任意关联 token，原权限与版本检查不变。
- 核对同类实际入口；新增必要边界检查，不重复整套已经通过的模块测试。

## Verified Boundaries

个人工作、报告和成果的查询 → 详情 → 翻页、实际成功版本、终结消费、终止冲突和原始参数防护方向成立。未发现新增独立模型调用或员工／数量／话术特判。

## Real Model Limits

v5 R01 low 23.22 秒、1 次主模型直接提问；high 71.96 秒、2 次主模型，先加载工具再提问。两档均未写入，允许自由填写，但选项预设生成文件且没有明确的追加已有工作选项；low 误写 12 份（实际 11），high 选项暴露步骤数量限制。没有提供方错误或重试、没有宿主休眠证据。

程序边界与模型语义表现分开记录；不能因为问题框出现就认定及时澄清达标。完整回复及阶段耗时见 `artifacts/agent-decision-flow/probe-v5-analysis.{md,json}`。完整矩阵与 Web 流程尚未完成。
