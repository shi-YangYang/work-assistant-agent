# 项目路线图

本文描述用户已提出的阶段方向，不替代具体 Spec，不承诺时间或尚未确认的实现方案。

产品目标平台包括 macOS 和 Windows，架构与技术选型从当前阶段开始考虑跨平台兼容性。Spec 003 最终代码 `0b84fe1` 的 [macOS / Windows CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34451673078) 已完整通过，包含两平台真实 ASR 与新增转写桌面流程。Windows 的 4 项既有平台受限冒烟测试仍跳过，物理麦克风验证仅在 macOS 完成。最低系统版本及安装包交付安排留给后续分发阶段。

## Phase 0 — 项目骨架与架构准备（已完成）

- 已建立标准 Agent 结构及基础项目目录。
- 已记录产品使命、开发规范、阶段边界和已知技术约束。
- 已完成 [Spec 001：产品与技术基础](../specs/spec-001-product-and-technical-foundation/spec.md)，交付产品定义、技术方案和可运行工程骨架，独立工程验收为 PASS。
- 已确定 Electron + React + TypeScript 桌面入口、Python 本地核心及 stdio 进程通信，见 [实施基线](../.ai/decisions/0004-foundation-stack.md)。
- 已实现中文会议工作区、设置、真实核心连接、故障重试与退出清理；本机工程检查及 Electron 冒烟测试通过，当前双平台 CI 状态见上文。
- Spec 001 未接入真实录音、ASR 或 LLM；完整 Meeting Agent 功能由 Phase 1 的后续 Spec 推进。

## Phase 1 — Meeting Agent MVP（当前阶段）

目标是完成开始会议、持续录音、本地转写、显示并保存完整 Transcript、结束会议、生成并保存结构化纪要的闭环。

已完成 [Spec 002：会议录音与本地保存](../specs/spec-002-meeting-recording-and-storage/spec.md)，交付麦克风录音、保存、历史与回放；状态为 DONE，独立验收 PASS。转写与纪要在此基础上逐步接入。正式用户试用前应完成独立的安装包与内置运行时分发工作。

已完成 [Spec 003：本地语音转写与 Transcript](../specs/spec-003-local-transcription/spec.md)，状态 DONE，独立验收 PASS。交付应用内默认模型下载、中文为主且兼顾中英混合的持续转写、尾部补齐、历史补转写与持久恢复；实际质量、麦克风和双平台结果均已记录。纪要仍留给后续 Spec。

[Spec 004：会议纪要生成](../specs/spec-004-meeting-minutes/spec.md) 已实现多服务 API 管理、动态模型列表、自定义推理预设和转写完成后自动生成纪要；本地检查完成，仍待真实 API 样本及本轮 Windows／远端 CI 验证。

关键结果：

- ASR 和 LLM 延迟不阻塞录音。
- 音频与转写处理解耦，音频分块策略可调整。
- 结束会议后处理完剩余录音，再用完整转写进行会后分析。
- 保留会议原始信息及结构化结果。
- 提供后续可替换的 ASR、LLM 和存储 / Memory 能力边界。

本阶段不实现复杂实时理解、周报模块、复杂 Memory 或产品中的多 Agent 工作流。

## 后续方向 — Weekly Report Agent

- 收集与解析员工周报。
- 保存完成事项、进行中工作、下周计划、问题、风险和协调事项。
- 汇总个人与团队工作信息，逐步分析跨周持续出现的问题。

## 后续方向 — Memory 与会议理解增强

- 关联会议、人员、项目、任务、决策、周报和风险。
- 基于历史信息回答工作与项目问题。
- 根据需要增加说话人分离及真实人员映射。
- 增加增量会议理解，将转写、结构化事件和已有记忆用于最终分析。
- 在需求与数据基础成熟后考虑主动分析与工具调用。

后续方向之间的具体顺序、范围与技术方案尚未确定，应在 MVP 验证后再明确。
