# 性能基线：真实模型调用

## 结论与口径

本轮建立冻结版本的基线，没有修改产品，因而没有“优化前后提速”的结论。独占串行样本中，普通短答约 2～4 秒；复杂工作操作最高约 80 秒，搜索和重试能显著放大等待。不能把某一轮的快慢都归因于 low／high，更不能以这些小样本承诺线上延迟。

- 应用 SHA：`26db8f9bb8af64da403696362b158df7a94ebe1a`；文本模型 `deepseek-v4.1-flash`，仅 low／high。
- 8 类任务 × 2 档 × 3 次，共 48 次，每次新账号、新会话、新附件，交错档位，使用相同输入／权限／人设。执行窗口为 2026-10-17 07:45:07.950～07:58:30.301 UTC；核查主、故障轨迹，该窗口无其他测试模型请求竞争。
- 主指标为 `measurement.sendToTerminalSeconds`：HTTP 发送开始到轮询观察到终态，排除发送前上传和终态后的下载／数据读回。轮询存在采样误差，**不是浏览器像素呈现时间**。旧 `turn.seconds` 含额外测试耗时，不用于本表。
- “首正文 SSE”从收到任务回执到观察端收到正文事件；不包含发送受理时间，也不等于上游首 token 或屏幕首字。失败／无正文应留空，不用状态通知代替。
- 每例 `result.json` 保留上传、受理、终态、下载核验的独立测量；`metrics-1.json`、`sse-1.jsonl` 和主 `trace.jsonl` 保留关联证据。没有完整浏览器、解析／渲染、持久化阶段的独立时钟，未观测项不估算，不用相减制造“系统自身耗时”。
- 48 次均为附件首次处理；没有完成同题冷／热读取的耗时配对。历史图文追问验证了相同页图被复用，但不作为热读提速证明。
- 主聊天请求使用对应 low／high；11 次授权核对请求原有配置为 `enable_thinking:false`。报告子任务遵循独立用途配置，不能把聊天选择的档位当成所有内部请求的实际参数。

## 分组结果

每格为“中位数（最小～最大）”，单位秒，每格仅 3 次。全部任务都获得终态，但终态不代表答案和成果每个细节均正确；质量问题单独列在下文。

| 任务 | low | high |
|---|---:|---:|
| 普通问答 | 3.09（2.08～4.15） | 3.09（2.08～3.10） |
| 写作 | 5.15（4.10～9.34） | 4.12（3.09～4.13） |
| 搜索 | 25.51（18.40～28.67） | 26.60（24.52～31.87） |
| 工作操作 | 47.96（28.61～79.69） | 36.77（11.23～69.37） |
| 短文本附件 | 6.15（5.13～7.16） | 6.14（4.12～7.18） |
| 图文附件 | 14.30（13.31～18.42） | 16.34（13.30～17.38） |
| 文件执行 | 11.28（11.27～12.25） | 11.25（10.19～11.28） |
| 多步成果 | 17.57（12.29～29.67） | 21.62（17.50～22.50） |

工作操作的波动明显大于普通短答；当前 n=3 不足以证明 high 比 low 更快。不能将复杂任务耗时与单次直连 API 耗时直接相减，因输入上下文、工具、授权及轮次数不同。

## 48 次原始样本

首正文 SSE 列是“回执后秒数”；总耗时列是“发送后秒数”，二者起点不同。证据目录内各例均有完整结果、读回与 job ID。

