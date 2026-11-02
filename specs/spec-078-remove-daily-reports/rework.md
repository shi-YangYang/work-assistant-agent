# 移除日报功能：问题与修复记录

独立验收 FAIL，唯一必修项见 [验收报告](acceptance.md)。

## 问题与证据

`0034_remove_daily_reports.py` 只取消关联聊天 Job 的 queued、running、failed、awaiting_retry，遗漏 `awaiting_input`。日报确认卡已退役，父任务却仍等待确认，消息 GET 后也不终结。

最小复现源码 `/tmp/spec078_acceptance_probe.py`，失败日志 `/tmp/spec078-acceptance-probe.log`。隔离数据库容器 `paa-spec078-test`，端口 55000；连接方式见 [实施报告](implementation.md)。

## 返工范围

- 定向终结日报关联的 `awaiting_input` 任务以及等待确认／提问等仍可恢复的投影，清除该退役等待的可执行信息并保持明确终态。
- 沿用 fence／租约保护；保留原消息、原始工作、周报及无关等待任务。不要通过清空所有会话或取消无关工作实现。
- 检查项目实际任务状态，补上遗漏的活跃等待状态，不只用测试里的一段固定文案匹配。
- 把验收复现场景纳入退役专项，包含消息 API 投影、旧确认／重试不可恢复、无关等待仍有效的边界。

## 验证与交接

新实施 Agent 只处理上述耦合修复，更新 implementation.md 的返工结果；不更改此前通过项的结论，不自行最终验收。只运行退役专项的必要检查及改动文件格式／diff，不重跑既有 713 项矩阵或无关前端检查。随后由新的独立验收 Agent 验收。
