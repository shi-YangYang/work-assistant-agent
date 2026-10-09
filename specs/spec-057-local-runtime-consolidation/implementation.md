# Implementation Report

## Summary

本地数据库、Redis、沙盒统一到 `paa-company` Compose 项目；保留四个服务和既有业务协议。生产 Compose、CD、业务代码与前端未修改。

## Files Changed

- `scripts/company/local-infra/`：Compose 配置与调用、管理锁和按容器 ID 清理、一次性迁移／回滚、数据核对、进程树退出。
- `database-local.mjs`、`reply-stream-local.mjs`、`sandbox-local.mjs`、`run.mjs`：共用生命周期，移除重复 docker run，等待应用和本次拥有的服务完成退出。
- `deploy/company/compose.dev.yml`、`compose.sandbox-local.yml`：统一项目、移除固定容器名、明确 business／sandbox 网络。
- `package.json`：`dev:web:migrate`；CI 接入快速编排测试。
- `tests/deploy/local-*.mjs`：生命周期与迁移定向测试、显式启用的真实 Docker 演练。
- README、setup、architecture、tech-stack：更新本地启动、迁移和回滚说明。

## Important Decisions

- 同一开发管理命令持有进程锁。已运行的服务只复用；退出仅停止本次启动且 ID 未被替换的 Redis／沙盒，数据库继续运行。
- 迁移拒绝活动 API/Web 端口、数据库连接、queued/running 任务和沙盒执行；等待人工输入／重试的历史记录保留。
- 数据库备份实际恢复到隔离 PostgreSQL 核对全部用户表摘要，再复用原镜像 ID 与原卷。引擎缓存与控制状态保留原卷，socket 新建。
- 目标容器记录迁移专属标签和实际 ID。回滚不触碰外部服务或被替换的容器；成功移除旧壳后仍可用记录重建原拓扑。回滚保留最新业务数据，不将数据库还原到旧时间点。
- 旧沙盒构建缓存先按原摘要核对；仅编排分组变更不重建镜像，真实源码变化仍会构建。

## Tests

- 快速测试：`node --test tests/deploy/local-*.test.mjs tests/sandbox/local-dev.test.mjs`，16 项通过。
- 本次 MJS 定向 ESLint 通过；修改源码已用项目 Prettier 格式化；`git diff --check` 通过。
- 真实 PG／Redis 演练：`PAA_RUN_DOCKER_REHEARSAL=1 node tests/deploy/local-infra-rehearsal.mjs` 通过。覆盖停止阶段失败回滚、启动后失败回滚、成功与重复迁移、删除旧壳后的显式回滚、再次迁移、三次启动／退出和 Redis 单独重启。三轮约 6.60／6.60／6.58 秒（包含健康等待与停止，不代表模型响应耗时）。原镜像 ID、卷和种子数据摘要一致。证据：`artifacts/spec057/docker-migration-rehearsal.json`。
- Docker 实际解析沙盒关闭配置：仅 PostgreSQL、Redis 和 business 网络，无沙盒变量要求。
- 回归 Agent 的真实沙盒验证通过：旧→新迁移、故障回滚、原回执和文件摘要、engine/control 卷及 runner 缓存一致，7 组真实 gVisor 执行（九类输出、内置工具、连续修改、多用户隔离、中断等）通过。证据：`artifacts/spec057/sandbox/report.md`。此后新增的迁移归属与分流映射修复由定向测试和 PG／Redis 演练验证，未重复全套沙盒执行。
- 主 Agent 安排的业务／浏览器回归：197 项通过、1 项既存过期模型二次核对断言失败；11 项浏览器通过。具体证据位于 `artifacts/spec057/regression/`，不把该既存断言表述为本次通过。

## Known Limitations

- Windows 进程树退出仅验证 taskkill 参数分支，未在真实 Windows 主机验收。
- 本实施 Agent 未停止或迁移用户日常服务；日常迁移与前后数据核对由主 Agent 在隔离演练和审查后执行。
- 无生产部署、真实模型性能评测或全项目测试；未 commit／push，远端 CI 未触发。
- 隔离 Docker 演练资源已清理，证据保留在 artifacts；不删除用户原卷、镜像或凭据。

## Remaining Questions

无待确认产品决策；待独立验收及主 Agent 的日常环境迁移。
