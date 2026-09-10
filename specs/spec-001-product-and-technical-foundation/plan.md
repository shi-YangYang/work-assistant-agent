# Plan — Spec 001

DONE。对应 [Spec](spec.md)，实际实现见 [implementation.md](implementation.md)。

## 模块与数据流

`React UI → 有限 preload API → Electron main → JSON Lines / stdio → Python`。

- `src/desktop/`：窗口、IPC 来源与参数校验、无 shell 子进程、超时 / 重连 / 退出。
- `src/renderer/`、`src/shared/`：中文工作区、空历史、设置与类型契约。
- `src/python/paa_core/`：健康 / 能力、空会议查询、错误响应与退出。
- `tests/`、`scripts/`、根配置：测试、依赖安装和统一构建；沿用已有目录。

## 修改顺序

1. 确认产品与 [工程基线](../../.ai/decisions/0004-foundation-stack.md)，建立锁文件和构建配置。
2. 实现 Python 协议及 main 客户端，先处理核心缺失、乱序响应、超时和退出。
3. 接入隔离窗口、有限 preload 和 React，真实能力未接入时明确禁用。
4. 建立针对性测试、CI 与 README，提交实施报告后独立验收。

## 接口与迁移

带 ID 的 UTF-8 成功 / 错误响应，方法集中定义；preload 不暴露任意 IPC、文件或进程操作。解释器选择支持 `PAA_PYTHON`、项目 `.venv` 和平台回退，不硬编码开发机路径。无业务数据迁移。

## 验证计划

安装 / 开发启动 / 构建预览、类型 / lint / 格式、TS 与 Python 协议测试、真实 Electron smoke。重点覆盖无配置启动、Python 不可用、请求关联和限流、超时 / 非法输出、重连与退出清理、默认及最小窗口、sandbox / CSP / 来源边界。实际命令统一见 [技术栈](../../constitution/tech-stack.md)，结果只记在 [验收](acceptance.md)。

## 风险

Electron 与构建插件须满足 peer 范围，首次二进制安装需要网络；系统 Python 3.9 不满足项目 3.12 基线，不能替换系统解释器。Windows 仅配置检查时须标明未运行；构建产物不等于安装包。
