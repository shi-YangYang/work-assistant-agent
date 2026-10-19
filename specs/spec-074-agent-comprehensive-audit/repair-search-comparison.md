# 搜索返工：真实模型定向对照

## v3 首轮结论

**FAIL：来源交付正确，但流程与耗时未达到目标。** 两种强度最终都有真实工具返回的 ChatGPT Learn 与 Claude 产品链接，并准确说明 OpenAI 正文未读；但用户只要求链接，任务却被升级成正文核验并标记为 blocked/awaiting_input。不能把有链接和无伪造当作整个用例通过。

原输入始终为“请联网查OpenAI和Anthropic各一个官方产品介绍页面，给链接即可。”每个强度仅首轮一次；没有更换问题、强制工具决策、替写答案或重跑到绿。

## 冻结条件

- v3 采样北京时间 **2026-10-17 23:34:10—23:48:46**。后续整理与 v4 复验已跨到 10/18，不能称全部同日对照。
- 服务、模型、low/high、人设、权限、14 个观察驱动与原 before 一致，worker 并发 1，新账号/会话/独立 schema。
- v3 源码目录：`/private/var/folders/36/c4plv9vs1bl3ck8hmc7jstjh0000gn/T/spec074-repair-search-v3-1puznp7t`。
- Python 树 SHA：`327b91292abbfdfdb6461809c01af231aff995d66e121bcc0ab06170af94d90e`；相对报告 v2 仅 `tool_progress/{evidence,service,state}.py` 改动。
- 先前 before、v1、报告 v2 证据均未覆盖。此两例不能拼接成新的全量准确率。

## 耗时、请求与工具执行

| 强度 | 原 before 秒 / 模型 HTTP | v1 秒 / 模型 HTTP | v3 秒 / 模型 HTTP |
| ---- | -----------------------: | ----------------: | ----------------: |
| low  |              170.74 / 15 |         72.86 / 8 |       359.04 / 28 |
| high |              274.22 / 18 |       189.76 / 13 |       518.12 / 25 |

v1 low 未交付 OpenAI 链接，不能视为同质量速度基准；v3 两例有链接但额外核验和错误未完成状态仍是缺陷。

| 强度 / 工具   | 调用数 | 实际尝试数（含工具内重试） | 各调用耗时相加 | 去除并发重叠的时间 | 无新增来源搜索 |
| ------------- | -----: | -------------------------: | -------------: | -----------------: | -------------: |
| low / search  |     34 |                         37 |       62.70 秒 |           40.50 秒 |             27 |
| low / fetch   |     17 |                         33 |      172.80 秒 |          112.82 秒 |              — |
| high / search |     27 |                         29 |       48.01 秒 |           34.81 秒 |             23 |
| high / fetch  |     21 |                         48 |      278.04 秒 |          258.67 秒 |              — |

工具可在一轮中并发，上表各列不能直接相加当用户总耗时。每次来源增量比较保留 URL、标题和摘要的 SHA，而非只按 URL 数量判断。

## 已经够交付之后发生了什么

| 强度 | 最早已有两家产品链接   | 此后新 search / fetch | 此后模型 HTTP | 此后无新增来源搜索 | 至最终回复剩余时间（约） |
| ---- | ---------------------- | --------------------: | ------------: | -----------------: | -----------------------: |
| low  | 第16次搜索，169.894 秒 |                17 / 5 |            12 |                 15 |                189.15 秒 |
| high | 第8次搜索，50.914 秒   |               19 / 18 |            18 |                 18 |                467.21 秒 |

这些时点来自实际工具返回，不是猜测可能找到链接的时机。Anthropic 先返回了 `https://www.anthropic.com/claude/opus`，之后 OpenAI 返回 `https://learn.chatgpt.com/docs`；均足以满足仅需链接的原请求。Claude 概览页随后实际读取成功；最终链接未把失败请求地址冒充检索结果。

high 对 `learn.chatgpt.com/docs` 调用了3次（含 refresh），对 `/docs/overview` 调用了2次（含 refresh）。每次均4次执行尝试、约28秒。临时网络错误可再次请求，工具内部重试与反复查找相叠加，是实际耗时的重要部分。

