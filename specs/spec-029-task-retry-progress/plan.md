# 实施计划

范围与行为见 [Spec](spec.md)。

## 改造目录

```text
apps/server/app/
├── tasks/
│   ├── retry/                    # 新增：独立异步重试核心
│   │   ├── types.py              # 策略、尝试及失败分类接口
│   │   ├── policy.py             # 次数、退避与重试判断
│   │   └── runner.py             # 执行、等待、取消
│   ├── node_execution.py         # 新增：节点执行、租约与恢复适配
│   ├── node_state.py             # 新增：有界节点状态和手动重试轮次
│   ├── node_failures.py          # 新增：领域错误分类
│   ├── context.py                # 修改：Agent 节点上下文和预算
│   ├── feedback.py               # 修改：授权后的节点快照
│   ├── queue.py                  # 修改：中断后保留次数并恢复
│   ├── serializers.py            # 修改：兼容旧任务的节点 DTO
│   ├── handlers.py               # 修改：仅启用工作助手 Agent 节点
│   └── router.py                 # 修改：失败节点手动恢复
├── agent/
│   ├── model.py                  # 修改：模型节点接入
│   ├── middleware.py             # 修改：工具节点接入
│   ├── tool_nodes.py             # 新增：工具标签、结果和回执适配
│   ├── operations.py             # 修改：业务回执原子关联与读取版本
│   ├── reports.py                # 修改：工作助手内的报告改写核对
│   ├── harness.py                # 修改：稳定标识与恢复边界
│   ├── intent.py                 # 修改：授权核对节点接入
│   └── reply_review.py           # 修改：答复核对节点接入
├── integrations/models/          # 修改：可复用失败分类信息
└── modules/model_services/
    └── usage.py                  # 修改：逐次调用用量和状态
apps/web/src/
├── features/jobs/components/
│   ├── TaskProgress.tsx          # 新增：紧凑节点列表
│   ├── TaskNode.tsx              # 新增：节点与重试状态
│   ├── TaskProgress.module.css   # 新增：局部样式
│   └── JobNotice.tsx             # 修改：仅工作助手接入
├── features/assistant/components/
│   └── MessageCard.tsx           # 修改：传递实时节点快照
└── api/job-feedback.ts           # 修改：节点快照合并
packages/api-contracts/src/
└── index.ts                      # 修改：前后端节点契约
tests/
├── server/
│   ├── test_task_retry.py         # 新增：重试、恢复、权限与幂等测试
│   ├── test_task_receipt_recovery.py # 新增：提交中断和回执恢复边界
│   └── test_search_metrics_feedback.py # 修改：中断后的逐次调用断言
└── web/
    └── task-progress.test.ts      # 新增：节点显示与快照测试
```

节点日志复用 `Job.result`，写入恢复沿用现有业务回执；无需新增表或数据库迁移。

## 模块划分

| 位置 | 职责 |
| --- | --- |
| `apps/server/app/tasks/retry/` | 策略、失败分类接口、尝试执行器；纯异步逻辑，可注入时钟和等待 |
| `apps/server/app/tasks/` 节点适配层 | 工作助手 Agent 节点的标识、持久化状态、租约、恢复及预算 |
| `apps/server/app/integrations/models/` | 提供供应商失败分类依据，保持现有单次调用行为 |
| `apps/server/app/agent/` | 显式接入工作助手模型、工具与核对节点；独立报告流程不启用 |
| `apps/server/app/modules/model_services/usage.py` | 每次实际调用的记录与最终状态 |
| `apps/server/app/modules/operations/` | 写入幂等与已提交回执恢复 |
| `packages/api-contracts/src/index.ts` | 节点、尝试次数、重试等待及快照契约 |
| `apps/web/src/features/jobs/` | 可复用节点进度组件与就近 CSS Modules，仅在工作助手接入 |
| `apps/web/src/api/job-feedback.ts`、`hooks/useJobFeedback.ts` | SSE、只读重连、身份代次与快照合并 |

## 实施顺序

1. 明确工作助手 Agent 的模型、工具和核对执行边界；统一失败类型，区分业务拒绝和暂时性故障。
2. 实现独立重试核心，验证次数、退避、取消、总期限与不可重试错误。
3. 增加有界、可恢复的节点状态；接入 `Job.attempt/fence`、事务和 checkpoint，明确旧任务回退行为。持久化字段变化使用 Alembic 迁移。
4. 仅为工作助手 Agent 接入模型／核对和工具执行，逐次记录用量；清理该链路的重叠重试，校正耗时与逻辑调用预算。保留 ASR、文件解析和独立报告任务的策略。
5. 验证写入后异常、父子节点传播、报告入队和进程恢复；仅在有回执或幂等保障时重放写操作。
6. 扩展工作助手 Job DTO／SSE 的节点快照，复用现有权限校验与版本排序；旧任务和其他 Job 维持现有回退行为。
7. 将紧凑步骤组件接入工作助手消息，完成移动端和错误状态视觉检查。

数据流：工作助手 Agent → 节点适配层 → 重试核心 → 单次模型／工具操作 → 持久化结果与节点快照 → SSE／查询 → 聊天内节点进度组件。

## 验证

实施涉及共享执行机制、持久化与权限恢复，按 S3 选择相关验证：

- 核心测试：初次成功、先败后成、耗尽、退避、Retry-After、取消、剩余期限。
- 服务端测试：不可重试错误、部分响应、子节点失败不放大次数、结构化工具失败、用量记录、回执幂等、权限撤销、输入变化及 worker 恢复。
- 范围隔离测试：共享模型、HTTP 客户端与 Job 组件不会改变语音转写、文件解析、独立报告任务的重试行为或其他页面展示。
- 前端测试：节点合并、次数显示、手动重试、刷新恢复、断线与身份切换；执行 `npm run test:web`、`npm run typecheck:web`。
- 使用 `npm run test:server -- <相关测试文件>` 验证后端子系统；新增迁移在专用测试数据库升级验证，不对用户日常数据执行破坏性测试。
- 对修改文件运行项目格式化器；检查相关 lint。以浏览器检查浅／深色和手机宽度，不改登录页或 Electron。
- 本地真实验证工作助手创建／查询流程；报告工具只验证入队与回执幂等。可控故障验证重试，临时数据完成后清理，保留用户原有记录。

## 风险与交付

- 供应商可能已处理超时请求：每次尝试独立记录，不能承诺外部只产生一次用量。
- 业务提交后连接中断：回执优先，无法判断结果的写操作停止核对。
- 子调用吞掉异常、全局预算提前耗尽、恢复后次数归零是重点检查项。
- 决策阶段仅检查文档；确认后由实施 Agent 开发，新的独立验收 Agent 验收。通过后再编写精简验收结果。
