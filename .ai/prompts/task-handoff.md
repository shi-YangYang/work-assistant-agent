# Task Handoff — Spec 003 规划与历史实施上下文

## Current Stage

ACCEPTANCE。Spec 003 业务与暂停竞态返工已完成，implementation.md / implementation-rework-1.md 为正式报告。首轮独立验收 P2 及失败证据保留在 acceptance-round-1.md；正在由新的独立验收 Agent 复验，交接为 .ai/prompts/acceptance-spec003-rework.md。当前候选分支 codex/spec-003-local-transcription，用于触发实际 macOS / Windows CI。

用户已确认中文为主、兼顾中英混合，应用内提示下载 small 模型，并授权实施。用户指定内置扬声器播放公开人声 → 物理麦克风采集的验收方式已完成：37.035秒、首字18.383秒、CER15.56%，保存补尾、重启片段一致、定位后播放实际推进；固定2分钟文件基准CER6.52%、累计44.659秒。完整来源、原失败和测量边界在 verification.md，不能混称同一次测量。模型、音频与DB均保留在ignored artifacts，不提交Git。

恢复后先检查子Agent和对应提交CI，再读实际报告，不重复已通过的模型基准、物理实录或无关基础检查。最终报告未完成前不能给PASS。Spec决策无需子Agent验证，工程独立验收规则继续适用。

## Previous Task — DONE

Spec 002 录音与本地保存已完成，首轮 ISSUE-01 恢复重试缺陷已修复，新的独立验收 acceptance.md 为 PASS。实施、首轮 FAIL、返工与最终验收均已读取处理；无仍待处理子任务。后续 CI 修复已提交推送，`b9e0e74` 的 macOS / Windows CI 均已通过，Windows 既有 4 项平台受限场景跳过。无需重新实施或重复已通过检查。

以下保留 Spec 002 的原始实施上下文，仅供追溯，非当前执行指令；首轮历史与返工范围分别见其 acceptance-round-1.md 和 rework.md。

## Role
Implementation。一个实施 Agent 串行完成耦合模块。禁止创建子 Agent；不负责最终独立验收，不 commit/push。

## Goal
实现默认麦克风录音 → 停止保存 → 重启查询与播放，覆盖 Spec 002 的权限、异常恢复和退出收尾。

## Context
用户已要求“开始实施”。Spec 决策不派子 Agent 验证，业务代码完成后仍需新的独立验收 Agent。用户最新要求验证与停止规则：已通过检查不得无理由重复，需求满足且必要检查通过后停止。本次因权限、持久化、共享IPC和退出生命周期属于S3，仍只验证相关子系统。

## Project Mode
EXISTING。Spec001已提交；本次Spec002、决策0006和状态文档未提交，不得覆盖或重置。保持既有src/、tests/、docs/与固定Agent结构。

## Required Reading
AGENTS.md、constitution/mission.md和tech-stack.md、.ai/rules/所有有效规则、Spec002 spec.md与plan.md、决策0005/0006、docs/architecture.md、相关既有代码和测试。

## Scope
你拥有src/、tests/、scripts/、必要根目录工程配置、pyproject和新增Python锁定文件、.github/workflows/必要调整、.gitignore、.env.example、README.md、Spec002 implementation.md。主Agent维护constitution/、Spec/Plan、docs/和.ai/，不要同时改这些文档；接口和工程事实及时告知主Agent。

## Implementation Boundaries
- 先限定验证sounddevice/PortAudio稳定发布版安装、原生权限与默认设备；锁依赖，不引入ASR/LLM/NumPy或重复音频栈。现有.venv为Python3.12.14，Node24/Electron已准备，不无理由重装Node依赖或Electron。
- Python RawInputStream → 轻量回调 → 有界队列 → 写入线程 → WAV。SQLite元信息；用户数据根目录由Electron提供。自动化测试使用隔离目录，不得读写或删除真实用户会议来清理测试。
- 仅默认麦克风、一次一场。不自动录音、不自动换设备、不暂停续录。输入流实际打开才能显示recording。开始前停止回放，录音期间禁用回放。
- 开始/结束幂等；超时不代表未执行，要查询权威状态恢复。stdio控制响应不等待整段录音或长时间flush，音频不走JSON。状态轮询有界、不重叠。
- PCM16 WAV，真实设备支持的采样率。流式写临时文件，结束排空已接受音频、关闭文件、保存元信息；错误不能通过清空文件或重建DB解决。重启恢复已落盘完整帧，不能把interrupted伪装成completed。
- 页面切换/最小化保持录音；窗口关闭、app退出、重连、suspend共用会话保护。保存退出失败时保持界面可见。单实例保护兼容隔离测试。
- 扩展真实历史列表/详情，移除“只允许空列表”和“所有能力都false”的骨架校验。设备名、时长、音量、录音就绪来自实际数据；转写和纪要仍未接入。
- 保持现有中文浅色绿色UI风格，加入活动录音、历史、详情与播放器，错误可操作；普通页面不堆叠协议细节。
- 保留sandbox/contextIsolation、关闭nodeIntegration、校验IPC来源和参数。受限媒体资源只映射合法会议ID，限制根目录及文件并处理Range，拒绝路径穿越和任意本地文件访问；无关设备权限继续拒绝。
- 使用本地Electron声明或官方文档核对API，不猜测；如果原生权限证明既定采集归属不可行，及时报告，不擅自改为第二套录音架构。
- 继续区分开发环境与正式分发。本次不做安装包/内置Python，正式用户无需安装Python的约束不变。
- 实录前通知主Agent时间与操作，采用短时非敏感测试内容和可见录音状态；不擅自改系统隐私设置。缺少OS授权/设备时立即报告具体情况，继续独立工作；合成音频不能冒充实录。

## Verification
按Recorder/Writer/Repository/IPC/生命周期/媒体权限风险做相关检查。真实Electron验证业务闭环及关键失败。跨模块契约需要typecheck；媒体协议/CSP需要相关build+Electron验证。已通过后只在相关代码变更、具体失败或结果不明确时重跑，不追加无关压力/攻击穷举。
Spec001未变区域证据可复用，修改后的共享契约和退出路径必须有新证据。记录命令、结果、测试数、版本和真实/合成输入来源，验收可以复用明确证据。图形验证优先现有Playwright Electron，不申请Computer Use权限或另下浏览器。

## Expected Output
写specs/spec-002-meeting-recording-and-storage/implementation.md：Summary、Files Changed、Important Decisions、Tests、Known Limitations、Remaining Questions。报告API、存储布局、实际锁定版本、未执行项。截图证据放ignored artifacts/spec002/。结束自己的测试进程，不删除用户数据。每个实质进展阶段告知主Agent，完成报告不等于最终独立验收。
