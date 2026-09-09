# Implementation Report — Spec 002

日期：2026-09-09。角色：Implementation；业务实施已完成，等待新的独立 Acceptance Agent。没有提交或推送 Git。

## Summary

实现默认麦克风 → 持续 PCM16 WAV → SQLite 元信息 → 历史详情 → 重启回放的完整闭环。录音归属 Python 原生 RawInputStream；本机真实 Electron 调用 Python 的权限与采集已验证，没有实现第二套 renderer 录音栈。

- 默认设备在开始时解析，实际流打开后才显示 recording；显示设备名、有效采样时长和真实 RMS 音量。
- 回调仅复制音频与序号 / 样本偏移进入有界队列（64 × 最多 2048 帧）；单工作线程负责文件写入，状态 / 控制请求不等待整场音频或收尾。
- 开始 operationId 持久化唯一；重复开始返回相同或唯一活动会议，重复结束可安全查询。动作超时后只查询权威状态，不盲目重发；主进程合并状态查询，UI 按上次返回后 400ms 继续轮询。
- 结束先停止输入流并等待回调结束，再排空已接受队列、关闭并同步 WAV、同文件系统重命名、提交最终元信息。队列 / 驱动溢出、文件错误和数据库错误不宣告完整成功。
- 窗口最小化 / 页面切换保持录音；关闭 / 退出 / 重连确认保护活动会话；保存失败保持可见。系统 suspend 直接请求中断，因此不受未决关闭确认 promise 阻塞。
- 强制中断后从已落盘完整帧恢复到新文件，原始临时文件保留；中断不会恢复为 completed。系统缓存或队列中未落盘的数据不承诺零丢失。
- 主进程单实例保护、IPC 来源 / 参数校验、受限媒体协议、Range 读取与既有 renderer 沙箱保持生效。摄像头等 Chromium 权限继续拒绝。

## Files Changed

实施范围：

- `src/python/paa_core/recorder.py`、`audio_store.py`、`repository.py`：真实采集、状态、WAV 与恢复、SQLite v1。
- `src/python/paa_core/protocol.py`、`__main__.py`：真实控制方法、数据根启动参数与结构化错误。
- `src/desktop/core-manager.ts`、`json-line-client.ts`：方法 / 参数扩展、真实能力与会议校验、超时查询恢复、非阻塞收尾协调。
- `src/desktop/main.ts`、`preload.ts`、`media.ts`：原生麦克风权限、实例 / 退出 / 重连 / suspend、有限 IPC、受限媒体。
- `src/shared/contracts.ts`、`src/renderer/App.tsx`、`styles.css`、`electron.vite.config.ts`：录音 / 历史 / 详情 UI、标准播放器、必要 media-src CSP。
- `tests/python/test_recording.py`、`test_protocol.py`、`smoke_core.py`、`tests/desktop/media.test.ts`、`core-manager.test.ts`、`tests/smoke/app.spec.ts`：针对性测试与显式合成测试启动器。
- `pyproject.toml`、`requirements.lock`、`scripts/install-python.mjs`、`.github/workflows/ci.yml`、`.env.example`、`README.md`：锁依赖、可复现安装与实际使用说明。
- 本 `implementation.md`。

`constitution/`、`docs/`、Spec / Plan、`.ai/` 由协调 Agent 同步，不属于实施 Agent 修改。

## Important Decisions

延续决策 0005 / 0006，未改变采集归属和交付范围。实际稳定依赖为 sounddevice **0.5.6**、CFFI **2.1.1**、pycparser **3.0**；Mac wheel 报告 PortAudio **V19.7.0-devel**（库自身版本字符串，并非安装开发分支）。无 NumPy、ASR 或 LLM 依赖。限定安装首次误选 0.5.5，查询 PyPI 当前稳定版后更正为 0.5.6；最终锁与本机一致。

存储布局：