两例均没有预算或全局无进展强制停止：`taskBudget.reason` 为空，`toolProgress.stopped=false`；low 最后 stalled=0，high=4。模型自行输出 blocked，原因仍为 OpenAI 正文未读。v3 将不同查询的空结果改为软提示后，未形成任务范围内的收敛；仅提醒“可直接提供链接”不足以抵消“只引用实际读取来源”的歧义。此问题不能仅归类为网络慢或模型能力差。

## 证据与清理

- [v3 manifest](../../artifacts/spec074/20261017-repair-comparison/after-v3/manifest.json)
- [逐调用、来源指纹与最早交付点](../../artifacts/spec074/20261017-repair-comparison/after-v3/search-analysis.json)
- [真实模型请求和耗时](../../artifacts/spec074/20261017-repair-comparison/after-v3/facts.json)
- [首轮语义评估](../../artifacts/spec074/20261017-repair-comparison/after-v3/semantic-review.json)
- [业务读回与预算](../../artifacts/spec074/20261017-repair-comparison/after-v3/readback.json)
- [资源清理](../../artifacts/spec074/20261017-repair-comparison/after-v3/resource-cleanup.json)

v3 的 API/worker 已停止，独立 schema `spec074_web_ffd0a3cc12ef`、私有目录及凭据已删除；无沙盒执行，命名空间 Redis 键为0。源码快照与证据保留。

## v4 新契约复验

v4 **交付与终态通过，收敛性能仍未通过**。两例都给出有真实来源的官方产品介绍链接，`taskOutcome=completed`、`remaining=[]`、没有 pending interactions；`awaiting_input` 在本项目表示正常等待新消息，不能仅因此判失败。未读正文不再被标成额外未完成任务。

v4 采样北京时间 **2026-10-18 00:30:30—00:36:54**；与 before/v1/v3 跨午夜，仍在同一周。模型配置、14个驱动和原问题不变。相对 v3 仅 `agent/prompts/main.py` 不同，冻结源码为 `/private/var/folders/36/c4plv9vs1bl3ck8hmc7jstjh0000gn/T/spec074-repair-search-v4-x0zj3ntc`，Python 树 SHA `93d7ec77b7944ce7f9fb0ea4504e67343f25c3dcfad9947e7ea50640c6e57ae8`。

| 强度 | v4 秒 / 模型 HTTP | 对原 before 的秒数变化 | 对 v3 的秒数变化 | search / fetch | 实际尝试数 search / fetch |
| ---- | ----------------: | ---------------------: | ---------------: | -------------: | ------------------------: |
| low  |       194.79 / 15 |                 +24.05 |          -164.25 |         15 / 7 |                   15 / 16 |
| high |       189.05 / 15 |                 -85.17 |          -329.07 |         18 / 8 |                   19 / 17 |

不能将 v4 两例相加减少的耗时直接描述成稳定提速。low 比原 before 慢24.05秒；high 比原 before 快85.17秒，但两个强度都仍有明确多余调用。

| 强度 | 最早已有两家产品链接  | 此后新 search / fetch | 此后模型 HTTP | 此后无新增来源搜索 | 至最终回复剩余时间（约） |
| ---- | --------------------- | --------------------: | ------------: | -----------------: | -----------------------: |
| low  | 第4次搜索，28.826 秒  |                10 / 6 |            10 |                 10 |                165.96 秒 |
| high | 第13次搜索，60.831 秒 |                 4 / 4 |             5 |                  4 |                128.22 秒 |

这里不是拿到第二个链接之前的必要探索：两个时点之后已经有工具检索到的 `learn.chatgpt.com/docs/use-chatgpt` 与 `anthropic.com/claude/opus`。后续仍试图寻找或读取更多营销介绍页，low 的10次、high 的4次新增搜索均无新来源。正常内部重试也放大了网络等待：每例3个 `web_network` 抓取各自达到4次执行尝试，抓取去重并发时间分别91.42秒和92.33秒。本轮没有为了缩短测试耗时降低重试稳定性或改变总预算。

最终回复中的所有 Markdown 链接均可追溯到真实搜索条目、已读页面链接或已读正文，失败网址回显不作为来源。low 使用 ChatGPT Learn 与已读 Claude Opus；high 使用 ChatGPT Learn 与 Claude 产品概览，并附真实 Claude Opus 页。两例预算停止原因仍为空，`toolProgress.stopped=false`；最终正常完成。v4 改正完成条件并减少 v3 的额外流程，但 A03 尚未根除，不作性能全通过或所有循环已解决的结论。

