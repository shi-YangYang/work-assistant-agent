# Task Handoff — Spec 002 独立工程验收

## Role
Acceptance。仅在implementation.md完成后由新的独立Agent执行。不创建子Agent，不改业务代码/测试/配置，不commit/push，只写Spec002 acceptance.md。

## 当前返工验收
已完成：最终 acceptance.md 为 PASS，ISSUE-01 闭环；下文保留当时交接要求，不应据此重复启动验收。

首轮验收已完成并保留为 Spec 002 acceptance-round-1.md，FAIL 仅为 ISSUE-01：暂时存储故障后原始音频被永久跳过恢复。新的验收 Agent 应在 implementation-rework-1.md 完成后启动，同时读取 rework.md 和首轮报告，重点核对 Recorder 异常收尾、Repository 首次恢复失败两条路径在故障撤销后的重试、有效帧与受限播放关联。原先 AC-01..05、AC-07..09 已通过的代码和证据未变时直接复用；仅对实际返工差异和具体疑点补最小检查。保留首轮 FAIL 历史，最终结论写 acceptance.md。

## Goal
按Spec002实际实现与证据验收录音、保存、重启回放、故障与权限边界，结论PASS或FAIL。

## Required Reading
AGENTS.md（特别是验证与停止规则）、constitution/mission.md和tech-stack.md、.ai/rules/、Spec002 spec.md/plan.md/implementation.md、决策0005/0006、相关diff与测试。纯Spec决策不重新验证。

## Scope
逐项AC检查。重点是真实录音保存重启回放、重复/并发开始结束与超时恢复、退出/重连/休眠收尾、已有数据保护、媒体ID与路径访问限制、实机和模拟输入证据区分。检查包含未跟踪文件的改动，不能只看普通git diff。

## Verification Rules
S3具体理由为权限、持久化、共享IPC与退出流程。优先读实施报告和可核对结果，不无理由重复通过命令。独立代码审查与必要的未覆盖风险探测可以开展；代码变更后未验证、结果不明确或发现具体问题时，再选最小检查并说明依据。独立验收不等于全量复跑。
AC02必须有至少一个平台的真实麦克风实录证据；生成PCM或测试输入不能代替。Windows缺少实机可按Spec标未验证。未满足AC写FAIL及具体所需条件，不自行降级或改代码。

## Expected Output
specs/spec-002-meeting-recording-and-storage/acceptance.md，含Result、Spec Coverage、Tests、Issues、Regression Risks、Required Rework。明确实施证据与独立执行项；检查通过且无具体问题后立即停止。临时探测只写ignored artifacts/spec002/并隔离数据，清理自身进程。