| 样本 | 总耗时秒 | 首正文 SSE 秒 | 证据 |
|---|---:|---:|---|
| P-chat-high-1 | 3.102 | 2.321 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-chat-high-1/result.json) |
| P-chat-low-1 | 4.147 | 3.061 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-chat-low-1/result.json) |
| P-chat-high-2 | 2.081 | 1.916 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-chat-high-2/result.json) |
| P-chat-low-2 | 3.087 | 2.971 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-chat-low-2/result.json) |
| P-chat-high-3 | 3.085 | 2.192 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-chat-high-3/result.json) |
| P-chat-low-3 | 2.085 | 1.983 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-chat-low-3/result.json) |
| P-writing-high-1 | 4.117 | 2.923 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-writing-high-1/result.json) |
| P-writing-low-1 | 5.148 | 4.487 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-writing-low-1/result.json) |
| P-writing-high-2 | 4.131 | 2.624 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-writing-high-2/result.json) |
| P-writing-low-2 | 9.337 | 8.024 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-writing-low-2/result.json) |
| P-writing-high-3 | 3.093 | 2.014 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-writing-high-3/result.json) |
| P-writing-low-3 | 4.104 | 2.345 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-writing-low-3/result.json) |
| P-search-high-1 | 26.599 | 17.898 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-search-high-1/result.json) |
| P-search-low-1 | 28.666 | 21.387 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-search-low-1/result.json) |
| P-search-high-2 | 24.517 | 18.202 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-search-high-2/result.json) |
| P-search-low-2 | 18.401 | 12.500 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-search-low-2/result.json) |
| P-search-high-3 | 31.865 | 24.746 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-search-high-3/result.json) |
| P-search-low-3 | 25.508 | 18.010 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-search-low-3/result.json) |
| P-work-high-1 | 11.231 | — | [result](../../artifacts/spec074/20261017-real-audit/performance/P-work-high-1/result.json) |
| P-work-low-1 | 28.609 | 27.551 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-work-low-1/result.json) |
| P-work-high-2 | 36.773 | 34.975 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-work-high-2/result.json) |
| P-work-low-2 | 79.691 | 78.919 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-work-low-2/result.json) |
| P-work-high-3 | 69.375 | 68.201 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-work-high-3/result.json) |
| P-work-low-3 | 47.958 | 47.215 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-work-low-3/result.json) |
| P-text-high-1 | 7.182 | 5.061 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-text-high-1/result.json) |
| P-text-low-1 | 5.127 | 3.353 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-text-low-1/result.json) |
| P-text-high-2 | 4.122 | 2.780 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-text-high-2/result.json) |
| P-text-low-2 | 6.152 | 3.814 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-text-low-2/result.json) |
| P-text-high-3 | 6.144 | 3.726 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-text-high-3/result.json) |
| P-text-low-3 | 7.156 | 4.569 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-text-low-3/result.json) |
| P-visual-high-1 | 13.298 | 11.597 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-visual-high-1/result.json) |
| P-visual-low-1 | 13.307 | 11.609 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-visual-low-1/result.json) |
| P-visual-high-2 | 17.383 | 13.109 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-visual-high-2/result.json) |
| P-visual-low-2 | 18.416 | 17.536 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-visual-low-2/result.json) |
| P-visual-high-3 | 16.335 | 13.503 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-visual-high-3/result.json) |
| P-visual-low-3 | 14.299 | 12.402 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-visual-low-3/result.json) |
| P-execution-high-1 | 10.187 | 8.523 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-execution-high-1/result.json) |
| P-execution-low-1 | 12.247 | 9.727 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-execution-low-1/result.json) |
| P-execution-high-2 | 11.278 | 9.116 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-execution-high-2/result.json) |
| P-execution-low-2 | 11.268 | 8.743 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-execution-low-2/result.json) |
| P-execution-high-3 | 11.248 | 9.483 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-execution-high-3/result.json) |
| P-execution-low-3 | 11.285 | 8.983 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-execution-low-3/result.json) |
| P-multistep-high-1 | 21.616 | 17.693 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-multistep-high-1/result.json) |
| P-multistep-low-1 | 29.665 | 26.511 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-multistep-low-1/result.json) |
| P-multistep-high-2 | 17.497 | 14.559 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-multistep-high-2/result.json) |
| P-multistep-low-2 | 12.287 | 10.517 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-multistep-low-2/result.json) |
| P-multistep-high-3 | 22.499 | 20.682 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-multistep-high-3/result.json) |
| P-multistep-low-3 | 17.565 | 14.946 | [result](../../artifacts/spec074/20261017-real-audit/performance/P-multistep-low-3/result.json) |

## 直连模型对照

相同用户输入：`计算17加26，只给结果，不需要调用工具。` 同服务商、同模型、流式接口，真实上游均返回 200、答案均为 43；每次参数和 request ID 在 [原始记录](../../artifacts/spec074/20261017-real-audit/direct-provider/results.json)及配套轨迹中。

| 强度 | 第 1 次秒 | 第 2 次秒 | 第 3 次秒 | 中位数秒 |
|---|---:|---:|---:|---:|
| low | 4.010 | 1.247 | 1.413 | 1.413 |
| high | 2.084 | 1.869 | 1.549 | 1.869 |