## v4 证据与清理

- [v4 manifest](../../artifacts/spec074/20261017-repair-comparison/after-v4/manifest.json)
- [四版本耗时与请求对照](../../artifacts/spec074/20261017-repair-comparison/search-comparison.json)
- [v4 逐调用、来源指纹与最早交付点](../../artifacts/spec074/20261017-repair-comparison/after-v4/search-analysis.json)
- [最终链接的完整来源关联](../../artifacts/spec074/20261017-repair-comparison/after-v4/search-delivery.json)
- [v4 首轮评估](../../artifacts/spec074/20261017-repair-comparison/after-v4/semantic-review.json)
- [v4 业务读回及预算](../../artifacts/spec074/20261017-repair-comparison/after-v4/readback.json)
- [v4 资源清理](../../artifacts/spec074/20261017-repair-comparison/after-v4/resource-cleanup.json)

v4 API/worker 均已停止，独立 schema `spec074_web_2e8891dc8532`、私有目录及凭据已删除；本轮命名空间 Redis 的2个键已删除，无沙盒执行。保留冻结源码和证据，不修改日常服务。不再调整规则或新增模型调用，独立验收据此区分工程修复与性能残留。

## 搜索等待与无增量循环：同日六例对照

**工程优化有效，但搜索任务仍非全通过。** 首轮各六例均真实调用当前配置的 `deepseek-v4.1-flash`，low/high 各三例。两边均为 5 PASS / 1 FAIL：before 的 links-low、after 的 links-high 都交付了真实官方链接，却将用户没有要求的 OpenAI 正文／特定域名要求当作未完成事项。不能把答复有链接、工具次数减少或总耗时缩短直接称为完整质量通过。

### 冻结条件与输入

- before：北京时间 **2026-10-18 10:16:29—10:23:58**，树 SHA `93d7ec77b7944ce7f9fb0ea4504e67343f25c3dcfad9947e7ea50640c6e57ae8`，与上面的 v4 代码一致，重新采样而非复用旧答案。
- after：北京时间 **2026-10-18 10:56:21—10:59:36**，树 SHA `9d94acd2fd3390649ac1b809282134864a17cbd7e2f65ea116049c6ec8e5488d`。相对 before 仅 7 个生产 Python 文件变化，详见 [实现说明](repair-search-latency.md)与 [after manifest](../../artifacts/spec074/20261018-search-latency/after/manifest.json)。共享静态配置与 before 完全一致。
- 同一模型服务、权限、人设、low/high 和观察驱动；每例新账号／会话，每边独立 schema、Redis 命名空间及媒体目录，worker 并发 1，依次执行。没有替写模型回复、注入成功工具结果、自动换模型、降档或补跑失败到通过。
- 采用正常 HTTP API → worker → 实际模型／搜索／网页读取 → SSE 与数据库读回。时间是请求到服务端终态，不是浏览器绘制耗时；模型时间包含传输、推理及输出，不能全部称为“思考时间”。
- before 首次启动缺少冻结树的 `packages/api-contracts/input-rules.json`，导致六例在登录连接阶段失败，**零受理消息、零模型请求**。原记录保留在 `before/harness-failed`；补齐未改共享静态配置、启动正常服务后首次实际运行。这是脚手架准备错误，不计为模型／产品失败，也没有覆盖首轮模型结果。

同一组输入各运行 low/high 一次：

1. **links**：“请联网查OpenAI和Anthropic各一个官方产品介绍页面，给链接即可。”
2. **body**：“请读取 Python 官方文档 https://docs.python.org/3/howto/sorting.html ，说明 list.sort() 和 sorted() 是否原地修改、各自返回什么，以及两者排序是否稳定。请引用这个页面，不要仅凭记忆回答。”
3. **chat**：“请用一句话解释为什么天空通常是蓝色的。”

### 总耗时与任务结果

