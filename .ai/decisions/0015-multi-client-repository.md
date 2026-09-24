# 多端仓库与共享边界

- 同仓库维护 `apps/web`、`apps/desktop`、`apps/server`，各自运行和构建；公司后端供多端复用，桌面本地核心归桌面应用。
- `packages` 只放实际共用的 HTTP 类型、模型参数、品牌资源和声纹引擎；不共享应用私有 CSS，不反向依赖应用。
- Node 使用 npm workspaces 和一个根锁文件，Python 按应用保留独立依赖环境；暂不引入 Nx／Turborepo。
- 配置就近放对应应用，根目录仅保留 workspace 和公共检查配置；未来移动端按技术选择放入 apps，不提前建空工程。
- `constitution`、`specs`、`.ai` 保留产品、规格和 Agent 工作规则职责，不另建重复治理目录。
