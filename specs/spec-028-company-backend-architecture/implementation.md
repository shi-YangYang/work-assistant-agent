# 实施结果

公司共享后端已由 `services/company` 迁至 `apps/server`。保留 `paa_server` 包名与 API、worker、CLI 入口；依赖版本、迁移文件、数据库字段与业务行为不变。

- HTTP 工厂、实例依赖、中间件和异常适配集中到 `http`；路由按业务组织，主要写入事务和查询归各自 commands、service、queries。
- ORM 按业务归属拆分，`db/registry.py` 显式登记；公共配置、校验、权限和基础设施各有明确入口。
- worker 拆为队列、租约、处理器、调度和反馈；harness 拆为策略、模型、工具及编排。任务上下文不再依赖 harness。
- 模型传输、媒体转换和隔离解析归 integrations；更新资源路径、测试导入及实际执行位置的 monkeypatch，删除旧模块门面。

## 验证

改动按 S3 验证，数据库仅使用 `paa_company_test`。

- 全量后端测试首轮 **308 通过、3 失败**；修复新增架构测试的异步标记、依赖边界和钉钉跳转路径后，相关 **34 项全部通过**。
- 新架构测试补齐 Windows 路径兼容后，定向 **3 项通过**。未重复整套已通过的测试。
- 迁移前后 **101 个注册路由契约、完整 OpenAPI、32 张表的 DDL 与索引一致**。不相交路由改为按领域注册，保留重叠路径的匹配优先级。
- 包内导入与 AST 依赖检查通过，无模块循环；已有权限、事务、幂等、租约、SSE、文档和模型调用断言继续有效。

证据位于 `artifacts/spec028/`：`server-tests.log`、`server-recheck.log`、`architecture-final.log`、`contract-comparison.json`。协调 Agent 另行验证 Linux 进程入口、隔离解析及 Web 联调。

使用受控 Provider 验证业务链路，未调用用户真实模型服务，未运行远端 CI、生产部署或桌面构建。未 commit／push；独立验收由协调 Agent 安排。

## 结构检查修复

架构检查以真实模块集合解析导入别名，将 `__init__.py` 归为包名并正确解析相对导入；子模块导入指向具体模块，普通函数／类导入仍指向来源模块。统一边界断言覆盖包自身，保留 `as_posix()` 的跨平台路径处理。临时源码用例覆盖入口／harness／runner 反向依赖、子模块和包循环，以及普通符号与包重导出的无误报场景；业务代码未变。

按 S1 仅执行 `.venv-server/bin/python artifacts/spec028/run-server.py npm run test:server -- tests/server/test_architecture.py`，**13 项通过**，日志见 `artifacts/spec028/architecture-rework.log`。未重复完整后端或其他已通过检查；修复后的独立验收由协调 Agent 安排。