| 场景       | before 秒 | after 秒 | 模型 HTTP 次数 before → after | 首轮结果 before → after     |
| ---------- | --------: | -------: | ----------------------------: | --------------------------- |
| links low  |    147.65 |    32.79 |                         9 → 6 | FAIL（错误 blocked）→ PASS  |
| links high |    247.09 |   122.98 |                       15 → 12 | PASS → FAIL（错误 blocked） |
| body low   |     19.49 |    16.41 |                         4 → 4 | PASS → PASS                 |
| body high  |     24.61 |    16.41 |                         4 → 4 | PASS → PASS                 |
| chat low   |      5.16 |     4.13 |                         1 → 1 | PASS → PASS                 |
| chat high  |      4.14 |     3.13 |                         1 → 1 | PASS → PASS                 |

links 两档该次样本分别少 **114.86 秒（77.8%）**、**124.11 秒（50.2%）**。这不是稳定延迟分布或同等质量全部通过的证明：每格一次，先 before 再 after，网络与服务商负载没有固定；模型选择的查询／网址也不同。正文与普通聊天模型轮数未增加，四例目标事实与交付均正确。它们的秒数变化包含模型及网络波动，不能全部归功于搜索代码。

### 时间花在哪里

以下均按观察区间去除并发重叠。模型与所有工具的合计再加其他流程，才可与总耗时对照；search 与 fetch 可能重叠，不能直接相加。

| links 场景 | 模型累计秒 before → after | 搜索墙钟秒 before → after | 读取墙钟秒 before → after | 所有工具墙钟秒 before → after |
| ---------- | ------------------------: | ------------------------: | ------------------------: | ----------------------------: |
| low        |             56.47 → 23.58 |              24.61 → 7.20 |              66.80 → 1.55 |                  88.88 → 7.29 |
| high       |            117.01 → 78.15 |             38.50 → 15.86 |             95.39 → 30.56 |                126.08 → 41.74 |

| links 场景 | 搜索调用 / 实际尝试 before → after | 读取调用 / 实际尝试 before → after |
| ---------- | ---------------------------------- | ---------------------------------- |
| low        | 7 / 9 → 6 / 6                      | 6 / 15 → 2 / 2                     |
| high       | 14 / 15 → 14 / 14                  | 11 / 20 → 6 / 8                    |

after high 的两个 `web_network` 网页读取仍真实失败，但每次各执行 2 次，未再达到 before 的 4 次；HTTP 403 没有按临时网络错误反复自动尝试。不能因 low 这次没有读取超时就推断所有网络失败已消除。

### 是否在资料够用后及时结束

| 场景       | 两家官方产品链接最早齐全 before → after | 此后 search / fetch before → after | 此后模型 HTTP before → after | 此后等待秒 before → after |
| ---------- | --------------------------------------- | ---------------------------------- | ---------------------------- | ------------------------- |
| links low  | 28.86 → 26.02 秒                        | 4 / 4 → 0 / 0                      | 5 → 1                        | 118.79 → 6.77             |
| links high | 106.06 → 30.49 秒                       | 3 / 5 → 8 / 4                      | 5 → 7                        | 141.03 → 92.49            |

low 在资料齐全后直接进入最终回答，未再调用工具。high 仍有 8 次没有新增来源的搜索和 4 次读取；最终正文给出 ChatGPT Learn 与 Claude 产品总览，但 `taskOutcome=blocked`，原因是没取得 `openai.com` 的营销页。用户仅要求两家官方产品介绍链接，未指定营销页或要求正文，所以这是尚未解决的任务范围膨胀和错误未完成状态。不能将其归为用户要求不明确，也不能用总耗时减半掩盖。

### 正文质量与普通路径

- 四个 body 样本都真正读取了 Python 官方原文，返回 `list.sort()` 原地修改且返回 `None`、`sorted()` 新建并返回列表、两者排序稳定这三组事实，并给出指定来源。
- before/after 每个 body 样本均有两次成功 `web_fetch`：首次获取页面正文，后续读取缓存中的稳定性段落；before low 额外有一次 `web_find` 未匹配。after 没有把已读 URL 的不同正文段落误当重复，也没有用搜索摘要替代正文。`cacheHit=true` 的段落来自该任务前一次真实下载，不是历史答案回放。
- 四个 chat 样本都为一轮模型、零工具的正确简短解释，没有为普通聊天增加搜索、分类或核对轮次。
- 无业务操作、成果生成或沙盒执行。数据库中的 3 项工作是环境预置夹具，不是模型新增写入。

