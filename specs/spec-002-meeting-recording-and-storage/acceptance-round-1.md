# Acceptance — Spec 002

日期：2026-09-09。角色：新的独立 Acceptance Agent；未参与业务实施。项目模式：EXISTING。

## Result

**FAIL**

默认麦克风采集、正常保存、重启回放、媒体边界与主要生命周期路径具备可信的实施证据。独立检查发现并复现一项阻塞问题：音频写入失败且恢复副本暂时无法写入时，已落盘的有效原文件会失去产品内恢复入口；释放空间并重启仍不可播放。AC-06 未满足，需返工后由新的独立 Agent 验收。

本轮仅新增本报告与忽略目录中的最小探测 / 证据；未修改业务代码、测试或配置，未提交或推送 Git。

## Spec Coverage

| 标准 | 结论 | 依据 |
| --- | --- | --- |
| AC-01 主动开始、默认麦克风与真实错误状态 | PASS | 原生权限检查仅在 startRecording 中执行；Python 在输入流成功启动后才显示 recording。复用 macOS 实录、权限拒绝注入及设备打开失败测试。无设备与设备拒绝共用明确的 device_unavailable 错误路径，不假造成功。首次系统授权弹框仍未实测。 |
| AC-02 至少一个实机真实麦克风 | PASS | macOS ARM64，MacBook Pro 麦克风，48000 Hz / PCM16 单声道，210944 帧、4395 ms；真实输入量 0.0081497。已检查 real-capture.mjs 与 real-evidence.json 的物理输入来源和状态；合成 PCM 不计入此项。 |
| AC-03 幂等、超时与退出并发 | PASS | operationId 唯一持久化，Recorder 锁与唯一活动会话、主进程开始 / 生命周期 promise、桌面单实例限制均可核对。动作超时查询权威状态，不重放 mutation；状态查询合并。复用幂等、超时查询、单实例及关闭 / 重连场景证据。 |
| AC-04 正常保存与重启播放 | PASS | 正常路径停止输入、排空已接受队列、关闭与 fsync、重命名、提交最终元信息；有效帧决定时长。真实保存与重启播放证据一致，Chromium 解码时长 4.394667 秒，currentTime 推进至 0.66731 秒，无媒体错误。已查看重启播放截图。 |
| AC-05 页面 / 最小化 / 关闭保护 | PASS | 录音线程不依赖 renderer 页面；关闭、退出与重连检查同一会话，并等待保存；保存错误显示且阻止当次退出。复用 Electron 页面切换、最小化、取消关闭 / 重连、保存退出、保存失败保持可见场景，已查看合成输入设置页录音截图。 |
| AC-06 中断、写失败与恢复 | FAIL | 驱动 / 队列溢出、核心强杀、休眠、一般写入失败和最终元信息失败已有证据；但恢复文件因临时存储故障无法生成后，有效原音频不再进入重连 / 启动恢复，详见 ISSUE-01。 |
| AC-07 受限媒体与权限 | PASS | preload 不暴露路径或任意 IPC；主进程检查来源与参数；合法 UUIDv4 由数据库映射，限定音频文件名、真实根归属、符号链接、文件大小与 Range。内部 audioPath 被剥离；renderer 沙箱 / 上下文隔离保持，摄像头等权限仍拒绝。复用媒体与 Electron 边界检查。 |
| AC-08 数据路径与隔离 | PASS | userData 由主进程传给 Python，数据库只存相对媒体路径，与仓库 / cwd 无关；测试显式使用独立临时根。schema 版本冲突不清库；检查已跟踪修改与未跟踪实现，未发现迁移 / 覆盖真实用户数据。 |
| AC-09 文档与能力状态 | PASS | README、技术栈、架构及产品文档区分当前录音能力、开发预览和未来安装包；ASR / LLM 为未接入。macOS 真实输入、合成故障、首次授权弹框及 Windows 未验证分别记录。正在验收的状态文案正常保留。 |
| AC-10 报告、比例验证与闭环 | FAIL | 实施报告与本独立报告齐备，验证范围有权限 / 持久化 / IPC / 生命周期的 S3 依据，既有通过项未重复执行；ISSUE-01 尚未闭环。 |

## Tests

### 复用的实施证据

详细命令、首次失败及修正后的执行范围见 [implementation.md](implementation.md)。独立验收核对相关实现、测试与产物，不把以下项目表述为本轮重新执行：

