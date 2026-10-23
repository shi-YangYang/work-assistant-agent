# 实施计划

对应 [规格](spec.md)。保留当前工作区的 ReportsOverview 与定向前端测试，不从头重写。

## 修改顺序与数据流

1. 收束界面：显示公司本地周期范围和快捷选择，核对现有本地用例；仅在对应代码修改后重跑已通过用例。
2. 将报告全表周期唯一约束替换为未删除报告的部分唯一索引。新主动请求在成员／公司锁内查当前有效报告；不存在时先检查来源，再创建新的报告和任务。墓碑只用于抑制定时补回及确认可恢复待办，不重置旧报告。
3. 同步调度中的周期查询、删除后的幂等回执清理、待办重新关联和取消原因区分。人工重建与旧 worker／删除重放必须靠对象身份和现有 fence 隔离。
4. 空来源错误补真实周期；工具 Schema 文档明确周报的日期语义，不增加模型节点。
5. 实施 Agent 返回报告后，由新的独立验收 Agent 检查 diff、迁移、权限及必要测试证据。

## 改造目录树

仅列涉及项，文件原位修改；新增迁移与测试按现有目录归属。

```text
specs/
├── README.md                                      [修改] 登记规格与生命周期
└── spec-077-report-period-regeneration/            [新增] 本规格
    ├── spec.md                                   [新增] 行为和边界
    ├── plan.md                                   [新增] 实施与验证
    ├── implementation.md                         [新增] 实际实施结果
    └── acceptance.md                             [新增] 独立验收证据
apps/web/src/features/reports/components/overview/
├── ReportsOverview.tsx                           [修改] 汇报周期、请求一致与旧周期错误隔离
└── ReportsOverview.module.css                    [修改] 周期控件窄屏布局
apps/server/app/
├── migrations/versions/0033_report_regeneration.py [新增] 有效报告唯一索引、取消原因与安全降级
├── modules/reports/
│   ├── models.py                                 [修改] 有效报告唯一索引与取消原因
│   ├── service.py                                [修改] 新报告生成、串行化和周期错误
│   ├── commands.py                               [修改] 可恢复待办和历史幂等入口
│   ├── router.py                                 [修改] 生成入口复用历史幂等校验
│   └── scheduling/schedule.py                    [修改] 活跃报告查询、取消与重新关联
├── modules/operations/
│   ├── mutations/deletion.py                     [修改] 删除时清理待办准备缓存
│   ├── service.py                                [修改] 助手支持可恢复汇报待办
│   └── receipts.py                               [修改] 历史空来源回执提示实际周期
├── tasks/maintenance/scheduling.py                [修改] 资格撤销原因
└── agent/
    ├── reports.py                                [修改] worker 空来源错误含实际周期
    └── tools/business/actions.py                 [修改] 周报日期参数语义
tests/
├── web/dom/reports/report-generation-period.test.tsx [新增，接续已有修改] 周期到请求与错误隔离回归
└── server/modules/reports/
    ├── test_report_regeneration.py               [新增] 删除、重建、调度和并发边界
    ├── test_report_regeneration_migration.py     [新增] 真数据库升级及回退保护
    └── test_report_empty_sources.py              [修改] 空来源周期与无副作用
```

若实现需调整具体文件，只更新实际树；不扩展无关业务。

## 迁移与风险

- 升级保留全部旧报告及 FK，只更换“有效报告”的唯一约束。新建索引与删除旧约束在迁移事务中完成；不得在生产自行执行。
- 若需要取消原因列，明确区分报告删除、资格撤销和无法判断的旧记录。旧取消只有关联已删除报告、当前为有效员工、有覆盖该周期的未终止资格区间且周期开始后无资格撤销记录时，才回填为报告删除；其余保持 unknown。
- 新旧代码不能混用新约束，按既有停服务／备份／迁移／启动流程发布。重复周期墓碑出现后，降级不能靠删数据满足旧约束。
- 重点风险是旧对象身份复活、旧任务迟到写入、新报告被旧删除重放删除、恢复错误的汇报义务和旧幂等响应指向墓碑。

## 验证与停止

- 复用 `.venv-server/bin/python`、项目 pytest 配置及 `DATABASE_TEST_URL`，只允许专用 `paa_company_test` 数据库。可按需创建本任务专用临时 PostgreSQL 容器，结束清理；不启动 Web/API/worker 常驻测试环境，不使用生产库。
- 定向报告模块、删除／重建及调度回归；受控报告模型经过真实 API → 队列 → 来源校验 → 保存 → 提交，覆盖日报／周报、管理员删除后的新草稿权限、空来源、并发、旧任务 fencing 和重复删除。
- 真实 PostgreSQL 测试迁移升级、部分唯一索引及降级保护。原迁移约束和已删除数据保留必须得到实际断言。
- 前端只跑变更影响的定向交互测试；源码按已安装 Prettier 格式化。已通过且未改动的测试不重复执行。
- 不运行完整项目矩阵或真实模型，不读写生产；相关证据充分且独立验收通过后停止。
