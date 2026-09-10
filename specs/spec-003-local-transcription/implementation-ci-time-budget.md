# Implementation Report — Spec 003 · CI Time Budget

## Summary

根据[真实 CI run 34450871426](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34450871426) 的阶段与任务进度证据，只调整新增转写 smoke 的两处有界等待预算：恢复完成等待 30→60 秒，整个测试 90→120 秒。模型、17.124 秒公开音频 fixture、业务代码、所有通过条件及其他超时均不变。

本轮 Windows 整个 job 再次通过。macOS 明确失败于恢复后的多块推理完成等待；上一轮退出与清理修复已生效，本轮清理正常完成，没有 teardown 卡住。本报告不将新预算尚未运行的结果表述为通过。

## Evidence

已读取主 Agent 下载并核对摘要的 macOS artifact：`artifacts/spec003/ci/34450871426-macos/spec003/transcription-smoke-stages.json`。以下均为该远端运行的实际时间，单位秒，起点为 smoke 开始：

| 阶段 | 实测 |
| --- | --- |
| 已有文字恢复与定位完成 | 6.614 |
| 历史转写完成 | 16.658 |
| 关闭与重启完成 | 19.985 |
| 取消关闭通过 | 22.094 |
| 保留进度并关闭通过 | 22.872 |
| 重启确认为 paused | 24.397 |
| 继续后首次观察到 draining | 27.384；processedMs 0 / pendingMs 17124 |
| 首次观察到一个块已提交 | 51.689；processedMs 8460 / pendingMs 8664 |
| 30 秒等待到期 | 56.769；仍为 draining，error 为 null |
| 清理完成 | 57.627，无额外 teardown 超时 |

错误明确是期望 completed、实际 draining。任务已经提交首块并推进 8460 ms，剩余 8664 ms；这与永久无进展、暂停恢复失败或退出确认未处理有区别。

## Budget Rationale

从首次继续状态到首次观测首块提交，用时 24.305 秒；该值包含轮询采样误差，不是精确的 worker 单块计时。原 30 秒只给剩余块约 5～6 秒，因此不足以覆盖这台远端机器上两个含上下文的真实推理窗口。

恢复等待改为 60 秒：以已观测首块约 24.3 秒估算，两块约 48.6 秒，保留有限的调度与上下文差异空间。第二块实际耗时仍需新 CI 确认；60 秒不是硬件性能承诺，超出仍会失败。完成断言仍严格要求 completed，不能以 draining 或有部分文字通过。

总预算改为 120 秒：本次在继续推理前已用约 27.4 秒，再加最多 60 秒推理等待及已有退出清理期限，90 秒无法给失败清理留下完整空间。120 秒容纳已有阶段和有界清理，不修改各阶段原有模型、历史转写、窗口退出等上限。

本调整只用于跨平台功能集成测试，不改变参考设备上的首字延迟或累计推理性能验收标准，不把较慢 CI 主机描述为产品实时基准。

## Files Changed

- `tests/smoke/transcription.spec.ts`：仅上述两个数值。
- 本补充报告；上一轮诊断和修复报告保留。

## Verification

本轮为 **S0 小配置调整**，按交接要求只检查 diff：确认恰好修改总预算和恢复轮询预算，没有修改模型、fixture、状态断言、其他等待或平台 skip。未运行本机测试、build、lint、typecheck 或格式命令；本机此前约 15 秒的结果不能验证远端预算。

修改后实际验证由主 Agent 提交对应候选并运行 macOS / Windows CI；结果仍待补充，不能提前标记最终 PASS。

## Remaining Questions

无新产品决策。修改冻结，可提交；本 Agent 未 commit / push，未创建子 Agent，没有启动新的测试进程。
