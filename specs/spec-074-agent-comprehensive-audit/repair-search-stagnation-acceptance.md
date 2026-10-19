# 连续无新增搜索反馈独立验收

## Result

**FAIL：计数已进入真实模型输入，但首轮 low 仍长时间探索，并引用了工具明确标为未发现的地址。** 六例首轮已全部完成并清理自有资源；high 较快，不能覆盖 low 的失败。不接受 v6 作为搜索收敛修复。

## 代码与模块检查

- 独立比较 v3 与 v6 冻结产品树，仅 `agent/runtime/tool_progress/service.py` 有差异：[候选补丁](../../artifacts/spec074/20261019-search-stagnation-module/candidate-vs-v3.patch)。相对 v3，增加成功执行的搜索连续无新增 URL／标题／摘要次数，遇到新信息清零；错误、拒绝和其他工具不参与。没有增加硬性次数、判断模型、事务、搜索服务或提示词段落。
- 计数只观察已有证据指纹，不判断相关性或任务完成，不改变原有 `no_progress`、软停滞和任务预算。沿用既有 `webFeedback` 持久回执及固定字段顺序，回放不重新计数，旧记录与作用域重置保留。
- 计数按持有 lease 行锁的**工具完成顺序**更新；同批并发工具的消息仍按调用声明顺序返回。单个回执数字表示该回执完成时的观察，不能把消息列表最后一项当整批最新值。
- [模块首轮](../../artifacts/spec074/20261019-search-stagnation-module/junit.xml)为 **23 项通过，5.028 秒**；[自有测试环境](../../artifacts/spec074/20261019-search-stagnation-module/environment.json)已清理。独立验收没有重复运行检查或新增模型调用。
- 初始冻结快照缺少非 Python 的 `packages/api-contracts/input-rules.json`，API／worker 启动失败，尚未调用模型。补齐运行目录后，Python 源码指纹仍为 `4fcae3da156f25e519274e0ee0b8a06d3f5a1d77f97e28bc63f9edebdb460651`；启动错误保留在[记录](../../artifacts/spec074/20261019-search-chain/after-v6/startup-failure.json)，不算模型重试或产品通过。

## 首轮已确认失败

真实问题：**“请联网查OpenAI和Anthropic各一个官方产品介绍页面，给链接即可。”** 当前 deepseek-v4.1-flash，low，专业人设、自主执行，新员工／会话，通过真实 API＋worker 调用；没有代写答案或重跑选优。

| 版本    | HTTP 发送至观察服务端终态 | 模型请求 | 搜索／抓取 |
| ------- | ------------------------: | -------: | ---------: |
| v2      |                 162.30 秒 |       25 |     33／16 |
| 保留 v3 |                  54.35 秒 |        9 |       8／5 |
| v6 首轮 |             **171.21 秒** |   **22** | **26／12** |

计时取 `measurement.sendToTerminalSeconds`，不含验证读回，不代表浏览器绘制。单次差值不足以归因全部网络或模型波动，但实际多余调用已经否定本候选达到收敛要求。

独立读取[原始结果](../../artifacts/spec074/20261019-search-chain/after-v6/results/L-links-low/result.json)和 `after-v6/trace.jsonl`：

1. worker 开始后 **49.420 秒**已有 ChatGPT Learn `/docs` 的真实产品概述摘要和 Claude 官方页证据，足以各给一个产品链接。此后仍有 **11 次模型请求、12 次搜索及 8 次抓取**，继续约 **120.56 秒**。即使只从最终交付的 Claude `/product/overview` 正文到达时算，98.053 秒后仍有 7 次模型请求、7 次搜索及 5 次抓取，继续约 71.92 秒。
2. 约 **140.42 秒**的实际搜索回执已含 `consecutiveNoNewSearches=5` 和“连续 5 次搜索没有新增来源或摘要”，模型仍继续调用工具。正确投递计数不等于模型及时结束探索。
3. 回复有三个链接和较长抓取过程说明，偏离“各一个，给链接即可”。额外的 `https://chatgpt.com/` 在本轮抓取回执中明确为 `sourceDiscovered=false`、`evidenceLevel=unverified_url`，仍被作为官方产品站交付；这不能由已发现的 Learn 页面证据替代。此处指出依据不足，不断言该真实网站不存在。

