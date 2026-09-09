# Task Handoff — Spec 001 工程验收

## Current Status

本轮验收已完成，结果为 [PASS](../../specs/spec-001-product-and-technical-foundation/acceptance.md)。下文为历史交接记录，不作为重复启动验收的指令。

## Role
Acceptance。仅在实施报告完成后启动的独立工程验收 Agent。不能修改业务代码、测试或工程配置，不能创建子 Agent。

## Goal
验收实际 Electron / Python 工程实现与 Spec 的符合程度，提交 PASS / FAIL 及可复现证据。

## Context
用户已指定 Electron 并要求“开始实施”。用户要求 Spec 决策无需创建子 Agent 验证，本任务只验收已经实施的工程；不要重新讨论已定的桌面框架或替用户做产品决策。

## Project Mode
在已有文档和目录骨架上增量实施。初始存在多份尚未提交的规划文档，注意检查未跟踪代码，不要只看普通 diff。

## Required Reading
AGENTS.md、constitution/mission.md、constitution/tech-stack.md、.ai/rules/spec-decision-workflow.md、specs/spec-001-product-and-technical-foundation/spec.md、plan.md、implementation.md、docs/product-definition.md、docs/architecture.md、.ai/decisions/0004-foundation-stack.md。

## Scope
真实业务代码、配置、测试、README命令及与实现有关的文档一致性。不要为Spec决策本身出独立验证结论。

## Acceptance Criteria
逐项覆盖 Spec AC，并重点检查：
- npm锁文件和真实安装/启动命令；版本与electron-vite peer兼容。
- Electron实际创建窗口，缺少模型、密钥和设备权限不阻断启动。
- Python健康请求真实穿过子进程，renderer不得假造核心连接。
- Python缺失/错误/异常输出/超时/退出的处理，pending请求不永久挂起。
- 进程重试与应用退出清理，Windows路径及shell使用符合设计。
- renderer无Node权限，context isolation/sandbox等边界开启，IPC参数与来源约束。
- UI空状态诚实，无真录音/模型调用，无假会议和假已完成状态；主要操作在最小窗口尺寸可访问。
- 实际测试覆盖关键行为，未运行项准确报告。
- 当前验收范围为macOS实机，Windows验证配置/路径检查；Windows未实测必须列明，不能宣称跨平台运行已经全部通过。
- 构建预览不冒充签名安装包，不因发现后续MVP功能缺失而要求超范围实施。

## Commands
根据 package.json 和技术约束执行相关npm test/typecheck/lint/format/build/Electron smoke，优先一次完整检查；如已有可靠证据，可针对风险独立复验。不要运行不存在的命令，不修改配置来让检查通过。

## Expected Output
写 specs/spec-001-product-and-technical-foundation/acceptance.md，Result只能PASS或FAIL，列Spec Coverage、Tests、Issues、Regression Risks、Required Rework。返回具体问题与文件位置；如发现失败交主Agent安排返工，你不修改实现。截图等证据保存在受忽略的artifacts目录，不写真实密钥或私密会议数据。
