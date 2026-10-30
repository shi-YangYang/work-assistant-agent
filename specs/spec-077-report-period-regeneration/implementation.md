# 周报周期与删除后重建：实现与验证

## 主要改动

- 周报生成前展示完整周一至周日范围、本周／上周快捷选择，日报保持单日。切换日期、报告类型或视图会清除旧错误；异步返回的其他周期错误不会显示在当前周期。
- 主动生成在公司／成员锁内优先查询有效报告，来源有效后以新 ID 创建报告与任务。旧墓碑、旧任务、旧回执和提交版本保留原身份；有效报告部分唯一索引防止同周期重复。
- 定时生成继续尊重删除，有有效报告时优先使用有效报告。仅 report_deleted 待办可因显式生成恢复为 pending，清除旧提交时间，关联新报告；资格撤销和未知原因保持取消。
- 删除清理关联生成／待办准备缓存，生成入口额外识别历史失效缓存。助手 obligation_id 入口使用相同取消原因规则。空来源提示包含实际日期范围，保留 report_sources_empty 和无副作用保护。

## 涉及文件

实际文件与职责见 [plan.md 的目录树](plan.md#改造目录树)。在已有前端修改上接续，新增一个数据库迁移和两个后端回归文件；未改事实来源口径、模型调用链或公共 DTO 字段。

## 关键取舍

- 采用未删除记录的部分唯一索引，保留全部报告身份与引用。
- 历史取消仅在关联已删除报告、当前有效员工、有覆盖周期的未终止资格区间且周期开始后没有资格撤销记录时回填为 report_deleted；其他历史取消为 unknown。本人仍可从报告页创建新报告，但无法确认原因的旧待办不自动恢复。
- 降级前检测同周期重复历史；有重复时明确失败，事务保持新结构与历史记录，不删除墓碑来满足旧约束。

## 验证

验证级别 S3，限报告、调度、相关助手回执和迁移子系统。

- 真实 PostgreSQL 17 临时库升级至 0033 成功。迁移用例在隔离 schema 中验证旧数据与引用保留、可靠／不可靠历史取消回填、仅一个有效报告、重复墓碑共存、无重复时正常降级、有重复时拒绝降级并保留数据。
- 后端定向命令：`.venv-server/bin/python -m pytest tests/server/modules/reports tests/server/agent/completion/test_report_waits.py tests/server/agent/completion/test_report_outcome_recovery.py tests/server/agent/context/test_report_receipt_history.py -q`，连接专用 `paa_company_test`。
- 首次结果为 155 passed、8 failed、72 teardown errors：新测试库缺少 LangGraph checkpoint 表导致清理失败，残留模型服务随后引发密钥见证校验失败；另有新增测试对旧任务重试状态码和迁移路径层级的两处假设错误。修正初始化、清理本任务专用库并修正测试假设后，仅用 `--lf` 重跑受影响项：**73 passed、82 deselected**。其他已通过且未受影响项未重复执行。
- 新增回归实际经过认证 API → 数据库任务队列 → 受控报告模型及事实检查 → 保存 → 提交，覆盖日报／周报删除重建、多个墓碑、并发／幂等、旧 worker 迟到结果、旧 ID 与旧提交／删除、管理员删除后的新草稿可见性、助手旧回执、定时不复活、显式待办恢复、资格撤销／未知原因不恢复和空来源无副作用。
- 前端单文件：`npm run test:web -- tests/web/dom/reports/report-generation-period.test.tsx`，**2 passed**，覆盖跨月／跨年、快捷选择、请求日期、日报切换、旧周期及异步错误隔离。修改的 TSX 与测试文件已使用项目 Prettier 格式化。
- `git diff --check` 通过。测试日志保存在本机 `/tmp/spec077-tests.log`、`/tmp/spec077-tests-retry.log`、`/tmp/spec077-web-tests.log`。

## 已知限制

- 本报告是实施证据，尚待独立验收；未运行真实付费模型、全项目矩阵、生产迁移或生产业务测试。
- 没有 commit、push、部署；远端 CI 未触发。
- 新旧应用代码不能跨新约束混用；发布仍需按现有停服务、备份、迁移、启动流程操作。

## 待确认事项

无待确认产品问题。独立验收可复用本任务专用容器 `paa-spec077-test`（本机端口 60864，数据库 `paa_company_test`，连接参数已单独交接协调 Agent）。验收后由协调 Agent 删除此容器；未触碰其他容器或用户数据库，未启动常驻 Web／API／worker。
