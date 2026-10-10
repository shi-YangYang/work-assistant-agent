# Implementation Rework

## Summary

- 回滚先核对全部目标容器的项目、服务、迁移标签与 ID，再检查当前及旧 control 的在途回执；存在 queued/running、读取失败或输出不可解析时，不停止、删除或重建容器。
- 迁移和生命周期的逐项 `up` 均使用 `--no-deps`，依赖按 runtime → control 的明确顺序启动。
- 借用运行中的沙盒前，检查源码构建摘要、Compose 配置哈希与镜像内容；需要更新时提示先 stop/start，在构建和启动前拒绝接管。镜像使用 Config、Layers、架构和系统核对，兼容 Docker Desktop 的 manifest/config ID 差异。

## Files Changed

- `scripts/company/local-infra/lifecycle.mjs`：借用服务的一致性检查与禁止隐式启动依赖。
- `scripts/company/local-infra/migrate.mjs`：回滚预检、服务归属检查与显式启动顺序。
- `scripts/company/local-infra/migration-data.mjs`：迁移与回滚共用的沙盒在途检查。
- `scripts/company/sandbox-local.mjs`：构建前执行复用检查，共享镜像身份核对格式。
- `tests/deploy/local-infra.test.mjs`、`local-infra-migration.test.mjs`：新增三个缺失组合。
- `docs/setup.md`：运行中沙盒更新的 stop/start 操作说明。

## Tests

- `node --test tests/deploy/local-infra.test.mjs tests/deploy/local-infra-migration.test.mjs tests/sandbox/local-dev.test.mjs`：17 项通过。新增覆盖忙碌／不可读回执回滚零 stop/rm、无关 control 不读取、借用 runtime 下创建 control、无变化复用与更新拒绝。
- 隔离真实 Compose 演练通过，约 5.6 秒：已有 runtime → lifecycle 创建 control，runtime ID 不变；退出只停止本次 control；真实配置哈希及镜像内容核对可复用，源码与配置变化被拒绝。镜像变化分支读取两个不同的已有本地镜像内容验证，未改动镜像标签。证据：`artifacts/spec057/rework/result.json` 与 `rehearsal.mjs`。
- 修改源码已用项目 Prettier 格式化；相关 ESLint、`git diff --check` 通过。

## Limitations

隔离演练资源已清理，未操作日常容器、API 或 worker。未重复已通过的业务、浏览器或完整沙盒套件；原实施报告中的既存业务断言失败与 Windows 限制不变。未 commit/push，待新的独立验收与主 Agent 执行本机迁移。