- Python：17 PASS，含 7 协议、10 Recorder / Writer / Repository 检查。
- TypeScript 桌面：19 PASS，含协议边界、媒体访问、超时查询和轮询合并。
- Electron：首轮 5 PASS / 1 测试自身失败，修正不存在的权限 API 调用后仅重跑失败项 1 PASS，合计 6 场景通过。
- TypeScript 类型、定向 ESLint、最终生产 build 和实施阶段 diff 空白检查通过。
- 独立单实例实机检查：第二进程正常退出，原核心 PID 保持。
- 一次真实麦克风采集、保存、同数据根重启并播放；证据为 `artifacts/spec002/real-evidence.json`、`real-capture.mjs`、`real-restarted-playback.png`。`real-recording.png` 是准备态截图，不作为正在采集的视觉证据。

### 本轮独立执行

1. 阅读必读规则、Spec / Plan / 决策与实施报告，检查已跟踪 diff 及未跟踪的 Recorder、Writer、Repository、media、依赖锁和测试文件；核对控制、生命周期、媒体与用户数据边界。
2. 查看真实重启回放与合成设置页录音截图；检查真实录音 JSON 和采集步骤，区分真实输入与故障注入。
3. **一次最小故障探测**：`.venv/bin/python artifacts/spec002/acceptance-recovery-probe.py`，退出码 0，成功复现 ISSUE-01。追加依据是独立代码阅读发现恢复副本写入失败会清空关联，而既有写失败测试始终允许恢复副本创建，没有覆盖该存储条件。

探测使用合成输入与 TemporaryDirectory，模拟先写入有效帧再写失败，并让恢复副本写入临时失败；故障撤销后重新创建 Repository。临时数据已自动清理，没有打开真实麦克风，没有残留子进程。脚本与 JSON 证据保留于忽略目录：

- `artifacts/spec002/acceptance-recovery-probe.py`
- `artifacts/spec002/acceptance-recovery-evidence.json`

确认问题后停止追加验证；未重复单测、类型、lint、build、smoke 或实录。

## Issues

### ISSUE-01 — 恢复副本暂时不可写后，有效原录音失去后续恢复入口（P1）

**位置**：`src/python/paa_core/recorder.py:221-236`；关联 `src/python/paa_core/repository.py:127-144`。

**触发**：录音已写入有效 PCM；随后磁盘写满或其他临时写入错误导致录音停止，同时 `recover_audio` 无法再创建 / 完成 `recovered.wav`；数据库仍能提交错误元信息。用户排除存储故障后重新连接或重启应用。

**原因**：Recorder 将“恢复副本未生成”直接当作“没有可用音频”，提交 `failed`、`audioPath = None` 与零帧数。Repository 启动恢复只扫描 starting / recording / stopping，因此该 failed 记录不再被检查。Repository 自身的首次启动恢复发生临时写入失败时也有相同的终态转换。

**实测结果**：原 `recording.wav` 可被 `inspect_audio` 正常读取，含 256 帧、512 PCM 字节、5 ms；数据库和重启后的列表均为 failed、frames=0、audioAvailable=false、audioError=null。移除故障后重建 Repository，结果仍不变；原文件仍存在。

**影响**：原始内容没有被删除，但用户无法通过产品查看已落盘的可恢复部分；常规“释放空间后重连”不能恢复，需要手工干预文件 / 元信息。违反 R3 保留并支持查看可恢复部分、R5 恢复语义及 AC-06。该问题不能仅记为“不保证内存或系统缓存零丢失”，因为本次丢失的是产品内访问已落盘完整帧的能力。

## Regression Risks

- 返工必须区分“确实没有有效帧”与“恢复暂时无法完成”，保留原始文件、失败原因和可重试依据；不能将有缺口的录音改成 completed，也不能通过清库 / 删除源文件解决。
- 单纯开放任意 recording.wav 媒体路径会改变现有边界；若采用直接播放有效原文件的方案，仍须满足同样的 ID、路径和帧一致性校验。也可在存储恢复后生成受限 recovered.wav。
- Windows CI / 实机 / 真实设备录音未运行；首次 macOS 授权弹框未实测。Spec 允许当前 macOS 开发交付保留这些明确边界。
- 实录是短时物理输入与播放器验证，不代表长会音质或 Windows 设备兼容性验收；强杀时未落盘队列 / OS 缓存仍不承诺零丢失。

## Required Rework

1. 为有效原音频但恢复暂时失败的记录保留后续重试能力；存储条件恢复后，重新连接 / 启动应恢复实际完整帧并显示 interrupted，允许产品内回放，且保留源文件。
2. 同步覆盖 Recorder 异常收尾与 Repository 启动恢复的相同终态遗漏，避免第一次恢复失败后永久跳过。
3. 针对上述条件增加或调整最小回归检查：恢复失败时不假报完整成功；移除故障后重连能恢复并回放；元信息与有效帧一致、原文件保留。仅运行受该修复影响的相关检查，不重录麦克风或全量复跑已通过证据。
4. 新的实施 Agent 返回返工报告后，由新的独立 Acceptance Agent 检查并更新结论。
