# Acceptance — Spec 003 · Round 2

## Result

**FAIL** — 2026-09-10。本轮验收 Agent 未参与原实现或返工，未修改业务、测试、配置，未重新验证 Spec 决策。

验收候选：`d7013c94f87c85f081f158012a8e23613e01fdca`，分支 `codex/spec-003-local-transcription`。首轮唯一 P2 暂停竞态已修复；本轮没有发现新的确定业务缺陷，但候选提交的 [实际双平台 CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34448151461) 未通过，尚不满足平台验收标准。不得以本机已通过结果替代。

首轮 FAIL 和确定性复现保留在 [acceptance-round-1.md](acceptance-round-1.md)；返工说明见 [implementation-rework-1.md](implementation-rework-1.md)。本报告保留当前失败事实，后续修复应交新的独立验收 Agent。

## Spec Coverage

| 范围 | 本轮独立核对与证据 |
| --- | --- |
| R1 模型准备 | 固定官方来源、revision、文件大小和 SHA256；staging 下载、完整性和实际加载检查后发布。取消/失败可重试，文件校验读取有界；音频和文字未加入下载请求。应用内真实下载的状态/字节证据与实现一致。Provider 只加载本地文件，真实推理禁止 socket 连接的检查通过。 |
| R2 解耦与积压 | spawn 工作进程隔离重采样、VAD 和模型推理；当前 PCM 窗口受块长与上下文限制，积压由 WAV 和持久帧位置承接。活动会议优先，全局串行推理。读取与 WAV 最终重命名共用短锁，推理不保留录音句柄。慢 worker 定向测试本机通过，但该测试在本次 macOS CI 超时，需要定位后重新取得平台证据。 |
| R3 Transcript | 任务快照、稳定块/片段 ID、时间映射、可空 speaker/confidence、文字和检查点同事务提交、每页最多 50 段；renderer 非重叠轮询按游标追加，保留上文阅读位置并提供回到最新；录音期间禁播，历史文字可定位播放器。 |
| R4 尾部和重试 | 有效帧区间连续，静音及尾块推进检查点，目标帧处理完才 completed；录音与转写状态独立，重复开始不全量重跑。实录中观察到录音先 completed、转写仍 draining，随后全量补齐；重启后文字/ID/时间一致。 |
| R5 生命周期 | 首轮暂停竞态已修复：暂停、认领与提交共用控制锁；每次暂停取消当前令牌，继续使用新令牌，旧迭代的结果及异常不能覆盖新代。worker 发送与取消共用短令牌锁，模型加载/推理等待在临界区外，取消后有界回收。相关 Event 回归和真实 Electron 保留进度退出/恢复已通过本机检查。 |
| R6 数据兼容及安全 | schema 1→2 的 DDL/user_version 同事务，备份 staging 成功后替换、有界忙等待及失败清理；原会议和音频不移动，不自动转写旧记录。main 与 Python 校验会议 ID、参数和游标，renderer 不提供任意 URL/路径/命令；现有 sandbox 保持。 |
| 真人质量/性能 | 复用固定 121.76 秒 FLEURS 人声、人工参考和独立 CER 计算：业务分块 18/276=6.52%，无字符插入/删除，WiFi 保留，累计推理 44.659 秒、加载 0.412 秒。结果绑定最终 Provider 配置，原漏句失败历史保留。 |
| 真实麦克风闭环 | 用户明确选择的公开真人语音经内置扬声器→物理麦克风回采，非文件注入、非用户现场讲话；37.035 秒录音、首批文字 18.383 秒、CER 14/90=15.56%。完成尾部、重启后片段一致，点击第二段定位 9.266 秒且实际播放推进至 9.9418 秒。已核对原始 JSON；首轮声压/播放延迟不足的结果未当作通过。 |
| 双平台 | 候选的 macOS CI 在 Python 慢 worker 测试失败；Windows 单元检查和真实 ASR 的业务断言通过，但输出报告时 cp1252 stdout 编码失败导致步骤失败。新增 Electron 场景在 CI 显式开启，源码未沿用旧 Windows 跳过，然而本次失败后未取得其远端成功证据。**本项未满足。** |

## Tests

### 复用已明确通过且未变化的证据

按 S3 原实现与 S2 生命周期返工的实际范围核对 [实施报告](implementation.md)、[返工报告](implementation-rework-1.md)、测试源码及 [实录证据](verification.md)，不为独立验收重复已通过检查：

- 原实施本机 19 项 TypeScript、31 项 Python，类型/lint/format/build，以及 6 项原有 Electron smoke。
- 返工后 9 项相关 Python 定向检查通过：暂停选块间隙、暂停立即继续后的旧结果/旧异常、取消后发送边界、运行中 worker 回收、慢 worker 与录音控制、崩溃/超时、检查点重试、尾块幂等、模型取消/损坏重试。
- 上述新回归使用 Event 固定并发时序。审查确认断言覆盖 paused 持续、activity=false、不发送旧推理、继续只提交一次、旧异常不覆盖新任务、真实 spawn 子进程回收。
- 返工后 `npm run test:asr` 本机真实 small CPU INT8/禁止 socket 推理通过，4.281 秒公开中文约 1.434 秒；新 Electron 转写场景 1 项通过，14.3 秒，覆盖历史生成、持久化、定位、关闭取消/保留进度、重启 paused 及继续完成。
- 真实首次下载、固定中文质量、物理回采、重启和实际播放推进证据已核对；不重复模型下载、长基准和实录。

