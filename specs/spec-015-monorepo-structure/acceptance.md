# Acceptance — Spec 015

2026-09-15 · 首轮由独立验收 Agent `accept_spec015` 审查基线 `6e83d28` 之后的完整工作区；返工由新的独立验收 Agent `accept_spec015_dependencies` 复核最终依赖清单、锁文件和定向证据，包含未暂存内容。未变化部分沿用首轮已通过结论。

## Result

**PASS**：首轮唯一失败项已修复，根测试的三个直接依赖均显式声明；目录迁移、清理、运行与资源验证符合本 Spec，未验证范围见下文。

## Spec Coverage

- **R1：通过。** 两个应用、三个共享包与两个 Python 程序按职责归属；共享校验不依赖桌面类型，无反向或跨应用源码导入，外部依赖版本／integrity 未升级。根测试依赖声明已补齐。
- **R2：通过。** 原根 npm 命令均保留；开发 cwd、虚拟环境、构建／打包与 Docker 路径匹配。桌面 bundle 和 asar 不携带公司源码。CI 仅调整路径，触发及重型任务分层未扩大。
- **R3：通过。** 无用折叠组件及专属样式没有现行引用；过时产品定义用固定 Git 快照保留。有效测试、迁移、探测音频、评测与许可证未删；旧源码副本已清除，当前文档与历史记录分别维护。

## Tests

独立核对 diff、导入／清单、入口、删除依据及实施证据，没有重复运行已通过的检查。详细结果见 [实施报告](implementation.md) 和忽略的 `artifacts/spec015/`：

- 桌面 42、Web 27、core 92；server 109 项分轮通过（先修正测试库连接，再修正两个公司时区日期假设），断言未削弱；E2E 发现保留 4 文件／10 场景。
- 两端类型、格式／Lint、普通构建、冻结核心与目录包的 runtime-only／许可证／asar 边界验证通过。
- 主 Agent 日常环境启动证据确认原 6 条会议、6 个模型及加密设置不变，公司页面及既有会话正常；未重录音或调用模型。
- Docker 两个目标构建及离线 service import、探测 WAV、Alembic head／根路径检查通过。官方 registry 拉取超时，实际使用临时 Dockerfile 的同版本镜像前缀；正式镜像来源未修改，此结果不证明官方源网络恢复。
- 返工独立核对：根清单与锁记录一致；相对返工前仅根记录变化，相对基线 539 个外部记录的 version／integrity 全部不变；API 类型包仍解析到本地 workspace。Markdown 定向证据为 4/4 通过，相关文件未在证据产生后修改，未重复运行测试。证据为 `artifacts/spec015/dependency-rework-{audit,markdown}.json`。

## Issues / Rework History

**首轮 FAIL（P2）：** `tests/web/markdown.test.ts:1–2` 直接导入 `react`、`react-dom/server`，其他根测试直接导入 `@paa/api-contracts` 类型，但根清单未声明这三个依赖，依赖应用安装结果被 hoist，不符合 Plan。首轮直接导入核对未发现其他未声明项。

**修复与复验 PASS：** 根 devDependencies 补 `react = 19.2.8`、`react-dom = 19.2.8`、`@paa/api-contracts = 0.1.0`，离线同步锁文件；新的独立验收确认声明与直接导入匹配、版本未升级且定向证据有效，无剩余返工项。

## Required Rework

无。

## Regression Risks

Windows、远端 CI、安装卸载、完整 E2E、真实录音和模型推理本轮未执行；不将 macOS／替代镜像验证扩展为这些范围的通过结论。未提交或推送代码。
