# Acceptance

## Result

**FAIL**。新的独立验收确认首轮六项返工已落实，但发现一个合法 OOXML 兼容性回归：XML 注释或处理指令使新遍历器抛异常，普通可读 Word 会整份解析失败。修复这一局部问题后重新独立验收；不扩大为其他格式重构。

本轮复核源码摘要为 `c145abd4abd47445787879aa64aca5fa7e407b1cdc2225ed2ba9a76765c1e935`，基线为 `3916434b2059b7366ba5f81d01c1e55eaa5afc23`。验收未修改业务／测试代码，未访问线上、commit 或 push。

## Spec Coverage

首轮六项问题均已核对具体实现和定向回归：纯文字 Word 不被主题误判、Tab／换行保持、Excel 累计时长保留语义、活动字段属性和拆分指令检查、完整请求页图预算及 HumanMessage 归一、CI 显式安装依赖并执行预检。旧解析代次按需升级，版本策略已更新。

普通 Office／PDF 和重复材料追问的受控各 30 对、真实 low／high 各 3 对补测已完成，未发生页面渲染。此前重复材料追问的中位总耗时回归已消除：low **13.640→12.249 秒**，high **15.684→12.457 秒**。所有原始观察保留，准确性与全部时间以 [性能报告](performance.md) 为准。关键字段及时序正确不代表模型解释逐字无偏差；例如“检验后”被扩写成“检验合格后”的额外推断需要在报告中保留。

来源授权、实际输入覆盖、同代续提取、缓存及删除生命周期已只读核对，当前已阅范围没有其他确认的阻塞项。新增能力七类真实对照与缓存／批量对照尚待最终冻结后完成，本报告不提前判定整体通过。原有平台与组合测试限制继续保留。

## Issues

**合法 XML 非元素节点导致可读文件失败。**

- `integrations/parsing/document_ranges.py` 的 `office_visuals`（第 33 行）和 Word 区域检查（第 139 行），以及 `office_visual_validation.py` 第 33 行，对 `root.iter()` 的所有节点直接调用 `etree.QName(node)`。
- lxml 的 XML comment／processing instruction 节点不是普通元素，`tag` 不是字符串。合法 DOCX 中出现这些节点时，上述调用抛 `ValueError: Invalid input tag ... cython_function_or_method`。
- 同一自建 DOCX、同一正文分别加入一个注释／处理指令后，基线解析仍为 `ready`、正文 `SKU A12; quantity 34.` 完整；当前范围提取与渲染前校验均失败。错误与模型无关，也不需要原生转换才能复现。

## Tests

- 只读核对 Spec、Plan、测试矩阵、首轮 FAIL、返工报告、相关源码／测试、浏览器与性能证据。未重复运行已通过的实施检查。
- 在普通性能批次结束、协调 Agent 确认暂停后，执行 `.venv-server/bin/python artifacts/spec072/acceptance/xml-nodes.py`，约 **0.2 秒**。只使用临时 ZIP 和纯解析函数，无数据库、模型、网络或原生渲染。
- 复现脚本：[xml-nodes.py](../../artifacts/spec072/acceptance/xml-nodes.py)；结果：[xml-nodes.json](../../artifacts/spec072/acceptance/xml-nodes.json)。两种节点均复现旧版成功、新版失败。
- 不将未完成的新能力真实对照、新完整生产镜像构建、远端 CI 或 Windows 原生渲染记为通过。现有 Linux 非 root、无网络的定向原生预检仅证明当前代码和新增依赖在已有 worker 基础上可运行。

## Regression Risks

该问题可能由文件生成器或 XML 编辑工具加入的合法注释触发，会把本来可读的普通文件变成解析失败。其修复只需在元素检查处跳过非元素节点；不能因此跳过真实活动字段、外部关系或内容节点。

## Required Rework

1. 在本次新增的相关 XML 遍历处安全忽略 comment／PI，保留实际内容和安全校验。
2. 补一个参数化的直接回归：普通 Word 含 comment／PI 仍有正确正文、不会误判视觉；相同文件中的活动字段仍被拒绝。只跑相关最小检查。
3. 普通基准原件不含这些节点，已采集 A/B 无需全部重跑；保留摘要差异，新增能力组使用修复后冻结版。
4. 新的独立验收 Agent 复核修复和最终性能／质量证据。