### 本轮独立执行的最小检查

技术依据：最终 Provider 的纯静音真实输出缺少明确证据；早期 beam 1 的静音检查不能替代后续 VAD/beam 5 配置。经协调 Agent 确认，仅补此缺口。

用项目 `.venv/bin/python` 和当前 `WhisperProvider` 加载已有本地 small，模型加载前禁止 `socket.socket.connect`，输入单声道 PCM16/16 kHz 的 160000 个零样本（10 秒）。未打开麦克风、未注入返回文字、未修改产品或测试文件。

实际结果：**通过**，`words=[]`；加载 0.558721 秒，推理 0.110693 秒。参数 CPU INT8、4 线程、beam 5、中文；模型 revision `536b0662742c02347bc0e980a01041f333bce120`。证据在 ignored `artifacts/spec003/final-provider-silence.json`，记录候选 SHA 与 `asr_worker.py` SHA256 `14a8662c4e129578a5567b0ec7e37aad6af369fefc0cc1d0b458628bbfc35ac2`。这证明纯静音样本无假文字，不外推为所有噪声均无幻觉。

本轮未重复完整测试、build、lint、typecheck；未启动额外 Electron 或录音进程。

### 当前候选远端 CI

协调 Agent 读取候选对应的 Actions 任务及登录会话完整日志后提供以下事实：

| 平台 | 已确认结果 |
| --- | --- |
| macOS | 19 项 TypeScript 通过；35 项 Python 中 34 通过，`test_slow_worker_does_not_block_recording_controls_or_frame_growth` 在 `test_transcription.py:365` 等待 running 的 6 秒上限处失败。包括本轮 4 项新增暂停回归的其他测试通过；后续真实 ASR/Electron 步骤未获成功证据。 |
| Windows | `npm test` 通过；默认模型准备、真实 small 推理及全部业务断言通过，UTF-8 JSON 报告写入成功，但 `real_asr_check.py:120` 在 cp1252 stdout 打印 `ensure_ascii=False` 的中文 JSON 时抛 `UnicodeEncodeError`，导致 `npm run test:asr` 失败，后续 smoke 未跑。不能称整个 CI 或新增 Electron 场景通过。 |

旧 Windows 4 项平台受限 smoke 的 skip 是历史范围限制；本次尚未运行成功的新增场景不能记为通过或用旧 skip 代替。

## Issues

1. **P2 — macOS CI 慢 worker 场景超时。** 具体失败是等待任务进入 running 超过 6 秒，尚未证明其根因是业务调度、资源、fixture 或等待条件。必须先定位；不能仅增加超时掩盖录音隔离失效，也不能根据本机成功判定为无关。
2. **P2 — Windows 真实 ASR 测试的 stdout 编码导致 CI 失败。** `real_asr_check.py:120` 打印中文 JSON 时使用 cp1252 stdout，抛 `UnicodeEncodeError`。前面的模型准备、实际推理及业务断言已通过，第 119 行 UTF-8 结果文件也已写入；失败发生在测试报告输出，仍使后续 Electron 验证无法执行，需要修复跨平台输出后取得完整 CI 结果。

首轮暂停竞态本轮已确认修复，不列为未解决问题。当前没有新增已证实的产品行为缺陷；FAIL 依据是明确未满足的远端平台标准。

## Regression Risks

后续处理 CI 失败应保持真实默认模型、真实语音断言、录音优先和本轮暂停令牌边界，不能转用假 Provider 或静默跳过 Windows 新场景。只有关联代码变化、具体失败或未覆盖问题才能扩大/重复验证。

原文件基准的两分钟推理耗时与短公开语音回采的首字延迟是不同测量，不混称同一次两分钟实录。中文同音/繁简误差、噪声与硬件差异仍存在；Windows 物理麦克风、首次 macOS 权限弹框、最低系统配置、其他架构、安装包与自带运行时未在本轮验证，不能额外承诺。

## Required Rework

1. 保留 Windows cp1252 stdout 错误并修复测试报告的跨平台输出；定位 macOS 慢 worker 测试的 running 等待失败，以证据确定最小修改。
2. 由新的实施 Agent 完成针对性修复和必要检查，保留失败记录；不得仅跳过场景或降低真实业务断言。
3. 将修复候选提交运行实际 macOS ARM64/Windows x64 CI，取得依赖、真实 ASR 和新增 Electron 场景的明确结果及运行/跳过数量。
4. 再由新的独立验收 Agent 检查修复，复用未变化的质量、物理录音和本轮纯静音证据，更新最终报告。当前不得标记 Spec 完成。
