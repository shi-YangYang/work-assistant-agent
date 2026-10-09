# Acceptance

## Result

PASS。三项返工已修复，日常环境迁移、退出与重启完成。首次 FAIL 保留在 `acceptance.md`；没有改业务代码或重复执行已通过的测试。

## Spec Coverage

- 本地四个服务统一为 `paa-company` 项目，业务与沙盒网络分开；生产 Compose、CD、业务协议及前端保持原样。
- 回滚先核对全部目标和旧容器归属，再检查当前及旧 control 的在途任务；任务存在、回执读取失败或格式异常时，不执行 stop/rm/create。
- 生命周期与迁移逐项 `up` 均使用 `--no-deps`，control 不再间接重建借用的 runtime。
- 运行中的沙盒仅在源码摘要、Compose 配置哈希与镜像内容一致时复用；需要更新时在构建／启动前拒绝接管，提示先 stop/start。
- 本机迁移前后 49 张数据库表的记录数与摘要完全一致；PostgreSQL 原镜像、数据库卷、沙盒 engine/control 持久卷保留，12 个沙盒状态文件摘要一致。socket 按设计使用新卷。
- 实际 PTY Ctrl+C 后，启动管理进程、API reloader/server、worker 和 Vite 全部退出，8000／5174 端口关闭，管理锁释放；迁移预先启动的四个借用容器保持原 ID 与运行状态。再次启动后四服务健康、Web/API 返回 200，开发服务已留在运行状态。

## Tests

独立验收核对当前实现、定向用例及以下执行证据，没有操作日常服务或追加重复测试：

- 返工：17 项定向 Node 测试、相关 ESLint 与格式化通过；真实隔离 Compose 验证借用 runtime 时创建 control、退出归属及源码／配置／镜像更新拒绝，资源已清理。证据：`artifacts/spec057/rework/result.json`、`rehearsal.mjs`。
- 原实施：16 项快速测试通过；真实 PostgreSQL／Redis 故障回滚、成功／重复迁移、显式回滚、三轮启停及 Redis 重启通过。证据：`artifacts/spec057/docker-migration-rehearsal.json`。16 与 17 项存在重叠，不累计为独立用例数。
- 沙盒：真实迁移／回滚、原回执及文件保留，7 组 gVisor 执行通过，覆盖内置工具、九类文件、连续修改、隔离与中断。证据：`artifacts/spec057/sandbox/report.md`。
- 业务与浏览器：197 项后端通过、1 项既存失败；11 项 Chromium 通过，226 次 API 请求无 5xx／页面异常。证据：`artifacts/spec057/regression/report.md`。
- 日常环境：`artifacts/spec057/daily-before.json`、`daily-after.json`、`daily-migration-checks.json`、`daily-migration.log`、`daily-start.json`、`daily-stop.json`、`daily-restarted.json`。独立核对全部表摘要及持久卷／镜像映射，五项迁移断言和退出断言均为 true。

## Issues

无本次范围内待返工问题。既存 `test_running_pipeline_cancels_wait_and_cannot_finish[review]` 仍等待已移除的二次模型核对入口；本次未修改相关业务或测试，不将该失败表述为通过。

## Regression Risks

- Windows 进程树仅验证参数分支，未在真实 Windows 主机验收。
- 未执行全项目测试、完整沙盒资源耗尽套件或真实模型性能评测；现有证据支持本次编排与迁移，不代表模型质量或响应速度提升。
- 未部署生产、未 commit/push，远端 CI 未触发。

## Required Rework

无。
