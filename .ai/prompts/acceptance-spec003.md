# Task Handoff — Spec 003 独立工程验收

## Role

Acceptance，仅在 implementation.md 完成并收到主 Agent 明确交接后启动。必须是未参与本轮业务实施的新 Agent；不创建子 Agent，不修改业务 / 测试 / 配置，不 commit / push。仅写本 Spec 的 acceptance.md，问题交回主 Agent 组织返工。

## Goal / Project Mode

EXISTING。根据已确认 Spec 003 和实际工程证据验收本地持续转写，结论只用 PASS / FAIL。此文件是交接约束，不是已经运行的验收报告。

## Required Reading

AGENTS.md、constitution/mission.md / tech-stack.md、.ai/rules/全部规则、Spec 003 spec.md / plan.md / implementation.md、决策 0005 / 0007、相关含新增文件的 diff、测试和主 Agent 提供的真实平台运行结果。Spec 决策本身不重新安排子 Agent 验证。

## Scope

- 对齐 Spec 的全部验收标准，核对具体行为与实际证据，不能仅凭 UI 文案判断功能存在。
- 模型准备：固定来源与 revision / 校验、真实进度、取消重试、完整性与实际加载、模型缺失不影响录音、缓存就绪后仅本地推理。
- 录音 / ASR 隔离：独立进程、有界音频与任务描述、持续写入范围、积压可恢复、超时或 worker 异常不杀录音、关闭与父进程异常后的子进程回收。
- Transcript：真实时间映射、VAD / 静音 / 尾块 / 跨块、事务提交、稳定 ID、重复请求与重放防重、有界分页、回放定位和录音期间禁播。
- 数据：schema 1 升级及失败回滚、原会议 / 音频保留、静音也推进进度、文件暂时不可读与恢复范围变化不伪造完成。
- 生命周期：录音终态与转写状态独立，关闭可以保留进度退出，重启 paused 由用户继续，历史任务不抢占活动录音。
- 平台：macOS ARM64 与 Windows x64 的真实模型推理和相关 Electron 场景，确认新测试没有沿用 POSIX shim 跳过。现有 4 项 Windows 平台受限 smoke 的历史跳过要如实记录。
- 质量 / 性能：固定非敏感真实人声及参考稿、样本选择与来源、中文 CER / 混合术语 / 延迟指标。短合成语音、测试假 Provider、真实录音和物理麦克风采集公开人声应明确区分，不能互相冒充。

## Verification Rules

S3 的技术依据是持久化迁移、共享 IPC、下载和进程生命周期。先读可核对的实施证据并独立审查代码，不为“独立”而重复已通过且未变化的检查。仅对未覆盖的具体风险、变更后未验证代码或不明确结果执行最小探测，并说明依据。

声明远端 CI 通过必须有对应提交和实际双平台任务结果；本机不能代替 Windows。未执行或未满足的标准写明影响，不通过修改 Spec / 测试来掩盖问题。

## Expected Output

specs/spec-003-local-transcription/acceptance.md，包含 Result、Spec Coverage、Tests、Issues、Regression Risks、Required Rework。区分复用的实施证据和独立执行项目；只写可复现的相关问题，适当检查已通过且没有具体问题后立即停止。临时探测使用 ignored artifacts/spec003/ 和隔离数据目录，清理自己启动的进程。
