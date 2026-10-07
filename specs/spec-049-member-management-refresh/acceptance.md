# Acceptance

## Result

PASS

## Spec Coverage

- 成员列表、URL 搜索、人数、加载／失败／空状态、姓名编辑、查看工作及返回条件符合方案；移除启停入口，PATCH 拒绝 `active` 和多余字段。
- 姓名修改仅写姓名；列表创建时间使用独立类型，不改变身份响应。删除沿用原业务，清理范围和逐账号事务、失败计数、文件重试具备对应检查。
- 已检查桌面浅色、手机深色姓名弹窗、手机长文本操作菜单、错误状态截图，未见遮挡主要操作或横向溢出；最终验收重新查看桌面列表及手机长文本操作菜单，布局符合设计基准。

## Tests

- 实施报告记录相关 Web 140 项、后端 68 项和 Web 类型检查通过；独立验收审查了对应测试、改动和已保存的权限矩阵结果，未重复运行已通过检查。
- 两项 W15 浏览器结果及请求证据通过：真实 API 的添加、查找、改名、查看工作、返回、重置、删除和重建；加载／失败／空状态由请求控制构造，长文本使用真实 API。
- 协调 Agent 在隔离环境实际执行清理 CLI，退出码 0，删除 1 个停用员工，其余失败／残留／文件清理计数均为 0。未操作日常或生产账号。
- 返工定向检查 `tests/server/test_inactive_member_cleanup.py` 和 `test_company.py::test_real_harness_confirmation_followup_reports_and_visibility` 共 8 项通过；日志为 `artifacts/spec049/checks/cleanup-lock-rework.txt`。最终独立验收审查现有代码、测试和执行证据，未重复运行已通过检查。

## Rework Verification

- 清理在每个账号事务内先获取公司业务 advisory lock，再锁 Company／Member 并重查角色、停用和删除条件，与已有业务锁顺序一致。新增并发测试实际查询 `pg_locks` 和 `pg_blocking_pids` 验证阻塞，并验证持锁事务改变账号状态后，清理跳过过期候选且未改变账号和密码。
- 无关工作进度 HTTP 断言已恢复为必须返回 200；相应完整业务用例通过。

## Issues / Required Rework

无未解决项。未修改验收范围外业务代码。

## Regression Risks

前后端需配套发布；历史停用账号清理需按使用指南显式执行。代码回滚不会恢复已删除账号或录音。未运行全项目、桌面和真实模型检查，这些不属于此次成员管理变更范围。
