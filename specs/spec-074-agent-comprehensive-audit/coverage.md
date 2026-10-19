# 实际能力覆盖索引

本表将注册能力关联到真实执行记录；“已调用”只说明工具入口有证据，不代表整个工具、所有角色或异常分支通过。各例语义、数据读回与问题见 [主报告](report.md) 和 [问题列表](issues.md)。完整 job／toolCallId／trace 行号在 [机器可复核索引](../../artifacts/spec074/20261017-real-audit/capability-coverage.json)。

## 工具

37 个注册工具，35 个自然发生 dispatch。未使用预制模型工具序列补齐另外两个入口。下表只列前 8 个 case 便于阅读，完整观察全部保存在 JSON，主任务 T、浏览器 B、配对 C/R、性能 P、补充 S、故障 F 分组分别索引。

| 工具 | 真实 dispatch 次数 | 已观察角色 | 部分 case／未调用说明 |
|---|---:|---|---|
| `load_tools` | 191 | admin, employee | B04, B05, B06, B07, B08, B09, B10, B11 |
| `generate_image` | 4 | admin, employee | B10, T78, T79, T80 |
| `read_images` | 11 | admin | B05, C-T69-high, R-T69-low, T69, T71, T73 |
| `save_memory` | 2 | employee | T51 |
| `forget_memory` | 0 | — | T51 通过 save_memory old_text→new_text 局部删除偏好，revision28→29；忘记业务已验证，但未选择forget_memory专用工具 |
| `list_work_updates` | 14 | employee | C-T29-high, R-T29-low, T22, T29 |
| `list_work_materials` | 2 | employee | B07, R-T29-low |
| `read_work_material` | 1 | employee | B07 |
| `inspect_table` | 6 | admin, employee | P-multistep-low-1, R-T14-low, T65, T74 |
| `export_table` | 4 | admin | C-T37-high, R-T37-low, T37, T39 |
| `create_chart` | 2 | admin | T39 |
| `create_document` | 3 | employee | T40 |
| `create_slides` | 1 | admin | T41 |
| `run_python` | 38 | admin, employee | B11, C-T37-high, C-T67-high, F05d, P-execution-high-1, P-execution-high-2, P-execution-high-3, P-execution-low-1 |
| `read_execution` | 7 | admin, employee | B11, T38, T39, T40, T74 |
| `finish_task` | 0 | — | 真实模型未自然选择此工具；未用假工具序列补造 |
| `set_task_context` | 1 | employee | S03 |
| `request_user_input` | 1 | employee | B12 |
| `execute_business_action` | 102 | admin, employee | B04, B06, B07, B08, B12, C-T19-high, C-T29-high, C-T75-high |
| `get_business_actions` | 3 | admin, employee | P-work-low-2, T29, T52 |
| `query_reports` | 10 | admin, employee | C-T29-high, R-T29-low, T29, T34, T36 |
| `query_report_obligations` | 12 | admin, employee | B08, C-T29-high, R-T29-low, T29, T35, T36, T76 |
| `save_deliverable` | 2 | admin, employee | T13, T50 |
| `read_deliverable` | 8 | admin, employee | B11, R-T14-low, T13, T38, T39, T40 |
| `web_search` | 49 | admin, employee | P-search-high-2, P-search-high-3, P-search-low-1, P-search-low-3, T05, T06, T07, T08 |
| `web_fetch` | 73 | admin, employee | P-search-high-1, P-search-high-2, P-search-high-3, P-search-low-1, P-search-low-2, P-search-low-3, T05, T06 |
| `find_work_items` | 36 | admin, employee | B07, B08, B12, C-T29-high, C-T75-high, P-work-high-2, R-T29-low, R-T75-low |
| `get_work_item` | 29 | admin, employee | B06, B08, C-T19-high, C-T29-high, C-T75-high, R-T19-low, R-T29-low, R-T75-low |
| `get_message_context` | 8 | admin, employee | C-T67-high, C-T69-high, R-T11-low, R-T61-low, R-T69-low, T13, T69, T72 |
| `propose_progress` | 1 | employee | S02 |
| `find_documents` | 81 | admin, employee | C-T67-high, C-T69-high, F05, F05b, P-visual-low-3, R-T11-low, R-T61-low, R-T67-low |
| `read_document` | 72 | admin, employee | B05, C-T61-high, C-T67-high, C-T69-high, F05, F05b, F05c, P-visual-high-1 |
| `find_team_members` | 1 | admin | S01 |
| `query_team_business` | 6 | admin | B09, S01, T31, T36 |
| `read_team_source` | 1 | admin | S01 |
| `propose_followup` | 1 | admin | S01 |
| `read_file` | 1 | employee | F05c |

