# Implementation — Spec 004

状态：业务实施与必要本地检查完成，最新独立复验已关闭工程缺陷，用户反馈基本验收无问题；Agent 的真实 API 样本核对证据仍待补，整体结果见 [验收报告](acceptance.md)。提交、推送与本轮 Windows／远端 CI 状态以 Git 和对应提交的检查记录为准。

## 实施结果

- 设置支持 16 家独立服务、系统保护的密钥密文、明确的当前选择和自动生成开关。配置保存、重连恢复按同一序列执行，失败保留旧设置；更换地址必须重输密钥。
- 模型发现和检测使用当前草稿，经后台网络任务执行；真实目录可搜索／选择／手填，按 50 项分页。服务按模型保存自定义推理预设，支持简单字符串和嵌套 JSON，默认不加参数；校验受保护字段，不设置型号强度白名单。
- 一个兼容 Provider 提供 Chat Completions、可选 SSE、实际文本回复检测、错误归一化、请求／响应大小与时间限制。百炼目录仅在已识别官方主机内转换路径，读取模态元数据；不自动重定向、降档、修复响应或重试调用。
- 完整转写由核心读取并固定输入／配置快照；完成事件登记自动尝试，启动或保存设置不扫描历史。单网络 worker 不阻塞录音控制。队列更换服务时取消未发出的旧请求，在途请求不改接收方；退出和晚到结果有终态保护。
- schema 3 增量新增尝试、任务和成功结果表，保留 schema 1 升级链及迁移备份。重新生成失败保留旧纪要。模型结果须通过字段、长度及引用校验；详情可读取第 50 段之后的真实来源并定位录音。

主要文件：桌面 `summary-settings.ts` 与受控 IPC；共享 `summary-contracts.ts`、`reasoning.ts`；界面 `ModelSettings.tsx`、`MeetingMinutes.tsx`；Python `llm_provider.py`、`meeting_summary.py`、`summary_store.py` 及原有协议／迁移／转写完成事件。README 与架构文档已同步。httpx 0.28.1 由已锁定的间接依赖声明为直接依赖，没有升级 lockfile 或引入 SDK。

## 首轮本地验证

本轮为 S3（schema、凭证、跨进程契约）。下表保留首轮检查；返工后的结果见后文，未受影响的检查沿用这些证据。

| 检查 | 结果与证据（仓库内 artifacts/spec004） |
| --- | --- |
| `npm run test:python` | 50 项通过，5.275s；`python-test.log`。包括 schema 1 / 2 迁移、回滚、旧录音／转写及新增模型／纪要测试。 |
| 后续调度缓存／故障处理改动：`PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_summary test_protocol -v` | 23 项通过，0.918s；`python-final.log`。增加 worker claim 存储失败与目录分页／清理用例；当前 Python 共 51 项，未重复未受影响的 28 项。 |
| Vitest | 原有 19 项通过；新增设置用例修正后 5 项通过（`test.log`、`settings-test.log`）。随后新增重连解密并发用例并改动客户端白名单，`npx vitest run tests/desktop/summary-settings.test.ts tests/desktop/json-line-client.test.ts` 17 项通过，`desktop-final.log`；当前共 25 项均有对应通过结果。 |
| `npx playwright test tests/smoke/summary.spec.ts` | 1 项通过，6.7s；`summary-smoke.log`。真实 Electron + 临时 HTTP 服务：模型目录、未知强度／嵌套参数、模型切换恢复、密钥隔离、完整 61 段输入、末尾原文播放、失败保留、重启和过期响应；无平台跳过。 |
| `npx playwright test tests/smoke/app.spec.ts` | 原有 6 项全部通过，10.7s；`app-smoke.log`。保留原权限、录音、退出、失败恢复断言。 |
| `npm run typecheck`、`npm run lint`、`npm run build` | 最终代码通过；`typecheck.log`、`lint.log`、`build.log`。 |
| 修改文件定向 Prettier check、`git diff --check` | 通过；`format-check.log`。全部修改的 Prettier 覆盖文件已使用项目格式化器整理。 |
| 900px 视觉检查 | 专门编写的模拟数据，设置和纪要无横向溢出，卡片内边距与阅读布局正常；`settings-900.png`、`minutes-900.png`、`visual-check.json`。未为截图重跑已通过 smoke。 |

首次新增 smoke 发现纪要错误被旧协议白名单隐藏、推理选择器标签不精确、保存后用于纪要按钮未解除禁用；均已修复并由上述完整 smoke 验证。测试中的原型键用例改成真实 JSON own-key，`option.disabled` 使用实际 DOM 属性断言。测试失败记录保留于本次日志／对话上下文，不以修改业务断言掩盖失败。

首轮最后一次新纪要 smoke 后，仅增加服务移除的目录操作清理调用及网络 worker 存储异常保护；对应 Python 定向测试、基础 smoke、类型／lint／构建随后通过。后续独立 FAIL 及本次修改如下。

## 独立验收后的返工

针对 [首次 FAIL](acceptance.md) 的两项复现，未扩大到其他功能：

