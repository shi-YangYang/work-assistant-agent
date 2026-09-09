# Rework — Spec 002

## 状态

CLOSED，ISSUE-01 已修复并通过新的独立验收 [PASS](acceptance.md)。修复与 13 项定向 Python 检查见 [返工报告](implementation-rework-1.md)。首轮 FAIL 历史保留在 [acceptance-round-1.md](acceptance-round-1.md)。下文保留本轮返工要求与验证范围。

## ISSUE-01 — 暂时不可写导致恢复被永久跳过

已有有效录音时发生写入失败，恢复副本也暂时无法写入，Recorder 将状态置 failed、清空音频关联；Repository 只扫描活动记录，因此排除故障并重连也无法恢复。启动恢复本身遇到同样错误也会永久跳过。独立隔离探测确认原文件有 256 帧 / 512 PCM 字节且仍可读取，但重启后产品不可播放。

源码范围：`src/python/paa_core/recorder.py`、`repository.py`，必要时涉及 `audio_store.py`；相关 Python 测试。探测及 JSON 位于忽略目录 `artifacts/spec002/acceptance-recovery-*`。

## 修复要求

1. 区分没有有效帧和暂时无法完成恢复，保留源文件、失败原因及后续重试依据。
2. 录音异常收尾、启动恢复均不得因第一次恢复副本失败而永久失去恢复入口。
3. 排除故障后，重连 / 启动应恢复已落盘完整帧，标记 interrupted，元信息一致且能通过现有受限媒体资源回放；不得标 completed 或清库。
4. 保持现有媒体 ID / 路径边界；优先局部修复，不引入新依赖、第二套存储或未授权 schema / 目录重构。

## 验证

补充定向回归，覆盖录音写失败后恢复副本失败、首次启动恢复失败，两者在故障撤销后均能恢复；失败时不假报成功，原文件保留。修复涉及持久化恢复，允许运行受影响 Python 记录 / 存储子系统检查。未改动的 TS、Electron、实录证据复用，不重复全套或重新采集。若必须改跨界面契约，先报告具体理由，再只验证直接影响范围。

## 报告

新的实施 Agent 写 `implementation-rework-1.md`，记录实际修改、选择、命令、结果与未执行项。保留原 implementation.md 和首轮验收历史；最终 acceptance.md 由新的独立验收 Agent 更新。