```text
Electron app.getPath('userData')/
├── meetings.sqlite3           # PRAGMA user_version = 1
└── meetings/<UUIDv4>/
    ├── recording.wav          # 录制临时文件，崩溃恢复时保留
    ├── audio.wav              # 正常文件收尾后重命名
    └── recovered.wav          # 可恢复完整帧的新文件
```

数据库存相对音频路径；root 由可信 Electron 传 `--data-dir`，与仓库 / cwd 无关。已有不兼容 schema 报错，不清库。单表最小字段覆盖 Spec 并新增 operationId 唯一约束和音频元信息。

stdio：health、recording.start/status/stop/interrupt、meetings.list/get、shutdown。meetings.list 每页 50 条，输入 offset，输出 hasMore；避免历史增长导致单行控制消息越界。

preload：getStatus、retryCore、listMeetings(offset)、getMeeting(id)、getRecordingStatus、startRecording(operationId)、stopRecording(id)、onStatusChanged、onLifecycleError。普通操作返回 `{ok,value}` 或 `{ok:false,message,code}`；列表保留 meetings 字段。内部 audioPath 被主进程剥离，不进入 renderer。

播放地址仅为 `paa-audio://meeting/<合法会议ID>`，主进程再次核查数据库、真实根归属、文件名 / 类型 / 大小；拒绝查询参数、路径穿越、符号链接越界、任意文件和非法 Range，支持 GET / HEAD 与 206。录音活动时媒体响应拒绝；UI 开始前暂停播放器。

`PAA_TEST_DATA_DIR` 显式隔离测试数据并参与单实例锁；合成源只存在 tests，通过测试生成的 POSIX 可执行 shim 启动，不在产品中提供自动假录音回退。

## Tests

本次为 S3：持久化 schema、麦克风 / 媒体权限、共享 IPC 与退出生命周期。检查集中于这些实际变化的子系统，未跑无关模型或压力测试。

### 已通过的自动检查

| 命令 / 检查 | 结果与范围 |
| --- | --- |
| `npm run test:python` | **17 PASS**：7 协议、10 Recorder / Writer / Repository。包括帧序 / RMS / 幂等、权限式设备拒绝、driver / queue overflow、写失败保留、头部之外完整帧恢复、路径 / 缺失文件、schema保护 / SQLite锁、控制非阻塞、suspend / final commit失败。此后 Python 产品代码未变，未重跑。 |
| `npx vitest run tests/desktop` | **19 PASS**：16 既有进程边界（共享实现已变化）+ 3 媒体 / 超时查询测试。覆盖有限 Range、任意路径 / 符号链接、缺失媒体、超时不重放、轮询合并。 |
| `npm run typecheck` | **PASS**，覆盖最终业务与测试 TS。首次主实现通过；新增 smoke 类型后发现音频元素类型错误，局部修正并重跑通过。 |
| `npx eslint src/desktop src/shared src/renderer tests/desktop tests/smoke scripts/install-python.mjs` | **PASS**。首轮发现 publicMeeting 未用解构变量和测试未用 import；改为复制后删除内部路径、清除 import 后通过。 |
| `npm run build` | **PASS**，生产 main / preload / renderer。首轮用于真实录音和 smoke；publicMeeting 同等语义的 lint 修正后再构建最终产物，没有重录。 |
| `git diff --check` | **PASS**；检查期望范围与无空白错误。相关文件用 Prettier 格式化。 |

### 真实 Electron 图形 / 故障场景

`npx playwright test` 首轮 **5 PASS / 1 测试自身失败**。失败原因是测试错误调用不存在的 `Session.getPermissionStatus`，不是产品权限放开；改为真实 renderer 的摄像头 getUserMedia 请求，断言 `NotAllowedError`。仅重跑失败项 `npx playwright test -g 'real desktop exposes'`，**1 PASS**。合计 6 场景均通过，没有全量重复。

