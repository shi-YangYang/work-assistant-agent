# Rework Implementation Report

## Summary

已修复首轮独立验收的六项缺陷及后续 XML 节点兼容问题。业务和测试源码已冻结；本报告不代替最终 [独立验收](acceptance.md) 或 [真实模型评分](performance.md)。原 FAIL 证据保存在 [首轮验收](acceptance-initial.md) 和 [返工验收](acceptance-rework1.md)，未 commit／push，未操作线上或用户开发服务。

## Files Changed

- `integrations/parsing/document_ranges.py`：视觉检测限定实际正文、页眉页脚、注释区域与幻灯片，主题／样式中的几何默认值不再触发；保留真实图像、图表、原生形状和文本框识别。Word 保留 Tab、文本换行和回车，忽略分页换行，与原 paragraph.text 语义一致；嵌套文本框仍只读一次。Excel 先识别累计时长，随后才按日期／时刻转换，公式仍只读保存值。
- `integrations/parsing/office_visual_validation.py`：检查 `fldSimple` 的指令属性、拼接后的复杂 Word 指令、公式以及现有外部关系。活动字段在进入原生渲染前拒绝，安全 PAGE 字段仍允许；测试不会调用地址或渲染攻击样本。
- `agent/context/document_input.py`、`context_usage.py`、`agent/runtime/model.py`：页图选择收到完整工具 schema 和实际相同的输出预留；按最终文字、页来源、图片切片和消息封装计算预算，同时检查请求编码容量。可选图片／缺失说明不再使可容纳的文字请求整体失败。LangChain HumanMessage 与线上的 user 消息使用相同图像预留。当前页优先和重读旧页的规则保留。
- `document_parser.py`、`document_rendering.py`、`tasks/processing/document_ranges.py`：解析及渲染策略升为 v2；历史旧代次在按需读取时先升级，已有首段缓存不能跳过策略检查；不全库预解析，旧代次失败沿用既有保留和提示路径。
- `.github/workflows/ci.yml`：Company 检查显式安装 `poppler-utils` 和 `fonts-noto-cjk`，安装后必须运行既有增强版 `office_preflight`。缺依赖不能仅靠视觉测试 skip 获得假绿。
- `test_document_ranges.py`、`test_document_vision.py` 和新增 `tests/server/agent/context/test_document_input_budget.py`：新增普通 Word 主题误报、分隔符、时长／日期／时刻／公式值、活动字段、紧窗口完整预算、无提示空间降级及旧代次读取回归。

## Tests

只运行返工涉及的子系统，未运行全量产品检查或真实模型调用。

| 检查 | 结果 |
| --- | --- |
| `PYTHONPATH=apps/server .venv-server/bin/python -m pytest -q tests/server/modules/materials/test_document_ranges.py tests/server/agent/context/test_document_input_budget.py tests/server/agent/context/test_context_usage.py` | **22 passed，1.76 秒**；含实际源文件解析、属性／拆分字段拒绝、两切片的精确窗口边界、工具 schema、输出预留、零额外提示空间。 |
| 本次专用 PostgreSQL 15472，`pytest -q tests/server/modules/materials/test_document_vision.py -k 'new_page_batch or short_preload or old_ranges_generation or rejected_images'` | **4 passed，17 deselected，21.99 秒**；真实页处理及模型边界、批次优先、无渲染普通材料、历史解析代次升级、明确拒绝图片的一次降级。外部模型为受控响应。 |
| `PYTHONPATH=apps/server .venv-server/bin/python -m pytest -q tests/server/modules/materials/test_document_parser.py` | **35 passed，2.90 秒**；既有解析语义回归。日志：[parser-regressions.log](../../artifacts/spec072/rework/parser-regressions.log)。 |
| `node_modules/.bin/prettier --write .github/workflows/ci.yml` | 已按项目配置整理，格式未产生额外改动。 |
| `git diff --check` | 业务冻结前通过。 |

### Linux 依赖与原生处理 smoke

以本地已有 `noria-spec071-worker:latest` 为基础，仅安装 `poppler-utils`、`fonts-noto-cjk`，生成临时 `noria-spec072-native-smoke:local`。以现有非 root 用户 `paa`、`--network none`、只读挂载当前后端和 packages，运行 `python -m app.integrations.parsing.office_preflight`。

**通过**：真实旧 DOC／XLS／PPT 转换和读取、DOCX→PDF→PNG，使用 Linux LibreOffice **7.4.7.2**。构建及预检日志位于 [linux-build.log](../../artifacts/spec072/rework/linux-build.log)、[linux-preflight.log](../../artifacts/spec072/rework/linux-preflight.log)；临时 Dockerfile 位于同目录。容器退出后已自动删除。

这证明本次新增依赖和当前原生代码在已有 Linux worker 基础上可工作，**不是新的完整生产 worker 镜像构建，也不是远端 CI 结果**。没有重新下载或构建 Torch，没有修改本机其他容器。

## Remaining Questions

无待定产品决策。冻结源码的准确性／耗时对照已完成，并由新的独立验收 Agent 给出限定范围的 PASS；真实模型失败样本及未验证组合见对应最终报告。本报告不把未执行的新完整镜像、Windows 原生处理或生产压测列为通过。

## XML 非元素节点兼容修复

`document_ranges.py` 的视觉与 Word 区域检查、`office_visual_validation.py` 的渲染前校验仅对字符串标签的实际元素执行 QName 检查，安全跳过 XML 注释和处理指令。正文、页眉及真实活动字段校验保留；未调整提示词、模型流程、预算或普通文件路径。

`test_document_ranges.py` 新增两种节点的回归，覆盖根节点、正文、段落和页眉：正文保持完整、无视觉误判、渲染前检查通过；随后加入真实活动字段仍被拒绝。与现有 Word 分隔符／区域／字段检查合并定向执行：`PYTHONPATH=apps/server .venv-server/bin/python -m pytest -q tests/server/modules/materials/test_document_ranges.py -k 'word_xml_annotations or active_word_fields or plain_word_theme or word_other_regions'`，**8 passed，9 deselected，0.30 秒**。未调用模型、网络或原生渲染，未重复普通 A/B。Python 文件不在项目已配置的 Prettier 范围内。

本节完成后业务和测试源码再次冻结；保留独立验收的原 FAIL 报告，由新验收 Agent 复核，不在本报告中宣称整体验收通过。
