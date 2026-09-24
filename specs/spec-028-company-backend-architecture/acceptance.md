# Acceptance

## Result

PASS — 业务重构与运行证据符合预期；架构检查的子模块导入遗漏已修复，经新的独立验收审查，无剩余返工项。

## Spec Coverage

- 后端迁入 `apps/server`，保留 `paa_server`、API／worker／CLI 与部署数据边界；开发脚本、Docker、CI 和有效使用说明的路径同步完成。
- API、worker、harness 已实际拆分。消息及成员命令、工作和报告写入、查询、确定性权限、任务上下文／租约与外部协议分别归属明确；HTTP 和 Agent 复用业务保存逻辑，没有只搬路由或保留万能兼容门面。
- 对照迁移前源码，业务函数、ORM 定义、提示词、工具参数与数值限制保持；提取的命令保留原锁顺序、幂等、版本检查和事务语义。请求依赖仍为 `scope='function'`，设置及 session factory 来自当前应用实例。测试行为断言未删除或弱化，主要 monkeypatch 指向实际调用模块。
- 101 个注册路由条目、80 个 OpenAPI 路径、完整 OpenAPI 与 32 张表的 DDL／索引对照一致；历史 migration 保持。配置根路径、隔离解析脚本及包内音频路径按新层级调整。
- 架构检查基于真实模块集合解析绝对／相对导入及子模块别名，将 `__init__.py` 统一为包名；普通符号保留来源模块依赖，包自身也受边界约束。前次独立依赖审查未发现实际循环，修复后的检查通过；架构说明包含新增接口／业务／工具／任务的位置及真实消息处理路径。

## Tests

已审阅现有证据，未重复执行已通过测试：

- 后端首轮 308 通过、3 失败；相关修复后 34 项通过，Windows 路径处理调整后的架构检查 3 项通过。
- 架构检查返工后定向 13 项通过。临时源码回归覆盖绝对／相对子模块导入、别名、包入口反向依赖、子模块／包循环，以及普通符号和合法包重导出的无误报场景；独立验收核对解析与断言逻辑，未重复执行已通过检查。
- Web API／功能 API／任务连接／钉钉契约 30 项通过。
- 实际 worker 从 `/tmp` 启动、取得测试库进程锁并正常响应 SIGTERM；CLI 入口及测试库迁移成功。临时 Linux 容器中 API／worker／CLI 导入、七种文档与 PNG 的 `python -I` 解析、音频资源读取成功。
- 浏览器员工登录、真实消息／队列与受控模型 `process_job`、确认及编辑工作、生成和提交报告、切换管理员查看团队报告、模型设置读取、问题反馈通过。

日志、契约快照和具体运行边界见 `artifacts/spec028/`，尤其 `runtime-verification.md`、`server-tests.log`、`server-recheck.log`、`architecture-rework.log` 和 `contract-comparison.json`。

## Issues

无未解决问题。原 P2 的 `from paa_server import api`、`from paa_server.agent import harness` 和 `from paa_server.tasks import runner` 均产生具体模块依赖并受对应边界约束；相对导入及包名处理同时补齐，未修改业务代码。

## Regression Risks

未发现需要修改业务实现的功能回归。模型保存／检测、附件、语音、钉钉和桌面授权由受控 API 回归覆盖，不代表真实厂商验证。Linux 验证使用临时容器和只读挂载代码，未重建生产镜像；未执行远端 CI/CD、生产部署或桌面构建。

## Required Rework

无。
