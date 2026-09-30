# 实施报告

## Summary

五个结构化模型工具与 `run_python` 并列，复用授权、幂等、队列、租约、取消、成果保存和下载。内置任务通过 JSON 交给镜像内固定函数，不拼接代码。

- 表格检查与导出、中文图表、DOCX/PDF、可编辑 PPTX 已实现。
- 新增 `0023_builtin_execution` 可空请求字段，保留原 Python 代码及幂等身份。
- 历史阅读区分 Python 与内置任务，参数、数据和警告支持有界续读。
- 工具注册、关闭沙盒时的隐藏与拒绝、节点标签、重试回执及核对说明已接通。
- PPT 按真实字体宽度、固定行距和剩余空间换行分页；Word 去掉模板蓝色边框。大整数避免先转浮点数；超出 Excel 精确整数范围时按文本交付并警告。
- 图表标题、轴标签、图例和类别按实际字体宽度换行；输出分辨率下检查文字边界、重叠及绘图区容量，无法容纳时明确失败，不发布裁切文件。
- 历史记录补充持久错误消息与成果引用的分段阅读。成果版本重新检查会话、当前权限及来源后重建文件引用；失效时仅返回不可用状态，不回放旧下载地址或正文。

## Files Changed

- `apps/sandbox/{app,runner}`：双协议、固定分派、内部工具库与有界结果。
- `apps/server/app/modules/executions`：请求校验、输入映射、共同执行与历史阅读。
- `apps/server/app/agent/{tools,prompts,runtime,completion,context}`：结构化工具接入现有运行链。
- `apps/server/app/integrations/sandbox/client.py`：协议不兼容错误。
- `apps/server/app/migrations/versions/0023_builtin_execution.py`：请求快照。
- `deploy/company/Dockerfile.sandbox`：镜像安装固定分派器与工具库。
- `tests/sandbox`、`tests/server`：工具库、协议、生命周期、迁移及真实执行。
- `docs/{architecture,setup}.md`：能力、限制与镜像更新。

## Important Decisions

- 模型参数使用真实附件／成果引用，授权后替换为本次输入文件名；不暴露宿主路径。
- 重依赖仅由 runner 按需加载。CPU、内存、并发与现有文件限额未增加。
- 内置结果通过固定的独立 JSON 文件传回，不从标准输出猜测 JSON。格式检查、字体检查和视觉检查分别描述。
- 仅内置请求做键排序序列化；旧 Python 控制指纹与业务身份保持兼容。
- 固定黑白灰布局，提供标题和标签；未增加模板编辑器或任意样式参数。

## Tests

主 Agent 统一在独立 PostgreSQL 15445 与 gVisor 沙盒 8045 验证，未修改日常数据库及服务。

已反馈：初版工具库 17 项、协议 14 项、相关服务端 56 项、真实隔离执行 8 组通过。渲染发现 PPT 行距与 Word 模板边框问题后已修复；新增表格精度与协议规范化边界。修改后的定向复测、最终渲染和真实 Agent 结果由协调 Agent 汇总到验收记录，不用初版结果代替最终版本。

实施侧检查：五个模型工具可转换为实际模型 schema，运行时参数不会暴露；真实执行脚本语法检查通过。未重复运行协调 Agent 已执行的检查。

返工定向用例位于 `tests/sandbox/toolkit/test_charts.py` 与 `tests/server/test_execution_history.py`：175 字标题、长标签保留内容、超容量不发布、仅错误消息的失败回执、多个成果文件续读、权限／版本／来源失效和旧记录兼容。实施侧只检查本次 diff；这些新增用例与最终图表渲染由协调 Agent 统一运行，未以旧通过结果代替本次验证。

## Known Limitations

- 常见工具有明确行列／内容容量限制，特殊计算与布局仍使用 `run_python`。
- Word/PPT 可编辑但不保证其他设备字体一致；PDF 嵌入中文字体。实际生成过程不自动宣称完成视觉验收。
- 新工具需更新控制服务及 runner 镜像，再执行数据库迁移；不能只升级业务代码。

## Remaining Questions

最终定向验证和独立验收已通过，见 [验收结果](acceptance.md)。未 commit 或 push。
