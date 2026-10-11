# 返工要求

## 独立审计测试导入

首次独立验收发现 `_support/http/agent_audit_api.py` 提取 `evidence` 时未保留原审计脚本路径初始化。全量收集先导入其他文件掩盖了依赖；单独执行人设和工具边界审计测试会报 `ModuleNotFoundError: faults`。

- 让共享辅助模块正确拥有其审计脚本依赖，保持原证据写入行为；不依赖其他测试先执行。
- 不为每个测试目录注入路径，不新增旧路径转发壳，不改变测试断言和故障门禁。
- 最小验证：通过项目入口，分别独立收集 `tests/server/audit/test_agent_audit_persona.py` 与 `tests/server/audit/test_agent_audit_tool_edges.py`。
- 首次失败证据：`artifacts/spec061/acceptance-audit-collection.log`。两个既存日报日期假设失败仍保留，不扩展修复范围。

返工完成后由新的独立验收 Agent 复核，不重复已通过的 Web、后端全量与构建。