`forget_memory` 未被选中，但 T51 实际通过 `save_memory` 精确替换旧内容，删除人民币偏好、保留回答结构，记忆版本 28→29；用户“忘记”业务已验证，专用工具入口仍是 NOT_RUN。`finish_task` 没有自然调用，不能用最终消息完成代替该工具的直接覆盖。

每个工具的正常断言见 JSON；没有逐工具穷举两角色 × 三权限模式 × 所有边界／故障。跨能力拒绝、恢复及越权测试只按实际 case 的范围成立，不能乘算成 37 个工具全覆盖。

## 七种业务动作

模型 dispatch 和持久化 action 回执是不同观测：确认／续接可产生回执而不再次 dispatch 同一工具。下表也不将“回执存在”当成用户要求的全部字段均正确。

| 动作 | 模型 dispatch | 持久化 action 回执 | 部分 case |
|---|---:|---:|---|
| `create_work` | 72 | 118 | B04, B06, B07, B08, B12, C-T19-high, C-T75-high, F01 |
| `delete_report` | 3 | 4 | C-T29-high, R-T29-low, T29 |
| `delete_work` | 0 | 0 | 无对应 dispatch，参见回执或覆盖缺口 |
| `edit_report` | 0 | 0 | 无对应 dispatch，参见回执或覆盖缺口 |
| `generate_report` | 5 | 10 | B08, C-T29-high, R-T29-low, T29 |
| `submit_report` | 0 | 4 | 无对应 dispatch，参见回执或覆盖缺口 |
| `update_work` | 22 | 34 | B07, B08, C-T19-high, C-T75-high, P-work-high-3, R-T19-low, R-T75-low, T19 |

回执计数是数据库提交观察条数，**不是唯一对象数／成功操作数**；对象 ID、版本、state、changedFields 在 JSON 的 persistedReceipts 中。没有 dispatch 或回执的动作明确保留缺口，不从普通界面编辑推断模型动作覆盖。B08 从 UI 编辑并提交报告有单独真实结果，不等于 Agent 的 `edit_report` 工具路径已执行。

## 任务类型与状态

| 类型 | 观察结果 | 限制 |
|---|---|---|
| message | 有真实 worker job | 主任务、浏览器、故障与负载 |
| report | 有真实 worker job | 含成功及待重试子任务 |
| document | NOT_RUN | 附件处理在 message 链路内完成，未观察独立 document job，不能替代其构造入口覆盖 |

| Job.state | 观察结果 |
|---|---|
| `awaiting_input` | PASS（仅指状态观测） |
| `awaiting_retry` | PASS（仅指状态观测） |
| `cancelled` | PASS（仅指状态观测） |
| `failed` | NOT_RUN（仅指状态观测） |
| `queued` | PASS（仅指状态观测） |
| `running` | PASS（仅指状态观测） |
| `succeeded` | PASS（仅指状态观测） |

`awaiting_confirmation` 属于交互阶段／节点状态；`streaming`、`finalizing`、`withdrawn`、`interrupted` 在本轮是回复流状态，不能混入 Job.state 计算。`awaiting_input` 既可能需要补充，也可能是完整答复后等待下一条消息，必须看正文及 taskOutcome。未观测 failed 不代表失败恢复全部可靠；本轮实际错误多进入 awaiting_retry 或在重试后完成。

## 逐例与矩阵结果入口

- [逐例语义审查](../../artifacts/spec074/20261017-real-audit/semantic-review.json)：主 80 项为 73 PASS／7 FAIL；fresh 配对 24 项为 20 PASS／4 FAIL；补充 3 项为 PASS。不能以 dispatch 次数自动判分，也不将这些样本比例外推为总体准确率。
- 浏览器：[12 条旅程及恢复](../../artifacts/spec074/20261017-real-audit/browser/coverage.json)。原始扩展状态保留，主判定按具体失败与恢复分别列出。
- 故障／并发：[实际变体和未测分支](../../artifacts/spec074/20261017-real-audit/faults-owned/coverage.json)。PARTIAL／NOT_REPRODUCED 是范围说明，不是额外一种产品通过状态。
- [冻结矩阵](test-matrix.md)中未实际触发的变体，按 [主报告的覆盖缺口](report.md#明确保留的覆盖缺口)保留，不将注册表清点等同全部测试通过。
