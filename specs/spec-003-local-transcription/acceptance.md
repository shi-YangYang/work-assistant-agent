# Acceptance — Spec 003 · Final

## Result

**PASS** — 2026-09-10。

由未参与业务实施或 CI 修复的独立验收 Agent 完成。本轮仅维护本报告，没有修改业务、测试或配置，没有重新验收 Spec 决策。

最终候选为 `0b84fe1c6349aa7c413da2d24bc700e43849d97e`，分支 `codex/spec-003-local-transcription`。[实际 CI run 34451673078](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34451673078) 及 macOS、Windows 两个 job 均为 success。已核对对应 SHA 的官方 API 快照，以及主 Agent 下载并核对官方摘要的两平台实际模型结果和 Electron 阶段附件。

首轮暂停竞态、后续测试供帧/输出编码问题及 macOS Electron 恢复等待问题均已闭环。原 [Round 1 FAIL](acceptance-round-1.md) 和 [Round 2 FAIL](acceptance-round-2.md) 保留；后续失败 CI、诊断和修复依据见 [verification.md](verification.md) 及下列实施报告，不覆盖失败历史。

## Spec Coverage

| 范围 | 验收结论与依据 |
| --- | --- |
| R1 模型准备与离线边界 | 固定 small 模型来源、revision、文件大小/SHA256，staging 下载、校验和实际加载后才就绪；取消、失败重试、损坏文件及录音不依赖模型有明确实现和测试。已核对真实应用下载字节进度；最终两平台真实 Provider 在禁止 worker socket 连接后使用本地模型完成推理。 |
| R2 录音与转写解耦 | 真实 spawn worker 承担重采样、VAD、推理；WAV 与持久帧位置承接积压，当前音频窗和回调队列有界，读取后关闭句柄再推理。最终慢 worker 测试保持真实进程，确认推理未返回时录音帧增长、积压可见、停止调用低于 100 ms、录音保存与暂停正常。 |
| R3 Transcript | 稳定片段/块 ID、时间映射、可空 speaker/confidence、文字与检查点事务提交、每页最多 50 段已有实现与检查；renderer 按游标追加，保留上文阅读位置并提供回到最新，录音期间禁播。两平台 Electron 真实文字恢复与片段定位通过；本机物理录音定位后实际播放推进。 |
| R4 尾部与重试 | 静音和尾块推进连续帧检查点，目标帧处理完才 completed，录音与转写状态分离；重复开始不覆盖完成结果，失败继续保留已提交内容及任务配置。物理录音观察到音频先保存、转写随后补尾；最终两平台恢复任务均处理完 273984 帧，processedMs=17124、pendingMs=0。 |
| R5 生命周期与恢复 | 暂停、认领和提交共用短控制锁，取消令牌不可复用，旧结果/异常不能覆盖继续后的任务；推理等待不持有控制锁。Event 回归覆盖原竞态和 worker 回收。最终两平台实际 Electron 通过取消关闭、保留进度退出、重启 paused、继续完成及正常清理。 |
| R6 数据兼容与安全 | schema 1→2 的 DDL/user_version 同事务；备份 staging、有界数据库忙等待、失败回滚保留旧库与音频有测试。旧记录不自动转写，main/Python 校验会议 ID 和游标，renderer 不获得任意下载 URL、路径或进程命令，sandbox 保持。 |
| 真人质量与性能 | 固定 121.76 秒 FLEURS 人声与人工参考稿，最终分块 CER 18/276=6.52%，无字符插入/删除，WiFi 保留；M5/16 GiB 上模型加载 0.412 秒、累计推理 44.659 秒。最终 Provider 的 10 秒纯静音真实检查 words=[]，当前 Provider SHA256 与该证据一致。 |
| 物理麦克风闭环 | 用户指定的公开真人语音经内置扬声器→物理麦克风回采，非文件注入、非用户现场发言。录音 37.035 秒、首批文字 18.383 秒、CER 14/90=15.56%；补尾完成，重启片段 ID/文字/时间一致，定位 9.266 秒后实际播放至 9.9418 秒。 |
| 平台与交付证据 | 最终对应提交的 macOS ARM64、Windows x64 依赖、自动检查、真实 small 推理及新增 Electron 场景均成功。旧 Windows 4 项平台受限 smoke 的跳过单列；新增转写场景没有跳过。实施、返工、真实运行及本独立验收报告齐备。 |

## Tests

### 本轮独立审查与执行边界

阅读 Spec/Plan、原实施与暂停返工、历次 CI 修复报告、前两轮验收、相关业务和测试源码、候选间 diff、原始运行 JSON。此次没有新发现需要补测的具体缺口，因此没有重复本机模型推理、录音、测试、build、lint 或 typecheck；本轮执行的是证据读取和报告 diff 检查，不能表述为本 Agent 重新执行了全部测试。

复用的明确证据来自 [implementation.md](implementation.md)、[implementation-rework-1.md](implementation-rework-1.md)、[implementation-ci-rework.md](implementation-ci-rework.md)、[implementation-ci-smoke-rework.md](implementation-ci-smoke-rework.md)、[implementation-ci-time-budget.md](implementation-ci-time-budget.md) 和 [verification.md](verification.md)。原实现 S3 的存储/IPC/进程证据及 S2 暂停返工证据继续有效；后续 CI 修复没有修改业务代码、Provider、模型参数或参考稿。

### CI 修复没有降低业务通过条件

