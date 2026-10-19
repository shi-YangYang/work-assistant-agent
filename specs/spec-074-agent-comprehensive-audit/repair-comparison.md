# Spec074 修复真实模型对照（实施评估）

本报告是实施阶段的首轮真实评估，独立验收另行判断。没有重跑失败案例、替换模型回答或强制工具选择。

## 结论

36 轮总耗时由 1293.21 秒降到 1050.75 秒，下降 18.75%；但并非同质量下全面提速。整条用例通过数同为 14/18，逐轮通过数由 32/36 变为 30/36，不能据此宣称质量没有下降，也不能用这个小样本断定所有变化都由代码引起。

两侧均通过的 27 轮合计 835.80 → 765.56 秒（下降 8.40%），这是按结果筛选的描述性统计，不是独立性能证明。6 次普通问答均回答正确且无工具；中位数 3.13 → 3.15 秒，未观察到新增模型往返。

## 比较条件

- 基线提交：`26db8f9bb8af64da403696362b158df7a94ebe1a`，通过 `git archive` 保存到临时目录，没有回退工作区。
- 修后 Python 源码快照：`/private/var/folders/36/c4plv9vs1bl3ck8hmc7jstjh0000gn/T/spec074-repair-after-an5oqmd8`；树 SHA-256：`be5533d8912861b799b152f767fd036bbbb77a0a762f70d03f6c92b4f97b06a2`。
- 修前目录、归档 SHA、14 个共享驱动 SHA、修后逐文件 SHA 与 diff 均保留在证据 manifest / source-files / source.patch。两侧 HTTP/模型观察驱动相同。
- 同一真实服务与模型 `deepseek-v4.1-flash`，low/high；相同人设、权限及原冻结输入/文件 SHA。每个用例独立账号/会话，两侧不同 owned schema 和 media 目录。
- 两侧串行执行、`PAA_WORKER_CONCURRENCY=1`；因此报告路径的绝对时长不能代表默认多槽生产环境。此配置两侧不变。
- 2026-10-17 同一天运行，本周均为 10-12～10-18。计时为发送用户消息到终态回复，包含报告子任务/自然业务确认，排除环境准备、预上传及事后读回。
- 只首轮运行一次，内部正常重试保留。先 BEFORE 后 AFTER，非随机交错，服务商/网络可能变化；搜索实际有 HTTP 403 和连接失败。

## 汇总

| 指标                |          修前 |          修后 |
| ------------------- | ------------: | ------------: |
| 用例 / 对话轮次     |       18 / 36 |       18 / 36 |
| 通过用例            |       14 / 18 |       14 / 18 |
| 通过轮次            |       32 / 36 |       30 / 36 |
| 总耗时              |      1293.21s |      1050.75s |
| 实际模型 HTTP 请求  |           157 |           134 |
| 实际工具尝试        |           196 |           160 |
| 模型输入 tokens     |     1,088,779 |       916,130 |
| 普通问答均值 / 中位 | 3.14s / 3.13s | 3.31s / 3.15s |

`awaiting_input` 是已回答后等待下一条消息的正常终态，不直接作为失败；`succeeded` 也不直接作为语义通过。模型请求数统计实际 HTTP 请求，不混入 web 搜索 HTTP。

## 每用例质量与耗时

| 用例               | 修前质量 | 修后质量 | 修前秒 | 修后秒 | 模型请求 前→后 |
| ------------------ | -------- | -------- | -----: | -----: | -------------: |
| P-chat-high-1      | PASS     | PASS     |   3.15 |   3.16 |          1 → 1 |
| P-chat-high-2      | PASS     | PASS     |   3.13 |   3.13 |          1 → 1 |
| P-chat-high-3      | PASS     | PASS     |   3.10 |   3.17 |          1 → 1 |
| P-chat-low-1       | PASS     | PASS     |   4.20 |   3.13 |          1 → 1 |
| P-chat-low-2       | PASS     | PASS     |   2.11 |   4.13 |          1 → 1 |
| P-chat-low-3       | PASS     | PASS     |   3.13 |   3.12 |          1 → 1 |
| P-multistep-high-1 | PASS     | PASS     |  19.56 |  18.57 |          3 → 3 |
| P-multistep-low-1  | PASS     | PASS     |  14.41 |  12.37 |          3 → 3 |
| R-T09-high         | PASS     | PASS     | 274.22 | 189.76 |        18 → 13 |
| R-T09-low          | PASS     | FAIL     | 170.74 |  72.86 |         15 → 8 |
| R-T29-high         | PASS     | PASS     | 161.13 | 118.14 |        24 → 20 |
| R-T29-low          | FAIL     | FAIL     | 184.10 | 139.56 |        30 → 18 |
| R-T64-high         | PASS     | FAIL     |  42.05 |  40.97 |          3 → 3 |
| R-T64-low          | FAIL     | PASS     |  31.00 |  37.87 |          3 → 3 |
| R-T67-high         | FAIL     | PASS     | 116.84 | 129.69 |        15 → 18 |
| R-T67-low          | PASS     | FAIL     | 132.40 | 142.53 |        17 → 17 |
| R-T69-high         | PASS     | PASS     |  58.24 |  73.19 |        10 → 11 |
| R-T69-low          | FAIL     | PASS     |  69.70 |  55.40 |        10 → 11 |

