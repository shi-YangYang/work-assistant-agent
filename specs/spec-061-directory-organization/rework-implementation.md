# Rework Implementation Report

## Summary

修复审计支持模块缺少脚本路径初始化造成的独立收集错误。只修改 `tests/server/_support/http/agent_audit_api.py`：在导入 `faults.evidence` 前，由支持模块定位并加入审计脚本目录，已有路径不重复加入；证据函数仍使用原实现，测试调用者、断言和隔离门禁不变。

## Validation

按 S1 验证，使用本地隔离配置启动两个独立项目测试进程，清除继承的 `PYTHONPATH`，由项目入口设置其正常路径，避免调用者相互初始化或外部路径掩盖问题。

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `npm run test:server -- --collect-only tests/server/audit/test_agent_audit_persona.py` | 4 个用例收集成功，退出码 0 | `artifacts/spec061/rework-audit-persona-collection.log` |
| `npm run test:server -- --collect-only tests/server/audit/test_agent_audit_tool_edges.py` | 8 个用例收集成功，退出码 0 | `artifacts/spec061/rework-audit-tool_edges-collection.log` |

差异仅为依赖初始化与本报告。项目现有 Prettier 配置不覆盖此 Python 文件；未新增格式化器或运行无关检查。

## Limitations

只收集用例，未执行用例正文或重复全量后端／Web 检查。两个既存日报日期假设失败仍按原报告保留，未扩大修复范围。未 commit／push，未修改首次验收报告；最终结论由新的独立验收 Agent 复核。
