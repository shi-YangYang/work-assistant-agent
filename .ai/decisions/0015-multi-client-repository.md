# 0015 — 多端仓库与共享边界

2026-09-15 · **已落地**。用户审查后明确要求开始实施目录重整和全项目无用文件清理；具体映射见 [Spec 015](../../specs/spec-015-monorepo-structure/spec.md) 与 Plan，实施完成与否以验收为准。

## 决策

- 保持一个仓库，以 `apps` 存客户端、`services` 存后端、`packages` 存真实共享代码；Node 部分采用现有 npm 的 workspaces，继续一个 package-lock。Python 保持独立环境和依赖锁。
- Electron 的 Python 核心属于桌面应用；公司 API 与 worker 属于同一个后端，目录整理不引入微服务。共享公司 API 类型、纯参数校验和浏览器 UI，桌面协议留在桌面。
- Android／iOS 仅确定未来放置规则，不创建空项目、不预选 React Native／Flutter／原生框架。CSS 共享包不能被当成原生 UI，业务权限与私有凭证不进入客户端公共包。
- 保留根开发命令和真实用户数据位置。清理依赖入口／引用证据，低频的验收工具、迁移和手动测试不等于无用文件；历史材料用固定 Git 版本追溯。

## 理由与取舍

当前已经有两套客户端及两套 Python 程序，共用顶层配置会扩大以后加入终端时的影响范围。显式包边界有助于独立构建与定位依赖；代价是需同步 Electron cwd／打包资源、Python 路径、Docker 安装和测试发现。

只重命名 `src` 子目录无法解决依赖清单混用；立即拆多仓会增加共享接口的发布协调；引入 Turborepo／Nx 目前没有足够任务规模依据。因此采用原生 npm workspace，不同时更换包管理器或增加调度层。

本方案已实施，替代 [0001](0001-project-skeleton.md)、[0011](0011-company-agent-direction.md) 中“业务统一留在 src／暂不迁移”的阶段性目录约定。`AGENTS.md`、`constitution/`、`specs/`、`.ai/` 的位置和职责保持不变。

## 参考

这是一种适合本项目的常见组织方式，不是唯一行业标准：

- [npm Workspaces](https://docs.npmjs.com/cli/v11/using-npm/workspaces/)：同一根项目管理多个本地包、声明依赖和按 workspace 运行命令。
- [Expo Monorepos](https://docs.expo.dev/guides/monorepos/)：多应用使用 `apps`／`packages` 与包管理器 workspace，说明这种结构可容纳后续移动项目；引用不代表本项目已经选用 Expo。