### 本轮证据与清理

[冻结输入](../../artifacts/spec074/20261018-search-latency/cases.json)、[配对结果](../../artifacts/spec074/20261018-search-latency/paired-results.json)保留逐项耗时、真实调用次数、来源关联和首轮判分。两边的 `facts.json`、`trace.jsonl`、`readback.json`、`search-analysis.json`、`timing-breakdown.json` 和 `semantic-review.json` 分别位于 [before](../../artifacts/spec074/20261018-search-latency/before/facts.json)、[after](../../artifacts/spec074/20261018-search-latency/after/facts.json)。原始实际回答和工具正文可沿 facts 的 evidence 路径复核。

两边 API/worker 已停止，独立 schema `spec074_web_9029a1206864`、`spec074_web_7a2d68bb79eb`、私有目录和凭据已删除；命名空间 Redis 共清理 6 个键，没有沙盒执行。详见 [before 清理](../../artifacts/spec074/20261018-search-latency/before/resource-cleanup.json)、[after 清理](../../artifacts/spec074/20261018-search-latency/after/resource-cleanup.json)。保留冻结源码与脱敏证据，未修改线上或日常服务。

## 同日 after-v2：消除失败反馈中的继续搜索要求

**任务答案与终态 6/6 通过，搜索性能仍 FAIL。** after high 的失败证据触发了明确的源码修复：研究按需策略、失败回执 `nextStep` 和进度反馈不再无条件要求继续查找，也不把用户未指定的域名／营销页／正文要求变成剩余目标。没有修改输入或重跑 before，保留首次 after 的 5/6 结果。

- 采样北京时间 **2026-10-18 11:15:15—11:22:15**。
- 冻结树 SHA `93483f0fe364503ef2496458e2fd4f2a45f21661decdb423dbd5ce992a05c343`，相对 after 仅 `agent/prompts/main.py`、`agent/runtime/tool_progress/service.py`、`agent/tools/resources/web.py` 不同。其余驱动、真实模型配置、权限、人设、原六例和隔离方式均不变，原失败没有覆盖。

| 场景       | before 秒 | after 首轮秒 | after-v2 秒 | 模型 HTTP before → after-v2 | v2 目标结果      |
| ---------- | --------: | -----------: | ----------: | --------------------------- | ---------------- |
| links low  |    147.65 |        32.79 |      153.91 | 9 → 16                      | PASS；耗时未改善 |
| links high |    247.09 |       122.98 |      225.11 | 15 → 21                     | PASS；仍冗余调用 |
| body low   |     19.49 |        16.41 |       18.45 | 4 → 4                       | PASS             |
| body high  |     24.61 |        16.41 |       14.37 | 4 → 4                       | PASS             |
| chat low   |      5.16 |         4.13 |        3.11 | 1 → 1                       | PASS             |
| chat high  |      4.14 |         3.13 |        4.14 | 1 → 1                       | PASS             |

v2 两个 links 最终均给出真实工具来源中的 ChatGPT Learn 与 Claude 产品总览，`taskOutcome=completed`、`remaining=[]`，没有把 OpenAI 正文不可读写成额外待完成事项。两例 body 继续真实读取 Python 页面和稳定性段落，目标事实正确；chat 保持一轮模型、零工具。这里的 6/6 仅表示六个冻结任务的答案／来源／终态，不是整体性能通过。

| v2 links 强度 | 模型累计秒 | 搜索墙钟秒 | 读取墙钟秒 | 全部工具墙钟秒 | 搜索调用 / 尝试 | 读取调用 / 尝试 |
| ------------- | ---------: | ---------: | ---------: | -------------: | --------------- | --------------- |
| low           |      99.23 |      16.93 |      43.03 |          51.64 | 14 / 14         | 13 / 17         |
| high          |     167.21 |      27.39 |      28.24 |          52.97 | 29 / 29         | 9 / 13          |

自动重试已维持最多两次；但累计模型请求从 before 的 9/15 次变成 16/21 次，足以抵消工具等待改善。**不能再把慢归因于单轮思考特别长**：v2 low/high 模型单轮中位数约 5.20/6.59 秒，长时间主要仍来自往返次数叠加。