- 慢 worker 的输入改为按精确帧数经真实 callback/有界队列/WAV writer 供给；跨进程 Event 确认真实 spawn Provider 已进入推理并保持未返回。保留 running、帧增长、积压、100 ms 停止、保存、队列上界和 paused 断言，并增加 processedMs=0；没有以 queued 代替 running 或放宽等待来掩盖供帧不足。
- Windows stdout 仅改为 ASCII 转义 JSON；UTF-8 报告保留中文，解码后的内容不变。真实模型、CER≤20%、关键文字、时间范围、处理进度和幂等断言均不变。
- Electron 正文通过真实窗口关闭及有界 close event 检查退出；失败清理先回答确认，仅在清理失败时回收该测试进程。强制回收不能让失败通过，正文错误保留。新增阶段 JSON 实际定位了下一个失败，最终成功运行均为正常清理。
- macOS 诊断证据显示恢复任务在 30 秒内由 0 推进到 8460 ms、error=null，尚余 8664 ms。因该具体远端证据，将恢复等待改为 60 秒、总预算改为 120 秒；仍严格要求 completed，未修改模型、fixture 或其他业务断言。Spec 的性能基准明确针对 M5/16 GiB，未为云 runner 规定 30 秒恢复承诺；该预算修正不替代或降低原参考机性能验收。

### 最终提交的实际双平台检查

以下数量综合实际 CI 结果、协调 Agent 读取的日志和测试/工作流配置；本 Agent 独立核对了对应 SHA 的 API 全步骤 success，以及两平台原始 ASR/阶段结果。

| 检查 | macOS ARM64 | Windows x64 |
| --- | --- | --- |
| 环境 | macOS 26.6.2、Python 3.12.10 | Windows Server 2025、Python 3.12.10 |
| Node/Python 依赖、类型、lint、格式 | 全部成功 | 全部成功 |
| 单元与协议 | 19 TS、35 Python 通过 | 19 TS、35 Python 通过 |
| 真实 small ASR | 4.281 秒音频，8.9557 秒；CER 2/12 | 同一音频，3.500 秒；CER 2/12 |
| 构建及 Electron smoke | 7 项通过 | 3 项通过，4 项既有平台受限场景跳过 |
| 新增真实模型 Electron 场景 | 所有阶段成功；恢复阶段 44.445 秒，含正常清理总计 70.598 秒 | 所有阶段成功；恢复阶段 23.239 秒，含正常清理总计 37.004 秒 |
| 最终恢复状态 | completed；17124 ms 已处理，pending=0、error=null | completed；17124 ms 已处理，pending=0、error=null |

两平台均使用 `Systran/faster-whisper-small` revision `536b0662742c02347bc0e980a01041f333bce120`，CPU INT8、4 线程、beam 5、10 秒目标块/4 秒上下文。短公开语音 SHA256 为 `2f9fc9c912bb71c85fb286cb88b599c81efb8f727c727a5ea8f6d1c89c55ac13`，实际输出“廣州市法地产中介协会分析”；识别误差原样保留。CI 显式设置 `PAA_REAL_ASR_SMOKE=1`，没有用模拟 Provider 或平台 skip 替代这项推理。

### 原始证据位置

下列路径均相对于项目根目录，位于 ignored `artifacts/`，不将模型、录音或数据库提交 Git：

- 最终官方 API：`artifacts/spec003/ci/0b84fe1c6349aa7c413da2d24bc700e43849d97e.json`。
- 最终平台原始输出：`artifacts/spec003/ci/34451673078-macos/spec003/`、`artifacts/spec003/ci/34451673078-windows/spec003/` 下的 `real-asr.json`、`transcription-smoke-stages.json` 及截图。
- 前次明确恢复超时：`artifacts/spec003/ci/34450871426-macos/spec003/transcription-smoke-stages.json` 与同次 `playwright/` 错误附件；更早 CI 与修复复现分别留在 `artifacts/spec003/ci/`、`artifacts/spec003/ci-rework/`。
- 固定质量：`artifacts/spec003/benchmark.json`、`reference-evaluation-revised.json`、`reference-audio/`；首轮失败版本保留。
- 物理录音：`artifacts/spec003/microphone-evaluation.json`、`artifacts/spec003/interactive/session.json`、`artifacts/spec003/interactive/microphone-restart.json`、`artifacts/spec003/interactive/microphone-playback.json` 及截图。
- 最终纯静音：`artifacts/spec003/final-provider-silence.json`；对应 Provider SHA256 `14a8662c4e129578a5567b0ec7e37aad6af369fefc0cc1d0b458628bbfc35ac2` 与本候选一致。

## Issues

无与本 Spec 直接相关的未解决阻塞问题。原暂停竞态及实际 CI 失败已分别取得修复和对应结果证据；不以旧候选或单一本机成功替代最终双平台结果。

## Regression Risks

- 参考机 121.76 秒原文件基准的累计推理耗时，与 31.74 秒公开语音声学回采的首字延迟是不同测量，不混称同一次两分钟实录。CI 云端机器明显较慢，跨平台功能通过不等于所有电脑具备实时性能。
- small 仍有同音/繁简误差；固定清晰语音、WiFi 和纯静音结果不能外推所有口音或噪声都无错误/幻觉。
- Windows 物理麦克风、首次 macOS 权限弹框、最低系统配置、其他架构/GPU、签名安装包和自带运行时仍未在本轮验证。当前交付为开发预览，保持既有分发边界。

## Required Rework

无。需求已实现，必要验证通过；停止追加探索和重复测试，交协调 Agent 同步最终状态与交付。
