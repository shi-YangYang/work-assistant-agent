# T09-low 首轮修后检索复核

## 结论

修后没有把某个已发出的新网址或新搜索词误判为重复并拒绝；但新增的“搜索没有新增证据”被计入原有全局停滞计数，与 403／网络失败混合累积到 6，触发 `no_progress` 强制收尾。最后一轮工具列表为空，不能归因于模型主动停止，也不能只归因于外部网站。

修前交付两个链接，修后只交付 Claude 一个链接。耗时 170.70 秒 → 72.83 秒是伴随交付缺失的结果，不能算作保持质量的提速成功。

## 工具、预算与停止证据

证据目录：`artifacts/spec074/20261017-repair-comparison/`。修后任务 ID 为 `ff9a6bc4-65f5-4809-9817-4d96dc66a55f`。

- `after/readback.json`：12 条进度记录（含 `load_tools`）全部 `decision=execute`、`executed=true`。单次 `tool_no_progress`／`not_executed` 拒绝 **0 次**，不存在可以列举的“已分派但被新重复保护阻止”的工具。
- `toolProgress.stalled=6`、`stopped=true`；`taskBudget.reason=no_progress`，结束时 `phase=ended`。
- 结束总用量为工具 **11/64**、模型 **8/96**；最终回答调用开始前为模型 **7/96**，剩余时间约 **1,733.05 秒**。并未耗尽常规次数或时间预算。
- `after/trace.jsonl:1608`：最后 `model_attempt_start.offered=[]`。这是 `tool_progress.persist → budget.finalize(no_progress) → ToolBoundary.finish_only` 的强制收尾路径。此前工具一直可用。
- `result.json` 最终 `taskOutcome.state=blocked`、`incompleteTask=true`，`remaining` 明确缺少 OpenAI 官方产品页。未伪称两项都完成。

最后一次实际取得新搜索摘要之后，以下六个结果按完成顺序累积；表中“累计”可由已记录的完成顺序与 `state.complete` 规则确定，最终值同时得到持久化记录验证。

| 调用 | 实际结果 | 停滞累计 | trace 行 |
| --- | --- | --- | --- |
| `web_search`：`site:openai.com ChatGPT` | 正常请求，站点过滤后无结果 | 1 | 1535 |
| `web_fetch`：`https://openai.com/chatgpt/overview/` | 正常访问新 URL，HTTP 403 | 2 | 1553 |
| `web_fetch`：`https://chatgpt.com/` | 正常访问新 URL，4 次网络尝试均失败 | 3 | 1568 |
| `web_search`：`OpenAI Sora official page openai.com` | 正常新搜索词；返回此前同样的 5 个 URL／摘要 | 4 | 1590 |
| `web_search`：`openai.com ChatGPT 介绍 官方页面` | 正常新搜索词；返回此前同样的 5 个 URL／摘要 | 5 | 1593 |
| `web_fetch`：`https://openai.com/index/chatgpt/` | 正常访问新 URL，HTTP 403；随后全局停止 | 6 | 1607 |

因此：已调用的新 URL／query 都被放行，但停止后连尚未尝试的来源、定向搜索与显式刷新也无法再提出或执行。这是全局停止范围过宽，与逐调用重复判断是两件事。

## 第二官方来源是否本来还有机会

`before/search-evidence.json` 与 `before/trace.jsonl:1788,1800` 记录修前后续使用 `chatgpt.com ChatGPT 官方 网页版 介绍`、`domains=["chatgpt.com"]`，实际检索出了新链接 `https://learn.chatgpt.com/docs`。正文随后超时，最后按“已搜索到链接、未读正文”诚实交付，符合只要链接的原请求。

修后没有提出这条查询；它在开始阶段只做过 `domains=["openai.com"]`。全局停止确实提前关闭了进一步改换来源的机会，但不同轮次的搜索与模型都有随机性，不能断言取消停止就必然返回同一链接。本次只读调查没有重跑模型或外部搜索。

## 最小修复建议

保留新证据指纹、已有相同请求复用／拒绝、已拒绝同网址复用和正常任务预算。把**不同检索请求的低增量结果与新网址访问失败**作为软提示，不与重复操作一起触发整个任务的 `finalizing`。相同请求反复提交仍可走已有硬防循环，其他业务写入的保护不改。

实现时不能仅删 `no_progress` 参数：新的搜索 `result_key` 已去掉 query，`result in seen` 同样会累加全局停滞。需要在结果记账边界明确区分“检索没有新增证据”和“重复执行操作”；避免通过提高阈值掩盖作用域问题。必要回归应覆盖当前六步序列后新官方域名搜索仍可执行、相同请求仍受保护，不能仅检查工具数量降低。

本次仅新增这份调查记录，未修改业务代码、未重跑对照。