首轮可见回复原文：

> 各一个官方产品介绍页：
>
> **OpenAI（ChatGPT）**
>
> - ChatGPT 官方产品站：https://chatgpt.com/
> - ChatGPT 官方介绍/使用文档（ChatGPT Learn）：https://learn.chatgpt.com/docs
>
> **Anthropic（Claude）**
>
> - Claude 官方产品介绍页：https://claude.com/product/overview
>
> 说明一句：Anthropic 那条我已实际读取到页面正文（内容为 Claude 的产品能力与 Free/Pro/Max 计划介绍），可确认是官方介绍页；OpenAI 的 openai.com 域名对我的抓取返回 403、chatgpt.com 抓取超时，所以上面两条 OpenAI 链接是官方域下的地址，但我没能读到正文验证其页面内容，链接有效性以你实际打开为准。

## Required Rework

精确撤回 v6 自有计数和对应测试增量，保留 v3 的来源账本、回放一致性、有限抓取重试及较小契约修正。搜索收敛尚未完全解决，不继续叠加未经效果验证的弱反馈，也不把额外复杂度当成已经修好。

## 六例结果与证据边界

全部为同题 low／high 各一次的首轮真实调用，终态均 completed。独立读取全部[原始结果](../../artifacts/spec074/20261019-search-chain/after-v6/results/)的可见回复及计时，不以单元测试替代模型行为：

| 用例                 |  v2 秒 | v3 秒 |  v6 秒 | v6 模型请求 | v6 搜索／抓取 |
| -------------------- | -----: | ----: | -----: | ----------: | ------------: |
| 官方产品链接 low     | 162.30 | 54.35 | 171.21 |          22 |        26／12 |
| 官方产品链接 high    | 193.27 | 82.94 |  25.74 |           6 |          7／2 |
| Python 指定正文 low  |  12.17 | 22.46 |  14.35 |           4 |          0／2 |
| Python 指定正文 high |  14.32 | 16.38 |  14.36 |           4 |          0／2 |
| 一句话解释蓝天 low   |   3.07 |  4.12 |   3.08 |           1 |          0／0 |
| 一句话解释蓝天 high  |   6.10 |  5.12 |   3.09 |           1 |          0／0 |

- 链接 high 在 worker 开始约 21.119 秒取得两家所需来源，随后只用一次模型收尾，没有额外工具。两条链接均有真实发现依据，但仍附多余的 403 抓取说明。该例连续无新增计数最高仅为 1，不能证明累计反馈促成了提速，或把 low 的长链归为单纯网络波动。
- 两档正文均实际读取指定 Python 文档，原地修改、返回值及稳定性三项核心事实正确，引用真实页面；没有 v3 low 无依据的“当前开发版”表述。两档普通题均一次模型、零工具，一句话回答正确。
- [计数与实际 HTTP 审计](../../artifacts/spec074/20261019-search-chain/after-v6/stagnation-audit.json)独立重建 33 次成功搜索，新增数、连续数、提示文本和精确回执投递均无不符。low 最高连续数为 6，high 为 1；5 个并发批次的完成顺序与 HTTP 消息顺序不同，分别记录，没有误当作计数丢失。真实样本未发生回放，回放只由前述确定性模块检查覆盖。
- [最终链接依据检查](../../artifacts/spec074/20261019-search-chain/after-v6/final-source-support.json)再次确认 low 的 `chatgpt.com/` 没有搜索项、页面链接或已读正文支持；两个有效链接不能替它提供依据。[完整请求重建](../../artifacts/spec074/20261019-search-chain/after-v6/outbound-proof.json)匹配实际 HTTP SHA，未使用旧 worker 或其他候选描述。
- [清理记录](../../artifacts/spec074/20261019-search-chain/after-v6/resource-cleanup.json)确认独占 API／worker、schema、Redis 命名空间、私有目录和凭据已清理，未改日常或生产数据。

独立验收仅新增本报告，没有修改业务／测试、重复检查、调用模型、提交或推送。候选撤回的文件范围由新的独立验收另行确认，不用本报告推定撤回已完成。
