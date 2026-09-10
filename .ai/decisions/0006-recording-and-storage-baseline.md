# 决策 0006 — 原生录音与本地存储

2026-09-09 · 已在 Spec 002 落地。

## 决定

- 系统默认麦克风、一次一场；不做系统声音、暂停续录或录音中换设备。
- Python sounddevice `RawInputStream` → 有界队列 → 写入线程。回调不执行磁盘、数据库或推理工作；原始缓冲不要求 NumPy。
- 流式保存单声道 PCM16 WAV，采样率取实际设备；后续 ASR 在消费者侧重采样，不改原录音。
- SQLite 保存元信息与相对音频路径，数据根由 Electron userData 决定。stdio 只传控制，播放通过合法会议 ID 对应的受限资源。
- 正常退出先保存；异常恢复保留源文件和完整帧。恢复副本暂不可写时保留重试依据，故障解除后重连可恢复为 interrupted，不能清库或假报 completed。

## 取舍

沿用现有 Python 核心，避免 renderer 采集随页面生命周期变化或同时维护两套采集栈。PCM WAV 便于校验有效帧，代价是磁盘占用较大；不在内存累计整场音频。原生权限链路需实际设备验证，官方平台支持列表不能替代实测。

行为与验收见 [Spec 002](../../specs/spec-002-meeting-recording-and-storage/spec.md)，实现及恢复修复见 [实施摘要](../../specs/spec-002-meeting-recording-and-storage/implementation.md)。运行依赖版本统一见 [技术栈](../../constitution/tech-stack.md)，分发沿用 [决策 0005](0005-self-contained-desktop-distribution.md)。

## 依据

2026-09-09：[sounddevice Raw Streams](https://python-sounddevice.readthedocs.io/en/latest/api/raw-streams.html)、[安装说明](https://python-sounddevice.readthedocs.io/en/latest/installation.html)、[Python wave](https://docs.python.org/3.12/library/wave.html)、[Electron 权限 API](https://www.electronjs.org/docs/latest/api/system-preferences)。
