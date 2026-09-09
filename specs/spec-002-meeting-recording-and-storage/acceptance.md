# Acceptance — Spec 002

日期：2026-09-09。角色：新的独立返工 Acceptance Agent，独立于首轮实施、返工实施及首轮验收。项目模式：EXISTING。

## Result

**PASS**

首轮唯一阻塞问题 ISSUE-01 已闭环。录音异常收尾或首次启动恢复遇到暂时写入故障时，完整帧与后续恢复依据得到保留；排除故障并重新连接 / 启动后，恢复为可播放的 interrupted 记录，保留源文件和原始错误，不宣告 completed。AC-01 至 AC-10 均通过。

本轮独立审查实际返工代码、新增回归及媒体契约，复用已通过的必要检查和未变化区域的首轮证据，没有发现需要追加动态探测的具体缺口。本 Agent 仅更新本报告，未修改业务代码、测试或配置，未提交或推送 Git。首轮 FAIL 历史保留在 [acceptance-round-1.md](acceptance-round-1.md)。

## Spec Coverage

| 标准 | 结论 | 依据 |
| --- | --- | --- |
| AC-01 主动开始、默认麦克风与真实错误状态 | PASS | 复用首轮权限、真实输入和设备打开失败证据；此次未改变权限或设备选择。原生权限检查仍由用户开始动作触发，输入流成功打开后才进入 recording，失败不伪造成功。首次系统授权弹框仍未实测。 |
| AC-02 至少一个实机真实麦克风 | PASS | 复用并核对 macOS ARM64 实录 JSON：MacBook Pro 麦克风、48000 Hz / PCM16 单声道、210944 帧、4395 ms，输入量 0.0081497。物理输入证据与本轮合成故障回归分别记录。 |
| AC-03 幂等、超时与退出并发 | PASS | 复用首轮 operationId、唯一活动会话、动作超时查询、轮询合并、单实例和退出并发证据。返工未改控制契约；failed 待恢复记录不属于活动会话，已有重连流程能够重建同一数据根的核心与 Repository。 |
| AC-04 正常保存与重启播放 | PASS | 正常收尾路径未改变；复用真实保存和重启播放证据：Chromium 解码时长 4.394667 秒，播放位置推进至 0.66731 秒，无媒体错误。返工回归另外核对 recovered.wav 的 PCM 内容、帧数、格式、时长及文件长度。 |
| AC-05 页面 / 最小化 / 关闭保护 | PASS | 复用首轮 6 个 Electron 场景中的页面切换、最小化、取消关闭 / 重连、保存退出、保存失败保持可见等证据；相关桌面和界面实现未因返工改变。 |
| AC-06 中断、写失败与恢复 | PASS | 首轮驱动 / 队列溢出、核心强杀、休眠、一般写失败和最终元信息失败证据继续适用。新增回归覆盖 Recorder 写失败且恢复副本 ENOSPC，以及首次启动恢复 ENOSPC；持续故障时保留候选和真实完整帧，故障撤销后均恢复为 interrupted，原文件及原始错误保留。ISSUE-01 已闭环。 |
| AC-07 受限媒体与权限 | PASS | 独立核对 Repository.present、核心会议映射与 media.ts：待恢复 failed 记录 audioAvailable=false，内部查询也不返回 audioPath；恢复成功才返回现有 meetings/<UUIDv4>/recovered.wav。既有 ID、真实根归属、符号链接、允许文件名、44+bytes 和 Range 边界保持；无新增权限。复用首轮媒体 / Electron 检查。 |
| AC-08 数据路径与隔离 | PASS | 返工沿用 SQLite v1 和相对路径，不新增 schema、迁移或数据目录；原始文件保持不变。新增回归均使用合成 PCM 和独立 TemporaryDirectory，不触碰真实会议。首轮用户数据根、路径与不兼容 schema 保护证据继续适用。 |
| AC-09 文档与能力状态 | PASS | Spec / Plan / rework、两轮实施报告、决策 0006、README 及工程 / 产品文档记录恢复重试语义和实际能力。ASR / LLM、正式安装包仍未实现；真实 / 合成输入、Windows 和首次授权弹框边界明确。协调 Agent 在验收结束后同步最终状态，验收中的状态文案不构成功能缺陷。 |
| AC-10 报告、比例验证与闭环 | PASS | 首轮实施、首轮 FAIL、返工要求、返工实施与本次新的独立报告齐备。持久化恢复是验证受影响 Python 子系统的具体依据；已通过检查未无理由重复，唯一问题已闭环。 |

## Tests

### 本轮独立执行

