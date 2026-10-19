# 报告回执返工

## 改动与验证

报告子任务从失败恢复到排队、执行或成功时，清除 `refresh_generation` 自己写入的固定失败说明。只按这条精确说明清理，不清空全部 `message`，候选内容、没有正文、缺少来源等有效提示继续由原分支处理。没有改变报告生成、提交授权、回执身份或重试机制，也没有增加查询或模型调用。

在已有“子任务失败后原位重试”用例里补充失败、排队、执行、成功四个阶段的说明断言，并模拟失败说明已持久保存的情况。定向执行 `tests/server/modules/reports/test_report_receipts.py`，结果 **7 passed in 2.05s**。这些是确定性模块回归，不能代替真实模型准确性与速度结论。

检查在已迁移并有所有权标记的独占 `spec074_recovery_26e4227b8c91` schema 中运行；结束后经现有环境工具校验并清理 schema、临时文件与凭据，未触及日常服务和正在运行的真实模型对照。环境清理记录在 `artifacts/spec074/20261017-receipt-rework/environment.json`。相关 diff 无空白错误。此次修改 Python，项目格式化器不覆盖 Python。

## 新对照中报告状态的限制

真实修前 `before/results/R-T29-low/result.json` 第一轮有两个独立问题：

- 原请求只要草稿，首次 `generate_report(submitAfter=true)` 被拒绝；模型纠正为 `false` 后，同一服务端事项已成功生成 revision 2，但旧参数拒绝仍留在 `operationFeedback`。现有身份刻意区分提交要求，单纯忽略 `submitAfter` 会有掩盖真实待提交事项的风险。
- 最后模型把“草稿仍在处理中”归为自由文本 `taskInterpretation.remaining`，后续子任务成功仍留下这段待办。它与服务端固定失败说明不同；不能靠清空任意 remaining 或匹配文字，把用户尚未处理的其它要求也删掉。

本次精确说明清理不宣称修复上述两种状态，也不宣称能够保证模型所有完成描述正确。原始证据保留在 `artifacts/spec074/20261017-repair-comparison/before/`，父任务 `1f26abfc-90d0-43ad-a348-80cae7af03b3`、报告子任务 `3ffea7bf-86ae-4a4d-a262-16b3731eeff4`。后续若收敛这类状态，应使用明确的原子任务与授权恢复证据，而非基于自由文本推断。
