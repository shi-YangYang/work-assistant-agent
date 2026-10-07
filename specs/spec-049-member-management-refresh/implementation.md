# Implementation

## Summary

- 成员列表改为紧凑姓名／账号、创建时间和操作列；按 URL 关键词搜索，显示真实人数，保留首次加载、刷新、错误和空状态。
- 新增姓名编辑和查看工作入口；团队看板保留返回成员列表的关键词。添加、重置和删除沿用既有真实接口，删除期间禁止重复提交或关闭。
- PATCH 仅接受姓名，拒绝 `active` 等多余字段；只修改姓名，不撤销会话或重算汇报资格。列表新增独立 `MemberListItem.createdAt`，身份响应不变。
- 新增显式历史停用员工清理 CLI：逐成员事务重查范围，复用完整删除流程及持久文件清理队列。正常员工、管理员、其他指定范围外公司不受影响，重复执行与中断恢复可继续；失败、残留和文件核对失败返回非零。
- 同步登录配置提示与升级说明；依赖旧启停 API 的历史测试改用隔离夹具，不恢复该 API。

## Files Changed

- 成员业务与 CLI：`apps/server/app/modules/members/`、`apps/server/app/cli.py`。
- 前端：`features/members/{api,components/{overview,forms,actions}}`、成员路由、团队返回入口、登录配置提示、列表契约。
- 测试：成员管理、清理、输入校验、账号删除、认证并发、钉钉、声纹、权限矩阵、成员 DOM／请求契约及 W15 浏览器流程；`tests/server/member_fixtures.py` 构造历史停用状态。
- 使用指南：`docs/setup.md`。

## Tests

- 相关 Web 测试 140 项通过；Web 类型检查通过。首次新增 DOM 用例的必填标签定位错误已修正；其余已通过项不重复运行。
- 相关后端检查共 68 项通过，包含成员／清理、输入、删除、认证并发、钉钉、声纹、历史资格及权限矩阵。初次专用测试库缺已有迁移，补齐迁移后完成检查。旧测试库残留加密配置导致权限矩阵的临时密钥验证失败，该项在新的专用 schema 执行后通过，未删除旧测试数据。
- W15 成员真实 API 流程通过：添加、搜索、刷新、姓名更正、查看工作与返回、重置、重名字段错误、取消、删除和同名重建；桌面／手机、浅／深色截图。
- W15 状态验证通过：加载、网络失败与手动重试、空列表、长姓名／账号及手机操作菜单。加载／失败／空列表通过浏览器请求控制构造，长文本账号与业务流程使用真实 API。
- 协调 Agent 在独立验收 schema 实际运行清理 CLI：退出码 0，删除 1 个历史停用测试员工，失败、剩余、待清理均为 0。结果在 `artifacts/spec049/checks/cli-cleanup.json`。
- 修改的格式化器覆盖文件已使用 Prettier；diff 检查通过。未执行全量项目测试、构建、真实模型测试。

截图：`artifacts/spec044/browser/spec049-members-visual/`、`artifacts/spec044/browser/spec049-member-states/`。
权限矩阵隔离验证：`artifacts/spec049/checks/isolated-admin-scope.txt`。

## Rework

- 清理事务先获取公司业务 advisory lock，再锁 Company／Member 并重新核对条件，与 HTTP 写操作和 worker 的锁顺序一致，避免与密码重置等操作交错写入。
- 新增一个并发回归：通过 `pg_locks`／`pg_blocking_pids` 确认清理被共享公司锁阻塞；持锁事务改变候选状态后提交，清理跳过该账号，账号和密码保持原值。没有依赖固定 sleep。
- 恢复工作进度 HTTP 响应必须为 200 的原断言，移除无关的 `None` 放宽条件。
- 使用 `.env.web` 的 `DATABASE_TEST_URL` 指向专用 `paa_company_test`，执行 `npm run test:server -- tests/server/test_inactive_member_cleanup.py tests/server/test_company.py::test_real_harness_confirmation_followup_reports_and_visibility`：8 项通过（4.94 秒）。日志：`artifacts/spec049/checks/cleanup-lock-rework.txt`。diff 检查通过；未重复 Web、类型或浏览器检查，Python 文件不在现有 Prettier 覆盖范围。

## Remaining

- 未操作本地日常或云服务器账号；一次清理命令见 `docs/setup.md`，升级时需要执行。
- 未提交或推送；未启动长期服务。浏览器使用协调 Agent 启动的隔离 API／Vite，均已停止；浏览器与单项后端验证的临时 schema、凭据已清理，保留测试日志和截图。