## 逐轮质量与耗时

| 用例 / 轮次            | 修前 | 修后 | 修前秒 | 修后秒 | 差值秒 |
| ---------------------- | ---- | ---- | -----: | -----: | -----: |
| P-chat-high-1 / 1      | PASS | PASS |   3.15 |   3.16 |  +0.01 |
| P-chat-high-2 / 1      | PASS | PASS |   3.13 |   3.13 |  +0.00 |
| P-chat-high-3 / 1      | PASS | PASS |   3.10 |   3.17 |  +0.07 |
| P-chat-low-1 / 1       | PASS | PASS |   4.20 |   3.13 |  -1.07 |
| P-chat-low-2 / 1       | PASS | PASS |   2.11 |   4.13 |  +2.02 |
| P-chat-low-3 / 1       | PASS | PASS |   3.13 |   3.12 |  -0.01 |
| P-multistep-high-1 / 1 | PASS | PASS |  19.56 |  18.57 |  -0.99 |
| P-multistep-low-1 / 1  | PASS | PASS |  14.41 |  12.37 |  -2.04 |
| R-T09-high / 1         | PASS | PASS | 274.22 | 189.76 | -84.46 |
| R-T09-low / 1          | PASS | FAIL | 170.74 |  72.86 | -97.88 |
| R-T29-high / 1         | PASS | PASS |  62.69 |  27.76 | -34.93 |
| R-T29-high / 2         | PASS | PASS |  38.87 |  51.19 | +12.32 |
| R-T29-high / 3         | PASS | PASS |  37.87 |  19.46 | -18.41 |
| R-T29-high / 4         | PASS | PASS |  21.70 |  19.73 |  -1.97 |
| R-T29-low / 1          | FAIL | FAIL |  81.10 |  22.60 | -58.50 |
| R-T29-low / 2          | PASS | FAIL |  56.42 |  28.59 | -27.83 |
| R-T29-low / 3          | PASS | PASS |  21.70 |  39.88 | +18.18 |
| R-T29-low / 4          | PASS | FAIL |  24.88 |  48.49 | +23.61 |
| R-T64-high / 1         | PASS | FAIL |   9.28 |  11.28 |  +2.00 |
| R-T64-high / 2         | PASS | PASS |  26.57 |  25.53 |  -1.04 |
| R-T64-high / 3         | PASS | PASS |   6.20 |   4.16 |  -2.04 |
| R-T64-low / 1          | PASS | PASS |   7.29 |  12.28 |  +4.99 |
| R-T64-low / 2          | PASS | PASS |  16.45 |  19.44 |  +2.99 |
| R-T64-low / 3          | FAIL | PASS |   7.26 |   6.15 |  -1.11 |
| R-T67-high / 1         | FAIL | PASS |  36.91 |  30.66 |  -6.25 |
| R-T67-high / 2         | PASS | PASS |  30.75 |  62.10 | +31.35 |
| R-T67-high / 3         | PASS | PASS |  49.18 |  36.93 | -12.25 |
| R-T67-low / 1          | PASS | FAIL |  48.26 |  44.03 |  -4.23 |
| R-T67-low / 2          | PASS | PASS |  26.72 |  60.66 | +33.94 |
| R-T67-low / 3          | PASS | PASS |  57.42 |  37.84 | -19.58 |
| R-T69-high / 1         | PASS | PASS |  14.43 |  14.43 |  +0.00 |
| R-T69-high / 2         | PASS | PASS |  20.19 |  25.97 |  +5.78 |
| R-T69-high / 3         | PASS | PASS |  23.62 |  32.79 |  +9.17 |
| R-T69-low / 1          | PASS | PASS |  15.36 |  11.31 |  -4.05 |
| R-T69-low / 2          | FAIL | PASS |  22.56 |  20.53 |  -2.03 |
| R-T69-low / 3          | PASS | PASS |  31.78 |  23.56 |  -8.22 |

