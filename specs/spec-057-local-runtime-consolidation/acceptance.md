# Acceptance

## Result

FAIL。发现三项与资源归属、在途任务和版本一致性直接相关的问题；日常环境尚未迁移，应先返工。

## Spec Coverage

统一项目、业务／沙盒网络分隔、数据库原镜像与原卷映射、备份恢复核对、迁移专属归属记录及故障回滚已有实现和隔离演练证据。生产 Compose、CD、业务代码及前端未改动。

停止归属与在途任务保护仍有遗漏；运行中的沙盒升级可能继续使用旧代码，尚不满足完整交付条件。

## Issues

1. **P1：显式回滚可以打断仍在执行的沙盒任务。** `scripts/company/local-infra/migrate.mjs:318` 的 rollback 入口仅检查 API/Web 端口和数据库连接／任务，然后在第 325 行调用回滚。独立沙盒可以在这些检查都通过时仍有 `queued` 或 `running` 执行；`rollback()` 随后直接停止 control/runtime。正常迁移已有 `/state/*/receipt.json` 检查，显式回滚缺少对应保护。
2. **P1：启动 control 可以隐式重建不属于本次启动的 runtime。** `scripts/company/local-infra/lifecycle.mjs:76` 的 Compose `up` 没有 `--no-deps`；沙盒 Compose 中 control 声明依赖 runtime。当 runtime 已运行、control 未运行或需要重建时，runtime 自己的启动步骤使用 `--no-recreate`，但后续 control 的 `up` 不带该标志，仍可因镜像或配置变化重建 runtime。生命周期只记录当前 service 的 ID，无法正确追踪这个间接重建，违反“不接管已运行共享服务”的要求。
3. **P2：沙盒构建完成后可能继续使用旧 runtime/control。** `scripts/company/sandbox-local.mjs:139` 在源码变化时构建新镜像并写入构建摘要，随后调用 lifecycle；`scripts/company/local-infra/lifecycle.mjs:80` 对已运行服务始终使用 `--no-recreate`。两个服务都已运行时，新镜像不会应用，健康检查仍可通过并报告就绪，导致升级后的实际代码与构建记录不一致。

## Tests

独立验收读取完整实现 diff、规格、实施报告及以下证据，未重复已经通过且未改动的检查，也未操作日常服务：

- 实施报告：16 项定向 Node 测试、相关 ESLint／格式化通过。
- `artifacts/spec057/docker-migration-rehearsal.json`：真实 PostgreSQL／Redis 的故障回滚、成功／重复迁移、显式回滚、三轮启停及 Redis 重启。
- `artifacts/spec057/sandbox/report.md`：真实沙盒迁移及回滚、历史回执／文件保留，7 组真实 gVisor 执行通过。
- `artifacts/spec057/regression/report.md`：197 项 API 测试通过、1 项既存失败；11 项浏览器测试通过。既存失败为 `test_running_pipeline_cancels_wait_and_cannot_finish[review]`，仍等待已移除的二次模型核对入口，与本次基础设施改动无关，未修改或宣称通过。

上述三项来自明确的调用路径和 Compose 参数遗漏，现有用例未覆盖这些组合。真实 Windows 进程树、完整项目测试和生产部署未执行，远端 CI 未触发。

## Regression Risks

显式回滚可能中断独立沙盒任务；control 的依赖处理可能停止共享 runtime；借用的运行容器可能掩盖沙盒源码升级。已有隔离演练不能排除这些未覆盖组合。

## Required Rework

- 显式回滚在停止任何容器前检查当前归属沙盒的在途执行；发现任务或检查失败时保持环境不变。补充“应用已退出但沙盒仍运行任务”的定向拒绝用例。
- 每个 lifecycle 启动步骤只管理指定服务；依赖由现有明确顺序管理，禁止 Compose 隐式重建 borrowed runtime。补充“runtime 已运行、control 未运行、镜像或配置不同”的归属用例。
- 对已运行服务核对待用镜像／配置。需要升级且服务属于外部启动时，明确提示先停止再启动；不得静默使用旧镜像，也不得擅自重建共享服务。覆盖源码升级与无变化复用两种情况。
- 返工完成后由新的独立验收 Agent 检查；通过迁移安全审查后，再由主 Agent 迁移日常环境、核对数据并重启应用。