| v2 强度 | 最早两家产品链接齐全 | 之后搜索 / 读取 | 之后模型请求 | 之后无新增来源搜索 | 到最终回答剩余时间 |
| ------- | -------------------: | --------------- | -----------: | -----------------: | -----------------: |
| low     |             77.65 秒 | 6 / 4           |            6 |                  5 |           76.26 秒 |
| high    |             41.03 秒 | 22 / 5          |           14 |                 19 |          184.08 秒 |

这不是高质量所必需的正文研究：原任务仅需要链接。v2 改正任务完成语义，但未让模型稳定地在证据足够时结束；不得只挑 after 首轮 32.79/122.98 秒作最终速度结论，也不得把 v2 的 6/6 与上一版耗时拼成一个不存在的通过版本。low 相对 before 仍慢 6.26 秒，high 少 21.98 秒，每格单次不证明稳定改善。

证据：[v2 manifest](../../artifacts/spec074/20261018-search-latency/after-v2/manifest.json)、[facts](../../artifacts/spec074/20261018-search-latency/after-v2/facts.json)、[逐调用分析](../../artifacts/spec074/20261018-search-latency/after-v2/search-analysis.json)、[时间分解](../../artifacts/spec074/20261018-search-latency/after-v2/timing-breakdown.json)、[语义审查](../../artifacts/spec074/20261018-search-latency/after-v2/semantic-review.json)。[配对结果](../../artifacts/spec074/20261018-search-latency/paired-results.json)已追加独立的 after-v2 键，before/after 内容保留。

v2 API/worker 已停止，独立 schema `spec074_web_8299112d21ca`、私有目录及凭据已删除，命名空间 Redis 的 6 个键已清理；没有沙盒执行，不涉及日常或线上服务，见 [v2 清理](../../artifacts/spec074/20261018-search-latency/after-v2/resource-cleanup.json)。

## 同日 after-v3：修正原始空域名搜索回执

**答案／来源／终态仍为 6/6，搜索收敛性能仍 FAIL。** v2 轨迹进一步证明，原始 `web_search` 空域名结果还会无条件要求继续检索，并把模型自行指定的 domains 过滤器当成用户要求。v3 只修改 `integrations/web_research.py` 的 `coverage`／`nextStep` 两处反馈，不改变域名过滤、结果条目或重试逻辑；再次执行原六例首轮，不重跑 before，也不覆盖 v2。

- 北京时间 **2026-10-18 11:37:04—11:43:29**。
- 冻结树 SHA `c6c599fa8f4b3e9db92d6ad32db66e3c92d869df49a73d9335235fae67df399f`，相对 v2 仅上述一个生产文件不同；模型／强度／人设／权限／输入及观察驱动保持一致。

| 场景       | before 秒 | after-v2 秒 | after-v3 秒 | v3 模型 HTTP 次数 | v3 任务结果        |
| ---------- | --------: | ----------: | ----------: | ----------------: | ------------------ |
| links low  |    147.65 |      153.91 |      168.36 |                18 | PASS；仍有冗余调用 |
| links high |    247.09 |      225.11 |      170.31 |                15 | PASS；仍有冗余调用 |
| body low   |     19.49 |       18.45 |       21.47 |                 5 | PASS               |
| body high  |     24.61 |       14.37 |       15.35 |                 3 | PASS               |
| chat low   |      5.16 |        3.11 |        6.17 |                 1 | PASS               |
| chat high  |      4.14 |        4.14 |        3.10 |                 1 | PASS               |

v3 两条 links 最终都引用实际工具证据中的 ChatGPT Learn 与 Claude 总览，`completed` 且没有额外剩余任务。但 low 比 before 慢 **20.71 秒**，high 少 **76.78 秒**；不能称两档稳定提速。body 两档都继续真实读取官方正文并正确回答三组事实，low 读取 3 次／5 轮模型，high 读取 2 次／3 轮模型；这是模型选择的分段策略变化，并未引入固定核对轮次。普通 chat 均仍为 1 轮模型、零工具。