- `llm_provider.py` 改用已安装 httpx 的异步 socket 读取，在原单网络 worker 内由 `asyncio.timeout` 取消整个请求。保留独立连接超时、跨目录分页共用截止时间及不自动重试，不新增网络工作线程。新增部分响应停顿用例：总预算 0.5 秒，0.4 秒收到一个字节后停顿，要求在 0.65 秒内返回超时且仅发出一个请求。
- 核心保存目录中明确的非文本信息，以服务 ID／规范化地址／密钥指纹隔离，最多 32 组、每组沿用 2000 模型边界；仅可信 Provider 返回更新，失败刷新保留既有信息，成功刷新替换，删除清除并使在途旧目录不能重新填入。此缓存仅在当前核心进程存在，不作为永久型号白名单。
- 新增受控、无网络的资格校验，保存、切换、连接检测及真正生成前均阻止已知非文本 ID；新目录使现用模型变为非文本后，手动生成被拒绝、自动任务明确失败，均不发出生成请求。未知手填 ID 仍可保存、检测和使用；界面给出可操作提示，禁止用手填绕过禁用选项。

本次必要检查（macOS ARM64；日志均在 `artifacts/spec004/`）：

| 检查 | 结果 |
| --- | --- |
| `PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_summary test_protocol -v` | 26 项通过，1.478s；`rework-python.log`，当前 Python 共 54 项，其余复用首轮未受影响证据。 |
| `npx vitest run tests/desktop/summary-settings.test.ts tests/desktop/json-line-client.test.ts` | 18 项通过；`rework-desktop.log`，当前 TypeScript 共 26 项。 |
| `npm run typecheck`、本次 7 个 TS/TSX 文件的定向 ESLint / Prettier check | 通过；`rework-typecheck-final.log`、`rework-lint.log`、`rework-format.log`。初次类型检查发现新 smoke 的递归类型推断过深，改用项目已有 JSON 序列化传参方式后通过，失败记录见 `rework-typecheck.log`。 |
| `npm run build` → `npx playwright test tests/smoke/summary.spec.ts` | 构建及 1 项 smoke 通过（9.0s）；`rework-build.log`、`rework-summary-smoke.log`。新增真实 Electron 手填禁用模型／绕过 UI 调用受控接口的拒绝、未知模型正例、现用模型刷新为非文本后的拒绝及恢复。 |
| `git diff --check` | 通过；仅检查本次 diff，没有重新运行未受影响的基础 smoke、全量测试或真实 ASR。 |

全部业务修改先于对应通过检查；随后只更新本报告。返工测试仅使用隔离临时数据与 loopback 模拟服务，没有访问协调 Agent 的私有验收目录，也没有调用真实 API、提交或推送。独立验收结论仍由新的验收者给出。

### DNS 截止时间返工

第二次 FAIL 的原因是取消请求后仍等待 [asyncio DNS 的默认执行器](https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.loop.getaddrinfo) 收尾。本次只改 `llm_provider.py`：请求私有事件循环使用有界解析器，每个 Provider 最多一个正在运行的 daemon DNS 线程；异步等待可取消，忙时拒绝增加解析，结束后可再次使用。DNS 线程不持有事件循环、Future 或请求凭证，无晚到回调和退出 join；httpx 原有主机名、地址选择及 TLS 校验保留，默认连接 10 秒／总计 180 秒未变。操作系统解析本身不能被此机制终止，永久阻塞时后续主机名调用及时失败，直到解析结束或核心重启；不会积累线程，数字 IP 连接仍可进行。

新增一个无外网的延迟 DNS 回归：总预算 0.1 秒、连接预算 0.05 秒，连续三次操作各在 0.25 秒内返回，仅一次底层解析且没有 HTTP 请求；等待期间数字 IP 请求成功，释放旧解析后不会补发请求，后续主机名调用恢复。`PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_summary test_protocol -v` **27 项通过，1.682 秒**，包括受影响的传输、队列退出与协议测试，日志为 `artifacts/spec004/dns-rework-python.log`。当前 Python 共 55 项，其余复用未受影响证据；未重复 TS、构建、UI 或 ASR 检查。未改动验收结论或私有窗口数据。

## 验证边界

用户验收后的两项局部界面调整由协调 Agent 直接完成：新建服务默认开启流式接口，既有配置保持原选择；推理预设使用页内锚定下拉，固定从控件下方展开。按 S1 验证实际组件及样式，在隔离 Electron 的 1240／900 像素窗口检查定位、选择、键盘关闭和默认／已存设置，均通过；证据为 `artifacts/spec004/settings-ui-result.json` 与 `preset-below-*.png`。原纪要 smoke 的 JSON 模拟服务显式关闭流式，避免依赖旧默认值；本次不重跑全套测试或构建。

- 本地实机为 macOS ARM64。Windows 新用例可执行，实际结果由本轮提交的远端 CI 提供；本地通过结果不代替远端结果。
- 本报告未调用任何真实付费 API。Provider 故障、推理参数形状和结构校验以模拟响应验证，不能代表 DeepSeek、GLM、Qwen、GPT、MiniMax、Kimi 等实际服务兼容性或纪要准确率。
- 后续真实服务验收遵循 [用户日常环境约定](../../AGENTS.md#21-测试与验证规则)，使用应用已有配置，不再等待隔离窗口重复配置。Agent 尚未执行真实“本地转写完成 → 自动生成 → 人工核对 → 重启读取”样本核对；用户的基本验收反馈与 Agent 实测证据分别记录。
- 超长会议采用既定单次完整输入策略；语义准确性仍需核对原文。退出不承诺取消服务端计费，未完成请求不自动重发。独立验收应重点检查凭证边界、任务／配置竞争、旧结果保护和真实样本质量。
