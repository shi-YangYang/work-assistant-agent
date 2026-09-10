# Spec 使用说明

`specs/` 是项目唯一的功能规格目录。`_template/` 保留空白模板，具体 Spec 的状态见下表。

## 当前 Spec

| 编号 | 名称 | 状态 |
| --- | --- | --- |
| 001 | [产品与技术基础](spec-001-product-and-technical-foundation/spec.md) | DONE：桌面骨架已完成，独立工程验收 PASS；Windows 尚未实测 |
| 002 | [会议录音与本地保存](spec-002-meeting-recording-and-storage/spec.md) | DONE：录音、保存、历史与回放完成，独立验收 PASS；Windows 尚未实测 |
| 003 | [本地语音转写与 Transcript](spec-003-local-transcription/spec.md) | DONE：模型准备、持续转写、历史补转写与恢复完成，独立验收 PASS |

平台证据补充：Spec 003 最终代码 `0b84fe1` 的 [macOS / Windows CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34451673078) 均已通过，包含真实 ASR 及新增 Electron 转写场景；macOS 7 项 smoke 通过，Windows 3 项通过、4 项既有平台受限场景跳过。上表旧 Spec 的实测限制不代表当前 CI 未运行；Windows 物理麦克风仍未验证。详情见 [Spec 003 验证记录](spec-003-local-transcription/verification.md)。

Spec 讨论、起草、决策和文档更新由协调 Agent 直接处理并自行检查，无需创建子 Agent 验证。下文独立验收指业务代码实施后的验收，详见 [Spec 决策工作规则](../.ai/rules/spec-decision-workflow.md)。

## 命名

实际功能规格使用 `spec-XXX-short-name/`，编号按项目已有 Spec 顺序递增。`_template/` 不分配编号，也不代表存在可实施任务。

## 文件职责

- `spec.md`：定义目标、非目标、行为、需求、边界、约束和验收标准，记录待确认问题。
- `plan.md`：说明已确认需求的实施方式、模块、顺序、接口、验证与风险。
- `acceptance.md`：实施后由独立验收 Agent 记录验收结果。
- `implementation.md`：可选，用于保存实施报告。
- `rework.md`：可选，用于记录验收失败后的返工目标。

## 生命周期

1. 先理解项目和需求，再从模板起草具体 Spec 与 Plan。
2. 识别影响实施的关键决策。可以根据用户已明确的信息或项目事实判断的事项，不重复询问。
3. 关键决策已确认、验收标准明确后，才将 Spec 标为可实施。
4. 实施 Agent 按 Spec 工作，返回实施报告并明确验证结果。
5. 创建新的独立验收 Agent，逐项检查 Spec、实现、相关 diff 和验证证据。
6. 验收通过后交付；未通过则明确返工目标，由新的实施 Agent 返工，再由新的独立验收 Agent 验收。

Plan 的调整不能绕过 Spec 改变需求。规格发生实质变化时，应先更新 Spec，并对重要决策留痕。

## PASS / FAIL

正式验收结论仅为 `PASS` 或 `FAIL`。空白验收模板在实际验收前不得填写或暗示已经通过。

- `PASS`：适用的要求已满足，并有相应验证证据。
- `FAIL`：存在未满足的要求或需要返工的问题，必须列明具体事项。

未执行的检查必须标明原因、替代验证与剩余风险，不能表述成已通过。验收 Agent 不修改业务代码，实施 Agent 不负责最终验收。用户明确接受剩余问题时，应记录该决定，不得把已知失败伪写为测试通过。

## 初次目录初始化例外

用户此前明确要求初次目录骨架初始化时不创建 Spec，该次任务已完成。这一范围决定不限制当前及后续 Spec 的起草。详见 [初始化决策](../.ai/decisions/0001-project-skeleton.md)。
