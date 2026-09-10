# Plan — Spec 002

DONE。对应 [Spec](spec.md)，方案依据 [决策 0006](../../.ai/decisions/0006-recording-and-storage-baseline.md)。

## 模块与数据流

`麦克风 → RawInputStream → 有界队列 → WAV writer → 文件 / SQLite`；状态经 stdio 到 UI，播放由 main 核验会议 ID 后提供媒体资源。

| 模块 | 职责 |
| --- | --- |
| recorder / audio_store / repository | 单会话、真实音量 / 帧水位、WAV 收尾与恢复、SQLite 元信息 |
| protocol / core-manager / shared | 有限命令、超时后查状态、类型与数据校验 |
| main / preload / media | userData、权限、单实例、关闭 / 重连 / suspend、受限播放 |
| renderer | 活动录音、历史分页、详情播放器和可操作错误 |

## 实施顺序

1. 核对音频依赖、默认设备参数与 macOS 原生授权归属，锁定依赖。
2. 建立 SQLite schema 1 和恢复路径，先以隔离输入验证采集 / 写入状态，再验证实机。
3. 扩展控制契约与能力校验，接入生命周期保护及受限媒体，不保留空列表专用校验。
4. 接入 UI、文档和对应检查；实施报告后独立验收，恢复返工见 [实施摘要](implementation.md)。

## 接口与存储

stdio 增加 `recording.start/status/stop/interrupt`、`meetings.list/get`，保留 health / shutdown。start 接受幂等 operationId；stop 尽快返回 stopping，状态轮询等待收尾；interrupt 和 shutdown 不直接暴露给 renderer。历史按页查询。

音频按设备可用采样率保存 mono PCM16；临时文件收尾后同文件系统重命名，数据库存相对路径。媒体仅接受会议 ID，核对真实根归属、文件类型 / 大小与 Range；生产 CSP 只增加必要音频来源。轮询最多一个在途请求。

## 迁移与故障

本阶段首次建立 schema 1，无旧业务库迁移；不兼容版本报错而不清库。文件和数据库非同一事务，按中间状态及实际完整帧恢复，保留源文件；恢复暂失败保留可重试依据。强制退出可能绕过退出钩子。

## 验证计划

本实现涉及权限、媒体、持久化、IPC 与退出，按 S3 验证相关子系统：Recorder / Writer 帧序、音量、幂等、溢出、写失败；Repository 重启、锁、中文路径与 schema 保护；媒体路径 / Range / 来源；Electron 关闭、切页、suspend、核心恢复、最小窗口。实机单独验证物理麦克风 → 保存 → 重启 → 播放。恢复修复只重跑受影响 Python 子系统，其他通过证据复用。结果集中见 [验收](acceptance.md)。

## 风险

设备授权因平台不同；WAV 有容量限制。控制循环和录音回调不能等待磁盘收尾或未来推理；存储故障不能通过清空源文件或扩大媒体权限解决。