直连没有 Agent 系统上下文、工具、队列，属于上游定位样本，不是严格等价的性能实验。首个 low 样本 TLS 完成约 1.97 秒，其他多为约 0.2～0.4 秒，连接差异已经能显著改变短答总时间。

## 长等待与质量观察

以下来自其他真实旅程，运行条件或故障注入不同，不能混入上面的独占基线：

- T05 首轮新闻检索约 195.65 秒，11 次搜索＋11 次抓取；T09 只要求两个链接，仍用了 10 次搜索＋10 次抓取，约 224.91 秒。主要可优化方向是减少没有新增证据的检索往返，而非新增模型核对。
- T07-low 第三轮无工具，首请求约 82 秒后中断、重试约 38 秒，总计约 122.77 秒。T02-high 也有内部重试，总计约 115.73 秒。这些记录不能单独证明模型或解析器必然有缺陷。
- T29 报告子任务一次 `invalid_response`，首失败调用约 33.84 秒，子任务进入 `awaiting_retry`。测试旧等待器额外等待约 32 分钟是脚手架错误，不能计为用户实际生成耗时。
- B04 长按语音发送约 150.52 秒，包含实际模型重试。录音片段少于完整测试音频，识别差异不直接判作 ASR 质量回归。
- T79 生成 4 张图约 147.75 秒；T80 要求 100 张按现有单消息上限生成 4 张，约 174.73 秒。两例均为一次批量工具调用、后端串行生成，不是每张都重新规划。
- `P-multistep-high-1` 下载 JSON 的乙项净额 160、合计 250 正确，但最终聊天表写成乙项 150，文字与成果不一致。low 对应样本另有输入没有提供却添加“元／CNY”的问题。因此不能把获得终态或文件可下载报告成 48 次质量全通过。

12 个复杂任务另有新账号的 low／high 配对，共 24 个结果，按冻结任务判定为 20 PASS／4 FAIL（[逐例证据](../../artifacts/spec074/20261017-real-audit/semantic-review.json)）；它们用于语义和副作用比较，不混入上表。历史页图追问问题两档均出现，报告风险字段的错误成功承诺在 low 侧观察到；没有足够证据给出总体准确率提升／下降结论。

## 并发基线

独占故障环境，worker 并发 3。96 个独立账号混合短答、文本附件和创建工作，全部收到并完成，实际答案／对象 owner 与各自输入对应。没有并发代码、生图、ASR，也未测负载中的取消延迟。

| 用户数 | 完成／受理 | 上游请求 | 中位秒 | 本批经验 P95 秒 | 最慢秒 | 受理接口最慢秒 | 回执至首模型中位秒 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1/1 | 1 | 3.645 | 3.645 | 3.645 | 0.035 | 0.406 |
| 5 | 5/5 | 7 | 7.347 | 9.613 | 9.613 | 0.155 | 1.534 |
| 10 | 10/10 | 16 | 14.159 | 20.732 | 20.732 | 0.253 | 6.986 |
| 30 | 30/30 | 50 | 36.523 | 54.264 | 54.776 | 0.606 | 33.514 |
| 50 | 50/50 | 82 | 58.898 | 92.503 | 95.239 | 1.180 | 53.001 |

这只是单批经验分位数，尤其 1／5／10 人不能代表稳定 P95 或 SLA。首上游等待随人数增加，包含队列和少量前处理，不能严格当成纯排队时间。50 人任务最慢约 95 秒，不等于线上 50 人会在同一时间内完成。

宿主为 Mac ARM、10 CPU／16 GiB；故障容器运行环境约 10 CPU／8 GiB，不能外推线上 8 核 16G。采样最高 API RSS 253.09 MB、worker 261.91 MB，CPU 分别 33.7%／34.6%；未测全容器资源或长期泄漏。完整请求、结果与限制见 [负载／故障报告](../../artifacts/spec074/20261017-real-audit/faults-owned/report.md)。

## 后续修改如何比较

复用冻结输入、档位、先验与测量口径，再对受改动影响的任务做前后对照。优先检查工具往返数、重试次数和真实完成结果；不能靠降档、删掉失败样本、复用附件处理产物或添加额外“质量评审”掩盖延迟变化。本轮尚未进行任何产品优化。