| v3 links 强度 | 模型累计秒 | 搜索墙钟秒 | 读取墙钟秒 | 全部工具墙钟秒 | 搜索调用 / 尝试 | 读取调用 / 尝试 |
| ------------- | ---------: | ---------: | ---------: | -------------: | --------------- | --------------- |
| low           |     118.08 |      21.15 |      29.54 |          44.75 | 24 / 24         | 9 / 11          |
| high          |      81.21 |      50.97 |      42.97 |          85.76 | 17 / 19         | 8 / 10          |

| v3 强度 | 最早两家产品链接齐全 | 此后搜索 / 读取 | 此后模型 HTTP | 此后无新增来源搜索 | 到最终回答剩余时间 |
| ------- | -------------------: | --------------- | ------------: | -----------------: | -----------------: |
| low     |             99.25 秒 | 9 / 1           |             6 |                  9 |           69.11 秒 |
| high    |             45.68 秒 | 10 / 5          |             9 |                  9 |          124.62 秒 |

这些结果表明回执契约矛盾已被移除，正确完成语义也保留，但单靠反馈语句无法确保模型及时结束。v3 不能作为搜索性能通过的依据，不能用前一版偶然较快样本替换本版结果。

证据：[v3 manifest](../../artifacts/spec074/20261018-search-latency/after-v3/manifest.json)、[facts](../../artifacts/spec074/20261018-search-latency/after-v3/facts.json)、[逐调用分析](../../artifacts/spec074/20261018-search-latency/after-v3/search-analysis.json)、[时间分解](../../artifacts/spec074/20261018-search-latency/after-v3/timing-breakdown.json)、[语义审查](../../artifacts/spec074/20261018-search-latency/after-v3/semantic-review.json)。[配对结果](../../artifacts/spec074/20261018-search-latency/paired-results.json)保留所有版本的独立数据。

v3 API/worker 已停止，独立 schema `spec074_web_cf5c35451e0c`、私有目录及凭据已删除，命名空间 Redis 的 6 个键已清理；无沙盒执行，未修改日常或线上服务，见 [v3 清理](../../artifacts/spec074/20261018-search-latency/after-v3/resource-cleanup.json)。

## 同日 after-v4：独立搜索额度与剩余反馈

**六例任务语义仍通过，但搜索性能 FAIL；两档链接任务均比 before 更慢。** 本版明确修改了六个预算／运行时文件，为新任务增加独立的 16 次 `web_search` 额度和内部剩余反馈，搜索耗尽后仍允许正文读取与其他任务工具。按原六例首次运行，没有重跑 baseline 或覆盖前三版失败。

- 北京时间 **2026-10-18 11:59:53—12:09:20**。
- 冻结树 SHA `a93534a1b914b8a1f0c23f5fb1254283ba43d44b79d231e56cfe7e276c353315`；相对 v3 只改变 `agent/runtime/{budget,middleware}.py`、`agent/runtime/tool_progress/service.py` 和 `tasks/budget/{policy,service,state}.py`。原问题、模型、low/high、权限、人设与串行 worker 均不变。

| 场景       | before 秒 | after-v3 秒 | after-v4 秒 | v4 模型 HTTP 次数 | v4 任务结果             |
| ---------- | --------: | ----------: | ----------: | ----------------: | ----------------------- |
| links low  |    147.65 |      168.36 |      209.31 |                18 | PASS；耗时增加 61.66 秒 |
| links high |    247.09 |      170.31 |      314.96 |                23 | PASS；耗时增加 67.87 秒 |
| body low   |     19.49 |       21.47 |       18.42 |                 4 | PASS                    |
| body high  |     24.61 |       15.35 |       15.38 |                 3 | PASS                    |
| chat low   |      5.16 |        6.17 |        4.13 |                 1 | PASS                    |
| chat high  |      4.14 |        3.10 |        4.18 |                 1 | PASS                    |

链接结果均给出实际检索到的 ChatGPT Learn 和实际读取过的 Claude 产品总览，`completed`、`remaining=[]`；两者都说明 OpenAI 正文未读到，未向用户复述内部搜索额度。它们确实完成了这两个仅需链接的目标，不能把完成归因于额度耗尽，也不能把抓取失败当作没有有效链接。两例正文题均实际读取 Python 原文和稳定性段落，回答所需事实；high 对官方稳定性承诺的措辞有额外保留说明，但未改成错误结论。普通题维持一轮模型、零工具。

