# Task Handoff — Spec 003 实施

## Role

Implementation。一个实施 Agent 串行处理耦合业务模块，禁止创建子 Agent，不负责最终独立验收，不 commit / push。

## Goal

实现 Spec 003：默认本地模型准备、持续转写、Transcript 保存 / 查询 / 定位、历史补转写与中断继续。先用真实模型验证技术可行性，不用模拟结果替代真实 ASR。

## Context / Project Mode

EXISTING。用户已明确“可以的，开始实施”。Spec 003、Plan、决策 0007 已就绪；目前未提交的文档来自本轮规划，应保留。现有 main 基线 b9e0e74 的双平台 CI 已通过，Windows 原有 4 项平台受限 smoke 跳过。Node 24 / Python 3.12 的依赖环境已准备，不无理由重装 Node / Electron。

## Required Reading

AGENTS.md、constitution/mission.md、constitution/tech-stack.md、.ai/rules/全部有效规则、specs/spec-003-local-transcription/spec.md 和 plan.md、决策 0005 / 0006 / 0007、docs/architecture.md、相关代码和测试。当前不存在 .ai/workflows/implementation.md，遵循现有规范，不需要补建流程。

## Scope / Ownership

你拥有 src/、tests/、scripts/、推理依赖和必要工程 / CI 配置、README.md，以及 specs/spec-003-local-transcription/implementation.md。主 Agent 维护 constitution/、Spec / Plan、.ai/、docs/，协助获取公开非敏感语音与协调验证；不要改主 Agent 文档。接口、版本、模型 manifest 与重大实际偏差及时告知主 Agent。

## Implementation Boundaries

- 默认 faster-whisper + small 多语言 / CPU INT8，中文为主兼顾中英混合。先验证 Python 3.12 macOS ARM64 / Windows x64 wheels，固定发布版本、官方模型 revision / 文件大小 / SHA256 和许可。允许在隔离 artifacts/spec003/ 中下载默认模型及安装所需依赖。公开来源核对用官方文档，不自动引入第二套引擎。
- 主 Agent 正在独立准备公开人声参考样本；先完成安装 / 小模型加载与代码调研，有可用样本后协调基准测试，不重复下载同样大文件。若已有合适样本及时发消息。
- 模型就绪后仅从本地路径加载，关闭隐式联网。受控下载需真实进度、取消 / 重试、校验 / 加载、staging 原子发布。普通 UI 不显示 pip / 任意路径，不需要用户自己配环境。录音在模型未就绪时仍可用。
- 保留原生录音 / WAV / SQLite，录音不等 ASR。ASR 独立受管工作进程，Windows 使用可用 spawn 入口，有界缓冲 / 队列 / 超时 / 退出清理，主 stdio 响应不做推理。磁盘音频及事务检查点承接积压。录音优先，单推理并发。
- 已写完整帧水位、约 10 秒可配置业务块、有限上下文与 VAD、正确重采样 / 时间映射、静音及尾块，避免跨块重复和确定性漏字。短读关闭音频句柄，避免 Windows 收尾 rename 被 ASR 占用。
- schema 1 → 2 增量事务迁移，新增任务 / 块 / 片段，进度与结果原子提交，稳定 ID / 唯一约束防重。旧会议不自动推理，不改变录音终态。仅操作隔离测试数据，不对真实用户数据试错 / 删除。
- Transcript 有界分页、持久后显示、实际时间戳、点击定位遵守录音期禁播。模型 / 录音 / 转写状态分离，积压和失败可见。历史补转写、失败继续幂等，退出保存进度、重启 paused 后用户继续。
- 保持 renderer sandbox / contextIsolation / IPC 来源和参数校验；不接受任意模型 URL、文件路径或执行命令。保留 Chromium fake-device smoke 修复，不使用 fake-ui 自动批准权限。
- 不做 LLM、云 ASR、编辑 / 导出、GPU设置、安装包、Memory、其他无关功能。

## Verification

本次为 S3（持久化迁移、共享 IPC、下载与进程基础设施），执行相称的相关测试和必需 CI 检查，不重复已通过且未变化的检查。先真实 ASR 可行性，再按修改模块测试；确切版本 / 参数 / 测试命令 / 数量 / 输入来源写报告。为重复实现而增加的琐碎测试不需要。

模型测试使用固定公共非敏感样本；模拟 Provider 只用于稳定控制故障。新增跨平台 smoke 不继承旧 POSIX shim 平台 skip。实际 Windows 模型推理需配置到 CI 并由主 Agent 跟进结果。本机与 CI 不互相冒充。实际录音请先通知主 Agent操作时间；不要在用户未知时长期间打开麦克风，不修改系统隐私设置。

## Expected Output

完成业务代码、相关验证，写 implementation.md：Summary、Files Changed、Important Decisions、Tests、Known Limitations、Remaining Questions；提供模型缓存位置、实际推理证据及可复用测试结果。截图 / 音频 / 模型 / 测试数据库在 ignored artifacts/，不提交用户数据。结束自己启动的测试进程。实施完成后回报，由主 Agent 安排新的独立验收，不自行标记最终 PASS。
