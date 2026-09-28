# Acceptance

## Result

PASS

新的独立验收 Agent 已审查完整 Spec、实现与返工 diff、相关测试及真实验证产物；未复用前次 FAIL 作为结论，未发现未解决的阻断问题。

## Spec Coverage

- 重试核心独立，工作助手显式启用；首次加 3 次重试、退避、期限、结构化失败分类及父子节点不叠加符合要求。ASR、解析、独立报告 Job 和 Electron 未启用节点重试。
- 原回执恢复问题已修复：业务写入与节点 `receiptId` 同事务提交；已提交结果恢复先于退避和次数预算。恢复重新校验租约、权限、源输入、冻结配置和业务回执，仅用该回执的准确版本替换本次旧读取，再核对其它读取版本；外部修改、删除或撤销不绕过检查。
- 第 4 次提交后响应异常或进程中断可恢复原工具结果，不增加尝试、不重复授权模型、业务写入或报告入队。删除／提交仍走原确认流程；报告工具成功只表示入队。
- worker 恢复保留次数，手动重试保留成功节点及历史；当前配置重处理沿用输入／checkpoint 隔离和业务幂等。逐次模型用量区分真实、未知和未发送请求，节点摘要有边界并清理完成输出。
- DTO 使用字段白名单，SSE 复用授权及 `attempt/fence/seq` 排序。工作助手节点组件支持重试次数、就地恢复、完成摘要、手机布局和键盘展开；旧任务、前置处理及其它页面保留原展示。

## Tests

- 返工最终定向命令：`npm run test:server -- tests/server/test_task_retry.py tests/server/test_task_receipt_recovery.py artifacts/spec029/test_acceptance_recovery_probe.py`，**37 passed**，包含原失败探针、七种业务动作的第 4 次提交恢复以及版本／删除／权限／输入／配置／其它读取变化。此前含架构检查的同批测试 **49 passed**。依据为实施者已执行工具输出整理的 `artifacts/spec029/receipt-recovery-verification.txt`，该文件明确不是原始测试日志。
- 已复核初轮原始日志：Web **189 passed**；前置展示调整后定向 **4 passed**；Web typecheck、修改文件 Prettier／ESLint 通过；报告与用量相关 **24 passed**，核对用量及 harness 恢复相关 **8 passed**。验收未重复运行已通过检查。
- 协调 Agent 使用现有 `deepseek-v4.1-flash` 完成真实创建（6.52 秒）、查询（8.75 秒）及最终 worker 的更新（14.99 秒）。更新 7 节点、5 次真实模型调用成功；工作仅从第 1 版变为第 2 版，只有 1 条成功更新回执，节点引用与回执 ID 一致。已核对 `artifacts/spec029/real-flow.json`、`real-update.json` 和对应截图。
- 已查看浅／深色、390／1280px 的 `nodes-*.png` 及真实创建、查询刷新、更新截图；键盘展开和刷新恢复由协调 Agent 实际操作验证。受控状态截图不作为外部模型故障证据。

## Issues

无未解决问题。

## Required Rework

无。

## Regression Risks

故障与提交窗口使用专用测试数据库和受控模型验证，未向真实服务反复制造付费失败。外部超时请求仍可能被服务商执行或计费，不能承诺外部只调用一次。本验收未改业务代码、操作日常数据库、重启服务或 commit／push；未运行桌面、全仓构建或远端 CI。