| v4 links 强度 | 模型累计秒 | 搜索墙钟秒 | 读取墙钟秒 | 全部工具墙钟秒 | 搜索调用 / 尝试 | 读取调用 / 尝试 |
| ------------- | ---------: | ---------: | ---------: | -------------: | --------------- | --------------- |
| low           |     126.16 |      17.43 |      62.92 |          78.66 | 17 / 16         | 15 / 20         |
| high          |     211.30 |      28.72 |      80.34 |          98.99 | 18 / 17         | 22 / 29         |

这里“搜索调用”包括被额度拒绝的派发，“尝试”是实际底层执行次数：low 为 16 个已准入搜索，加 1 个未执行回执；high 为 16 个已准入搜索、1 次底层重试，加 2 个未执行回执。不能将 18 次派发说成额度失效，也不能将 17 次底层尝试说成允许了 17 个搜索目标。读取仍遵循已有的至多两次尝试策略。模型累计时间包含传输、推理和输出，不等于纯思考时间。

### 额度生效证据与实际不足

- 两个任务数据库均有 `assistant-v2` 策略、`research_searches=16` 和 **16 个独立 `researchSearchReservations`**。超额回执为 `research_search_limit`、`executed=false`，没有伪造搜索结果。
- 第 16 个搜索准入后，low/high 后续 **5/10 轮**真实模型请求的 `offered` 工具列表均不再包含 `web_search`，仍包含 `web_fetch`。同批已经产生的越界调用也被拒绝，额度没有自动结束整条任务。
- 内部 system 正文在观察器中只保留 SHA256，因而本轮 trace 不能直接复述每轮剩余数字；实际额度执行、持久预留和模型可用工具变化有独立证据，剩余反馈文本的实现另由源码与定向检查核对。没有为了取证改写模型输入或追加真实调用。
- 额度耗尽后仍有多次网页抓取，但没有成功取得新的正文。任务最终正常回答，主要问题变为持续读取不必要或不可达的网页；单独限制搜索次数没有让整体研究及时结束。

| v4 强度 | 最早两家产品链接齐全 | 此后搜索 / 读取 | 此后模型 HTTP | 此后无新增来源搜索 | 到最终回答剩余时间 |
| ------- | -------------------: | --------------- | ------------: | -----------------: | -----------------: |
| low     |             53.89 秒 | 5 / 11          |             9 |                  4 |          155.42 秒 |
| high    |             30.98 秒 | 13 / 21         |            19 |                 10 |          283.98 秒 |

v4 模型单轮中位数约 6.46/8.19 秒、最大值 14.98/24.66 秒。结果再次指向多轮模型和工具往返叠加，而不是某一次持续几分钟的思考。每格只有一个首轮样本，不能把本轮变慢全部归因于额度代码；但也没有证据宣称搜索优化目标达成。应保留 **性能 FAIL**，不能以 6/6 答案通过代替速度验收。

证据：[v4 manifest](../../artifacts/spec074/20261018-search-latency/after-v4/manifest.json)、[facts](../../artifacts/spec074/20261018-search-latency/after-v4/facts.json)、[逐调用分析](../../artifacts/spec074/20261018-search-latency/after-v4/search-analysis.json)、[时间分解](../../artifacts/spec074/20261018-search-latency/after-v4/timing-breakdown.json)、[预算证据](../../artifacts/spec074/20261018-search-latency/after-v4/budget-evidence.json)、[语义审查](../../artifacts/spec074/20261018-search-latency/after-v4/semantic-review.json)。[配对结果](../../artifacts/spec074/20261018-search-latency/paired-results.json)已追加 after-v4 并保留全部历史结果。

v4 API/worker 已停止，独立 schema `spec074_web_03567533a9c2`、私有目录与凭据已删除，本轮清理时命名空间 Redis 已无键；没有沙盒执行或业务写入，不涉及日常和线上服务，见 [v4 清理](../../artifacts/spec074/20261018-search-latency/after-v4/resource-cleanup.json)。

独立验收后已撤回 v4 的六个产品文件额度增量及对应测试，当前实现恢复到 after-v3。上述 v4 实测仅作为保留的失败实验记录，不能用于描述当前版本。后续搜索结果质量排查尚未构成新的已验证版本，本评测不追加模型调用。