1. 真实核心能力 recording=true、空历史、IPC 非法 ID 拒绝、沙箱 / 无 Node、摄像头拒绝、900×640 无横向溢出、核心退出重连与退出清理。
2. macOS 权限返回 denied 的注入故障：用户提示可操作，状态 idle、无会议 / 无录音。
3. 显式合成输入：页面切换和最小化保持录音；关闭 / 重连取消不换会话；停止保存后退出、重启加载 / seek；不暴露 audioPath。
4. 显式合成输入：未决关闭确认期间模拟 suspend，及时 interrupted；再开始后强制 SIGKILL 核心，重启两场都为 interrupted，已落盘部分可播放。
5. 显式合成输入：关闭 WAV 失败时，保存退出被阻止，窗口仍可见、部分录音保留且可播放。
6. Python 缺失仍打开界面，显示重新连接入口。

另一次有明确风险依据的真实 Electron 单实例检查：同隔离数据根启动第二进程，第二进程退出码 **0**，原核心 PID 不变。没有采集麦克风。

截图：`artifacts/spec002/empty-minimum.png`、`synthetic-settings-recording.png`。合成输入是测试静音 PCM，不能作为真实设备证据。

### 真实麦克风闭环

时间：2026-09-09 **21:44**（Asia/Shanghai），开始前由协调 Agent 通知用户。使用真实 Electron 生产构建、真实 Python 子进程、系统默认 **MacBook Pro麦克风**。macOS 原生 microphone 状态已为 **granted**；默认 PCM16 mono / 48000Hz 参数检查通过。

一次约 **4.395 秒**录音，播放短系统 Glass 提示音，经电脑扬声器→物理麦克风采集；未注入 PCM，未修改系统音量和隐私设置。随后停止、保存、关闭 Electron、同隔离数据根重启、从历史打开并播放。

- meetingId：`90eb6ff9-6eb6-4019-928a-a3d80cce4cd8`。
- 有效帧 **210944**，PCM 字节 **421888**，单声道 / 16 bit / **48000Hz**，最终 completed，audioAvailable=true。
- 样本非零数 **203093**，RMS **139.3968**，peak **1080**；活跃输入量记录 **0.0081497**。
- 重启播放器解码 duration **4.394667 秒**、currentTime 已推进至 **0.66731 秒**、paused=false、无媒体错误；使用受限 paa-audio 资源。
- `artifacts/spec002/real-evidence.json` 保留状态与隔离目录位置；`real-capture.mjs` 保存该次验证步骤。
- `real-recording.png` 拍到准备状态，**不单独作为正在采集的视觉证据**；实际 recording 状态 / 帧数证据在 JSON。`real-saved.png`、`real-restarted-playback.png` 展示保存与重启播放；已查看布局。
- 音频保留在 JSON 指定的隔离临时目录，未放入版本库、未触碰真实用户会议；相关 Electron / Python 测试进程已结束。

上述证据证明物理输入、非空 PCM、保存一致性、历史重启与 Chromium 播放进度；不宣称 Agent 进行了人耳音质评价或真实长时间会议讨论实测。

## Known Limitations

- macOS ARM64、Node 24.20.0 / npm 11.19.0 / Python 3.12.14 / Electron 44.3.0 为本轮实机环境。Windows CI 已更新录音依赖安装，但 **Windows CI / 实机 / 设备录音均未运行**；POSIX 合成 smoke 在 Windows 明确跳过。
- 本机麦克风已获授权，**首次系统授权弹框尚未实测**。拒绝后的产品路径通过状态注入验证；实际输入流成功证明当前 Electron → Python 原生采集归属可用。
- 强制断电或进程退出时只能恢复已经落盘的完整帧；不保证内存队列或 OS 缓存零丢失。不自动换设备或恢复录音。
- WAV 固定单声道 PCM16、容量接近 4 GiB 时显式停止；没有压缩、导出、删除或编辑。
- 当前仍为开发源码 / 构建预览，正式安装包、内置 Python、签名 / 公证未实现；正式用户无需安装 Python / Node.js 的约束不变。
- ASR、LLM、转写与纪要继续未接入。没有新增外部收费服务。

## Remaining Questions

无阻塞实施的问题。等待新的独立工程验收；验收可复用上述明确证据，仅在发现具体缺口或变化时补充相关检查。