1. 阅读 AGENTS.md、constitution、全部有效 .ai/rules、任务交接、Spec / Plan、决策 0005 / 0006、首轮验收、rework 及两轮实施报告；检查工作区状态和相关 diff，未将用户或其他 Agent 的修改视为本 Agent 所有。
2. 对未跟踪的 audio_store.py、recorder.py、repository.py 和 test_recording.py 直接阅读全文，避免普通 git diff 遗漏。逐项检查只读完整帧识别、失败元信息、启动扫描、错误 / 时间保留和空 / 无效源处理。
3. 阅读新增 3 项回归及其辅助断言：故障在实际 recovered.recovering 写入打开处注入 ENOSPC，断言涵盖故障持续期间再次启动、解除故障后恢复、逐字节 PCM、原文件不变及不可播放期间的错误提示。
4. 核对未改变的重连 → 同数据根启动 → Repository.recover 路径、协议返回、主进程会议映射、界面 audioError / 播放分支和 media.ts 的恢复文件约束；核对首轮真实录音 JSON 的输入量、帧数和播放进度。

本轮没有重新运行单测、探测、类型检查、lint、build、Electron 或真实录音。审查没有发现已通过回归未覆盖的具体阻塞风险，因此遵循停止规则，不为增加主观信心而追加检查。首轮 acceptance-recovery-probe.py 保持原样作为旧缺陷证据，其断言描述旧失败行为，本轮未复跑。

### 复用的返工实施证据

详见 [implementation-rework-1.md](implementation-rework-1.md)。以下由返工实施 Agent 执行，本 Agent 核对代码和断言后复用，不表述为本轮重新执行：

```text
.venv/bin/python -m unittest discover -s tests/python -p test_recording.py -v
```

**13 PASS**，退出码 0，1.162 秒；包括原有 10 项与新增 3 项直接相关回归：

- Recorder 写失败 + 恢复副本 ENOSPC：失败和故障中再次启动均保留 256 帧 / 512 字节 / 5 ms；解除故障后为 interrupted，保留 storage_write、原文件和一致 PCM。回归同时核对持续故障重试不改写 endedAt。
- 首次启动恢复 ENOSPC：头部声明 128 帧，文件另有 64 个完整帧和一个尾字节；两次失败均保留 192 帧恢复依据，解除故障后保存 192 帧 / 384 字节 / 4 ms，保留 process_interrupted 和原始文件，忽略不足一帧的尾字节。
- 空 WAV / 无效 WAV：failed、零帧、空关联、不可播放，不生成虚假成功，源文件不变。

恢复断言核对 audioAvailable=true、audioError=null、既有 recovered.wav 路径、单声道 PCM16 / 48000 Hz 和文件长度 44+bytes。浏览器实际解码 / 播放沿用未改变媒体流程的首轮证据，本轮不宣称重新进行播放器实测。

### 复用的首轮证据

详见 [implementation.md](implementation.md) 和 [acceptance-round-1.md](acceptance-round-1.md)：

- 未改变的 7 项 Python 协议检查、19 项 TypeScript 桌面检查通过；原有 10 项录音 / 存储检查已包含在返工的 13 项中。
- Electron 首轮 5 PASS / 1 测试自身失败，修正不存在的权限 API 调用后仅重跑失败项 1 PASS，合计 6 场景通过。
- 类型检查、定向 ESLint、最终生产构建和首轮 diff 空白检查通过；独立单实例检查中第二进程正常退出，原核心 PID 不变。
- 一次真实默认麦克风录音、保存、同隔离数据根重启及播放，证据为 artifacts/spec002/real-evidence.json、real-capture.mjs 与 real-restarted-playback.png。首轮已检查截图；本轮核对 JSON，未重看截图或重录。real-recording.png 为准备态截图，不作为正在采集的视觉证据。

## Issues

无未解决的阻塞问题。

**ISSUE-01：CLOSED。** 两条失败路径先只读检查实际完整帧；暂时恢复失败时保留 failed、恢复目标和已核实元信息，并明确不可播放及重连提示。Repository 启动同时扫描活动记录与带恢复目标的 failed 记录，故障解除后生成、校验 recovered.wav，再保存 interrupted。原 errorCode 与已记录 endedAt 不被重试覆盖，源文件不删除。空或无效源不会伪造恢复成功。首轮失败证据及原因仍保留在历史报告。

## Regression Risks

- 恢复需要可读源文件、可写存储和足够空间；持续故障时保留错误与待恢复入口，下次重新连接 / 启动再试，不自动轮询或续录。
- 只能恢复已经落盘的完整帧，不承诺内存队列、系统缓存或强制断电时零丢失。
- Windows CI / 实机 / 真实设备录音未运行，首次 macOS 麦克风授权弹框未实测。Spec 允许当前 macOS 开发交付保留这些边界，不宣称 Windows 录音已验收。
- 真实证据为短时物理输入与播放器验证，不代表长时间会议、人耳音质或正式安装包验收；内置运行时、签名、公证与分发仍属后续范围。

## Required Rework

无。相关实现与必要验证满足本次 Spec，停止追加检查。
