# Implementation Report — Spec 002 Rework 1

日期：2026-09-09。角色：新的返工 Implementation Agent。范围仅为首轮验收 ISSUE-01；未提交或推送 Git，等待新的独立 Acceptance Agent。

## Summary

修复录音异常收尾和启动恢复的同一遗漏：恢复副本暂时不可写时，保留原始音频、已核实完整帧元信息和后续重试依据。用户排除存储故障后重新连接或启动，Repository 再次恢复到 `recovered.wav` 并标记 `interrupted`，不会将中断录音宣告为 `completed`。

临时失败期间显示恢复尚未完成及检查存储后重新连接的提示，不提供不可播放的媒体路径。原始 `recording.wav` 保留，空音频或无效格式不会伪造待播放内容。

## Files Changed

- `src/python/paa_core/audio_store.py`：提取 canonical PCM16 WAV 头与实际完整帧检查，增加只读 `inspect_recoverable_audio`，恢复复制沿用同一格式检查；支持计入旧头声明之外的完整帧并忽略末尾不足一帧的字节。
- `src/python/paa_core/recorder.py`：恢复副本写入失败时保存待恢复目标与实际帧数，不再清空恢复入口。
- `src/python/paa_core/repository.py`：启动同时扫描活动记录及带待恢复目标的失败记录；区分暂时 I/O 失败与空 / 无效音频；重试保留原始 `errorCode` 和已记录的 `endedAt`；待恢复记录返回明确的 `audioError`。
- `tests/python/test_recording.py`：新增三项直接相关回归及断言辅助。
- 本 `implementation-rework-1.md`。

没有修改 TS、IPC、Electron 媒体映射、schema、依赖或主 Agent 维护的文档。

## Important Decisions

沿用 SQLite v1 现有字段，不增加状态或迁移：

- `failed` 且 `audioPath` 非空表示有待完成的恢复，目标仍是 `meetings/<UUIDv4>/recovered.wav`。这是恢复目标，不代表文件已生成；此时 `audioAvailable=false`，内部查询也不提供播放路径。
- 对可以只读识别的原始 WAV，失败记录保存完整帧数、PCM 字节数与相应时长。判定不需要写入恢复副本。
- `failed` 且 `audioPath` 为空继续表示没有可恢复的有效候选；空文件和无效 WAV 不生成虚假可播放状态。
- 成功复制、校验并保存元信息后，转为 `interrupted`，恢复现有 `recovered.wav` 媒体关联；保留最初的 `storage_write` 或 `process_interrupted` 原因，不在重试时改写成无关错误。
- 保留既有会议 ID、路径、采样格式与帧一致性检查；没有开放 `recording.wav` 给播放器，也没有删除源文件或清库。

## Tests

本次涉及持久化恢复，按 S3 风险中的实际变更仅验证受影响的 Python Recorder / Writer / Repository 子系统；未扩展到未修改的桌面边界。

执行一次：

```text
.venv/bin/python -m unittest discover -s tests/python -p test_recording.py -v
```

结果：**13 PASS**，退出码 0，1.162 秒。包括原有 10 项录音 / 存储检查和以下 3 项新回归：

1. **写录音失败 + 恢复副本 ENOSPC**：先写入 256 帧 / 512 PCM 字节，再注入录音写失败；拦截实际 `recovered.recovering` 写入为 ENOSPC。失败时保留 256 帧元信息与待恢复目标，首次重连仍受故障影响也不丢失入口；撤销故障后再次启动得到 `interrupted`、256 帧 / 512 字节 / 5 ms，逐字节核对恢复 PCM，保留 `storage_write` 和原始文件。
2. **首次启动恢复 ENOSPC**：原 WAV 头只声明 128 帧，实际另有 64 个完整帧和一个尾字节。两次故障中的启动都保留 192 帧恢复依据；撤销故障后恢复 192 帧 / 384 字节 / 4 ms，逐字节核对 PCM，保留 `process_interrupted` 和完整原始文件（含尾字节）。
3. **空 / 无效 WAV**：两种子场景均为 `failed`、零帧、空关联、不可播放，源文件不变。

两项故障回归核对恢复后的格式、帧数、字节数、时长、`audioAvailable`、无 `audioError`、受限媒体既有允许的 `recovered.wav` 路径，以及文件长度 `44 + bytes`。使用合成 PCM 和独立 TemporaryDirectory，未采集麦克风、未读取或删除真实用户数据。

实施前后定向 diff 已检查，修改仅限上述文件。通过后停止代码检查，未重复该测试、全量 Python、TypeScript、lint、typecheck、build、Electron 或实录。未修改的 7 项 Python 协议、19 项 TypeScript、6 项 Electron 及真实麦克风 / 播放证据沿用首轮报告；本轮不将这些证据表述为重新执行。

原 `acceptance-recovery-probe.py` 与 JSON 保持首轮缺陷证据，未覆盖；其断言描述旧失败行为，本轮修复验证由新增回归承担。

## Known Limitations

- 恢复仍需要存储可读写及足够空间；持续故障期间保留待恢复记录并显示错误，下一次重连 / 启动重试，不自动轮询磁盘或继续录音。
- 只能恢复已经落盘的完整帧，不承诺内存队列或系统缓存零丢失。
- 本轮没有重复启动 Chromium 播放器。恢复产物满足未修改媒体边界的既有契约；浏览器实际解码 / 播放证据复用首轮。
- Windows 实机 / 设备录音和首次 macOS 授权弹框仍未验证，边界同首轮报告。

## Remaining Questions

无阻塞实施的问题。返工代码及必要定向检查已完成，由新的独立 Acceptance Agent 根据 rework.md 验收；本报告不代替最终验收。
