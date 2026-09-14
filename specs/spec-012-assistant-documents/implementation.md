# Implementation — Spec 012

2026-09-13 · 实施与返工已通过[独立验收](acceptance.md)；未提交、推送或触发 CI。

## 实现

- `0004_documents` 增加附件提取状态、解析版本／revision、定位分段与回复引用；旧图音频身份及路径保留。上传流式落盘到私有 ID 路径，文件名只作显示；鉴权下载保留原件，提取接口每次最多 3 个分段。
- PDF、DOCX、PPTX、TXT、JSON、MD、CSV 均使用实际解析器；文档处理先于模型绑定，因此缺少 Key 或模型失败仍保留提取结果。单独的 `document` 任务只重试解析，不调用模型。成功解析及同输入已完成 checkpoint 可复用。
- harness 目录／查找／读取仅覆盖本人当前会话及本人已确认工作来源，报告进一步限定本次来源。分段读取证据由服务端保存，引用核对实际附件、revision、分段与授权；模型回复附真实读取范围。仅发文件时，工具阻止直接提出工作进展。
- 删除与解析／工具／回复共用 owner 锁、租约及输入版本；清除原件、分段、checkpoint，以及其他会话依赖被删文件的衍生回复和未确认建议，保留用户原文字及其他已确认工作／报告摘要。
- Web 统一“文件”入口，保留图片与录音；支持文档混图、草稿中的逐文件上传状态、解析卡片、原件下载、分页查看与引用。发送及晚到结果按会话草稿／操作编号隔离。

主要源码：`documents.py`、`document_parser.py`、`models.py`／`0004_documents.py`、`api.py`、`worker.py`、`agent/harness.py`、`deletion.py`；Web 为 `Assistant.tsx`、`Documents.tsx`、`files.ts`、共享 DTO 与局部样式。新增依赖仅 pypdf 6.18.1、python-docx 1.2.0、python-pptx 1.0.2 及其 lxml 6.1.3／xlsxwriter 3.2.9；其他锁定版本未变，已安装到 `.venv-server`。

## 资源边界与修正

每文件 60 秒墙钟、45 秒 CPU、512 MiB 内存、100 页／幻灯片、20 万字符、2000 分段，每段最多 3000 字符。Office 解压合计 64 MiB、单条目 16 MiB、2048 条目及压缩比例校验；PDF 解码流使用当前 pypdf 配置限制为 64 MiB。解析子进程没有服务配置／凭证环境，禁用网络与进程执行，XML 禁止 DTD／实体，不跟随外部关系。

Linux 使用内核资源限额；macOS 因不支持 `RLIMIT_AS`，由父进程监测 RSS 并终止超限子进程；Windows 使用标准库 ctypes Job Object 限制内存、CPU、进程数和句柄生命周期。父进程取消／超时会终止并回收解析进程，子进程另设墙钟限制。

实施中发现并修正：最后分段达到文字上限时误标完整；JSONB 键顺序改变造成 checkpoint 输入不稳定；引用弹窗因轮询替换对象自动关闭；跨会话衍生回复在来源删除后残留。既有语音纠正文案保持，文件版本变化使用独立提示。

## 实际验证

- 解析定向用例 **20 项**：其中 18 项使用真实解析器／子进程（七种格式、正文／表格／备注、后部文字、格式损坏、加密、扫描、编码／JSON／XML 错误、文本／页数／解压上限、取消／超时／内存终止）；2 项是 Windows Job Object API 结构／限额及失败闭合替身检查，**不代表 Windows 实机通过**。
- 专用 PostgreSQL 文档集成 **8 项**、既有管理／checkpoint／语音修订回归 **19 项**通过；只允许 `paa_company_test`，覆盖无 Key 解析、混合附件、幂等、下载／未发送权限、后部片段真实 harness 工具、伪造引用、版本失效、取消／删除竞态、共享来源清理及无重复工具调用的完成图恢复。
- Web 定向 **17 项**通过（文件／草稿／引用、音频、Markdown、分页）；最后发送状态调整后重跑相关文件 3 项。改动文件使用项目 Prettier；相关 ESLint、最新 `typecheck:web` 通过。普通 Web build 已通过，最后发送状态收尾使用类型与定向检查，未重复构建。
- 主 Agent 的日常验证独立于上述自动检查：七种文件真实上传解析、1440／390px、长中文名称、草稿切换、提取分页至行 91–96、引用持续打开、浏览器原件下载及无效 JSON 的独立重新解析；固定模型无网络、不创建业务建议。证据摘要在 `artifacts/spec012/ui-result.json`、`daily-sample-result.json`，截图同目录。主 Agent 已清理本轮自己的样本，原资料保留。
- 主 Agent 已备份并升级日常库；19 张原业务表旧字段摘要及原媒体一致。未运行 CI、Electron、真实付费模型、真实 ASR 或 Windows／Linux部署实机验收。

## 交接

主 Agent 已用 `npm run dev:company` 重启最终代码，API 健康就绪，worker 正常运行。样本工厂 `tests/server/document_samples.py:export_samples(directory)` 与固定工具模型 `tests/server/document_fakes.py:document_model(query='')` 可复用；CI 用例不依赖 artifacts。主 Agent 管理 README、技术栈、日常进程及后续独立验收。

## 来源删除返工（2026-09-13）

- 针对首轮独立验收的 P1，调整 `deletion.py` 中报告／会话删除顺序：在同一 owner 锁事务内先消费 `documentReads`，清除依赖消息的衍生回复与待确认建议，再失效任务并清空上下文；租约 fencing 保持，未保留被删材料缓存。
- `test_documents.py` 新增参数化回归：真实解析、`read_document` 与 `propose_progress` 后，在最终回复尚未写入时删除来源报告；以及删除会话中未确认文档时保留已成为业务来源的后续消息。两种情况均清除待确认摘录，保留用户原文、已确认 Work／Report 快照与无关排队任务，并拒绝旧租约写回。
- 按持久化删除风险仅运行相关删除组：`node scripts/company.mjs test tests/server/test_documents.py -k 'source_deletion_purges_inflight_document_proposals or shared_source_retention_and_admin_purge_chunks_checkpoints or delete_during_real_extraction_cannot_publish_late_result' --tb=short`，**4 passed，6 deselected**；专用库限定为 `paa_company_test`。源码 diff 已检查，Python 不在项目 Prettier 覆盖范围；未重跑解析／Web／全套检查，未操作日常环境、提交、推送或 CI。本次返工已通过新的独立验收，见验收记录。

## 提交配置对齐（2026-09-14）

提交前发现 CI 的数据库名称仍为 `paa_company`，与新增测试库保护不符。已将 Company job 的 PostgreSQL 建库、健康检查、迁移连接及测试连接统一为 `paa_company_test`，触发规则与检查范围不变；仅格式化该工作流并核对上述配置一致性，未重跑业务检查或手动触发 CI。
