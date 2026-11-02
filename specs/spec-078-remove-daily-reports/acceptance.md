# 移除日报功能：验收记录

## 结论

PASS

新的独立验收 Agent 已复核首轮唯一失败项的返工；首轮 FAIL 的证据保留在下文。返工没有改动此前已通过的前端与业务范围，本轮不重复其检查。

## 需求覆盖

- 已独立检查公开契约、默认 weekly、日报参数拒绝、所属及权限检查后的旧 ID 拦截、来源展开、旧回执与业务确认、周报生成及迟到写回路径。
- 已检查当前及历史补偿调度均只选 weekly；待办、提醒、统计和团队查询排除 daily；Web 报告／团队／设置入口与旧日报卡片处理符合删除方向。
- 已检查 0034 使用专门清理流程，不调用会删除原始消息的管理员报告删除函数；正文、候选、修订、日报通知／待办／安排及配置被删除，结构化关联识别涵盖清空 params 的成功操作、ID 字典键与 JSON 工具结果。工作、原始聊天和周报保留边界有实现及混合 fixture 证据。
- 普通按天写作没有关键词封禁；周报的来源、版本、幂等、权限、候选、租约及删除重建保护仍保留。
- 旧日报等待已终结：0034 纳入真实 `awaiting_input` 状态，取消日报确认／结构化日报提问、释放租约并递增 fence。消息投影为 cancelled、nextAction 为 none；TaskInterpretation 使用合法 `completed / remaining=[]`，节点不可恢复，会话任务及 previousTask 清除过期待办。
- 定向保留边界成立：同一消息仍有无关问题或 pending 操作时保留等待；其他会话不受影响。混合问题和其他会话问题的测试实际提交答案并创建续接任务，未仅检查数据库状态。

## 验证

- 复核 `/tmp/spec078-collected.log`：713 行用例身份、713 个唯一身份，无重复。实施各组首轮及定向复验日志与报告的 705 通过、8 opt-in 跳过相符；复验不可与首轮相加。8 项故障测试需要自有故障环境或可丢弃 Redis，本轮未启用。
- 首轮复核后端首轮、修复、补充、剩余模块及退役专项日志；首轮失败与周周期 fixture、跨意图样本及删除后无来源预期对应，相关定向复验已通过。当时退役专项 3 项通过，但未涵盖后续发现的等待确认父任务。
- 复核 Web 首轮 204 项、补充 25 项以及失败文件复验；最终相关 26 项、清理后 21 项通过。复核 typecheck、局部 ESLint、Prettier 日志。没有重复执行这些已通过的检查。
- 首轮独立最小探针 **1 项失败**：`/tmp/spec078-acceptance-probe.log`；复现源码 `/tmp/spec078_acceptance_probe.py`。只使用 `127.0.0.1:55000/paa_company_test` 隔离库，fixture 清理本次数据；临时测试文件已移出仓库。该历史失败不改写为通过。
- 本轮逐项阅读返工后的迁移、专项源码与 `/tmp/spec078-rework-final.log`：退役专项最终 **6 项通过**，包含新增确认／日报对象提问／同消息混合问题 3 项；覆盖消息 GET、旧确认 unavailable、旧重试 409、旧问题拒绝、fence、TaskInterpretation 解析及无关问答实际续接。6 项含原 3 项，不能重复相加。
- 本轮对照实际 `tasks/runtime/waiting.py`、`tasks/feedback/outcomes.py`、`modules/conversations/task/{task_schemas,task_state}.py` 和 `modules/interactions/service.py` 独立审查终态、续接和保留边界，未发现需要额外运行探针的具体缺口；没有重跑已通过的专项、713 项矩阵或前端检查。

## 问题

无未解决阻断项。

### 已修复的首轮 P2：迁移后旧日报确认任务仍停留在等待确认

原位置：`apps/server/app/migrations/versions/0034_remove_daily_reports.py:85`（首轮版本）。

首轮迁移将日报 BusinessAction 标记为 cancelled，并在 API 投影为 unavailable，但只把关联聊天 Job 的 queued、running、failed、awaiting_retry 状态改为 cancelled，遗漏实际存在的 `awaiting_input`。因此旧日报 pending 确认卡失效后，其父任务仍等待已经无法执行的确认；普通消息 GET 不会自动结算该任务。

隔离库复现：

1. 用现有 `legacy_rows` 建立日报、关联 BusinessAction 和聊天 Job。
2. 将动作设为 pending，参数为 `kind=daily`；父聊天 Job 设为 `state=awaiting_input`、`phase=awaiting_confirmation`，nodeExecution 节点引用该动作，taskInterpretation 表示等待确认日报。
3. 执行 0034，再 GET 原消息。
4. 实际：动作返回 `unavailable`；数据库 Job 仍为 `awaiting_input / awaiting_confirmation`，`taskInterpretation.remaining` 仍包含“确认生成日报”。预期：该日报等待得到取消／退役的明确终态。

这是产品状态迁移遗漏，不是测试环境问题或周报 fixture 假设错误。

返工补齐活跃等待状态，并按日报结构化身份终结节点、问题和任务投影；完整节点保留 DTO 所需字段，精简历史节点退役为失效标记。无关等待保留，相关状态契约与新增专项证据满足原返工要求。

## 回归风险

没有执行真实用户库／生产迁移、部署、真实模型调用、手机和桌面浏览器视觉验收、全仓测试或发行构建；已有混合 fixture 不能替代生产备份。未 commit／push，不能宣称远端 CI 通过。验收未修改业务代码，也未停止现有 Web／API／worker；隔离数据库容器保留给协调 Agent。

## 待处理问题

无。原返工要求已完成并通过本轮独立复核；真实环境迁移与部署仍未执行。