## 已观察到的改善与残留

- 历史 Word：修前 low 第 2 轮找不到历史页图；修后 low/high 共 6 轮每轮均有真实页面图片进入模型，A23/B33/C39、Reference、部门、单位均正确。high 三轮总时长反而增加，不能只选 low 结果。
- 旧 DOC：转换来源得到保留，修前 low 第 3 轮丢失“金额/到期”标签的事实漂移本轮未出现；修后 high 第 1 轮仍错误断言不存在漏看的图形，下一轮才撤回。low 首轮“另无图形”也有歧义，但同句限定转换可能丢失，和修前 high 同类边界一样保留给独立验收，不擅自计为确定错误。
- 长文：最终三个目标字段两侧全部正确。修后系统尾注准确显示实际提供的段数；low 第 1 轮正文仍越界断言其余全文均为例行条目，之后自行更正。high 首轮没有复现修前的范围断言。第 2 轮两种强度都变慢，来自模型新增回读/检索，不能说所有流程都更快。
- 报告 high：真实生成 revision2、风险字段写入 revision3，前三轮未提交，第四轮提交同一 revision3。第 2 轮错误提案被拒后修正，最终没有陈旧拒绝/待处理内容。
- 报告 low：第 1、2 轮仅给聊天草稿，没有创建报告或保存风险；第 4 轮才生成并提交 revision2，真实 `blockers` 为空，回复却声称包含刚才四条风险。该链路 3 轮失败，不能把短时长当提速成功。
- 搜索 low：更快但只交付 Anthropic 链接，OpenAI 未完成且如实说明。high 两个官方链接均完成，274.22 → 189.76 秒。
- CSV：两种强度实际下载 JSON 可读、声明字节数/哈希匹配；销售300、退款50、净额250及两条明细均正确，未新增工作或报告；12.37/18.57秒，相比修前14.41/19.56秒略短。

## 搜索来源指纹

按原始工具结果中每条来源的 `url + title + snippet` 计算 SHA-256；同 URL 的摘要发生变化也算新证据。保留每次查询、原始三字段、哈希及进展提示，未只按 URL 计数。

| 阶段 / 强度         | 搜索调用 | 唯一来源指纹 | 无新增来源调用 |
| ------------------- | -------: | -----------: | -------------: |
| before / R-T09-high |       20 |           24 |             15 |
| before / R-T09-low  |       13 |           13 |              9 |
| after / R-T09-high  |       13 |           18 |              9 |
| after / R-T09-low   |        6 |            7 |              4 |

修后高低两组没有出现“URL 不变但摘要新增”的情况，故本次来源指纹与新 URL 计数恰好相同。high 仍有 9 次无新增证据，说明提示减少部分重复消耗，并不保证消除循环。low 提前停止导致少交付一家来源，已计任务未完成。

## 证据入口

- [完整逐轮对照与原始搜索来源](../../artifacts/spec074/20261017-repair-comparison/comparison.json)
- [冻结 manifest](../../artifacts/spec074/20261017-repair-comparison/manifest.json)
- [修前事实](../../artifacts/spec074/20261017-repair-comparison/before/facts.json) / [修后事实](../../artifacts/spec074/20261017-repair-comparison/after/facts.json)
- [修前语义评估](../../artifacts/spec074/20261017-repair-comparison/before/semantic-review.json) / [修后语义评估](../../artifacts/spec074/20261017-repair-comparison/after/semantic-review.json)
- [修前业务读回](../../artifacts/spec074/20261017-repair-comparison/before/readback.json) / [修后业务读回](../../artifacts/spec074/20261017-repair-comparison/after/readback.json)
- 每个 `results/<case>/` 包含不可覆盖的 `first.jsonl`、SSE计时、消息/工具回执、业务字段和实际下载文件；`trace.jsonl` 保留真实请求/响应关联。

本轮只验证既定修复覆盖面，不代表全量审计所有条目重跑通过；已知模型措辞和工具选择偏差如实保留。

## 资源清理

本轮两个 API/worker 已停止，无活跃任务；两个 owned schema、私有 media/密钥目录和临时账号凭据已清理，owned Redis namespace 中的键已清理。6 个代码执行资源均已 release，文件已移除；沙盒按正常规则保留释放后的幂等元数据直到 TTL，不删除共享运行服务。冻结源码与证据仍保留用于复核。详见两侧 `resource-cleanup.json`。
