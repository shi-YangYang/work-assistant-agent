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

## Phase 1 — Meeting Agent MVP（已有会议基础，保留）

目标是完成开始会议、持续录音、本地转写、显示并保存完整 Transcript、结束会议、生成并保存结构化纪要的闭环。

已完成 [Spec 002：会议录音与本地保存](../specs/spec-002-meeting-recording-and-storage/spec.md)，交付麦克风录音、保存、历史与回放；状态为 DONE，独立验收 PASS。转写与纪要在此基础上逐步接入。正式用户试用前应完成独立的安装包与内置运行时分发工作。

已完成 [Spec 003：本地语音转写与 Transcript](../specs/spec-003-local-transcription/spec.md)，状态 DONE，独立验收 PASS。交付应用内默认模型下载、中文为主且兼顾中英混合的持续转写、尾部补齐、历史补转写与持久恢复；实际质量、麦克风和双平台结果均已记录。纪要仍留给后续 Spec。

[Spec 004：会议纪要生成](../specs/spec-004-meeting-minutes/spec.md) 已实现多服务 API 管理、动态模型列表、自定义推理预设和转写完成后自动生成纪要；用户反馈基本验收无问题，代码 `9b2dc93` 的双平台 CI 已通过，仍缺 Agent 的真实 API 样本核对证据，详见该 Spec 实施报告。

[Spec 005：桌面打包与会议操作体验](../specs/spec-005-desktop-distribution-and-controls/spec.md) 已实施，状态 ACCEPTANCE：内置 Python 运行环境的安装包、设置折叠与命名整理、录音暂停／继续、自定义播放器。交付及验证结果以本 Spec 报告为准。

[Spec 006：界面层级、页面导航与会议交互](../specs/spec-006-interface-and-navigation/spec.md) 已完成现有能力的视觉、信息组织和操作体验重设计，状态 ACCEPTANCE；独立验收及本次 CI 待闭环。

[Spec 007：会议记录管理与检索](../specs/spec-007-meeting-library/spec.md) 已实现会议查找、重命名、复制导出与永久删除，独立工程复验 PASS；日期控件的最后一项界面复验待解锁，具体边界见 [验收报告](../specs/spec-007-meeting-library/acceptance.md)。

关键结果：

- ASR 和 LLM 延迟不阻塞录音。
- 音频与转写处理解耦，音频分块策略可调整。
- 结束会议后处理完剩余录音，再用完整转写进行会后分析。
- 保留会议原始信息及结构化结果。
- 提供后续可替换的 ASR、LLM 和存储 / Memory 能力边界。

本阶段不实现复杂实时理解、周报模块、复杂 Memory 或产品中的多 Agent 工作流。

## 下一阶段 — 员工消息、工作汇报与老板看板

以用户所在公司为试点，优先员工消息与汇报流程。[Spec 008：员工工作助手与汇报看板](../specs/spec-008-meeting-followup/spec.md) 已完成业务实施与两轮定向返工，独立工程验收 PASS，状态 ACCEPTANCE。完整方向与 harness 约束见 [决策 0011](../.ai/decisions/0011-company-agent-direction.md)；独立结论及真实服务、设备、部署的验证边界以 [验收报告](../specs/spec-008-meeting-followup/acceptance.md) 为准。

- 接收员工文字、图片、语音及零散工作信息，整理可追溯的工作进展，支持员工确认或纠正。
- 生成日报／周报，供老板通过看板了解进展；以减少重复汇报和方便跟进衡量试点价值。
- 首期优先适配电脑和手机浏览器的 Web＋共享服务端；Electron 继续保留现有会议能力，后续按需接入共享业务，不同时建设全部终端。
- 首期权限、报告规则与验收要求见 Spec 008；框架、模型参考接入与单机部署提案见其 Plan，实际云资源与容量在部署前准备和验证。

## 后续方向 — 会议跟进、提醒与汇报关联

原会议事项跟进草案的业务方向保留至后续：从纪要确认独立事项，维护进展，关联会议与工作汇报，再按真实需求加入会议安排、提醒偏好和跨周分析。具体采纳、来源删除及人员映射规则届时重新确认。

## 后续方向 — Memory 与会议理解增强

- 关联会议、人员、项目、任务、决策、周报和风险。
- 基于历史信息回答工作与项目问题。
- 根据需要增加说话人分离及真实人员映射。
- 增加增量会议理解，将转写、结构化事件和已有记忆用于最终分析。
- 在需求与数据基础成熟后考虑主动分析与工具调用。

除已明确优先的员工消息与汇报流程外，其余方向的顺序和范围按试点反馈确定。
