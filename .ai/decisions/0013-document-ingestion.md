# 0013 — 文档解析与附件存储

2026-09-13 · **ACCEPTED**。用户已确认 [Spec 012](../../specs/spec-012-assistant-documents/spec.md) 的格式、非 OCR 范围、用途和私有存储方案；实际依赖、接口和验收结果在实施时记录。

## 决策与理由

- 原文件保存在私有文件存储，数据库保存身份、权限、引用、解析版本和可定位文本。保留原件才能下载、纠正与重新解析；保留定位才能让 Agent 的回答对应证据。解析文字量受限，首版存 PostgreSQL 即可，不因支持文件就引入向量数据库。
- 当前复用服务端私有磁盘和现有附件生命周期，部署时使用持久卷。以后多实例或容量增长时，将原文件迁到私有对象存储（例如阿里云 OSS）；客户端仍经业务授权读取，不依赖公开桶或永久匿名链接。这是演进方向，本轮不购买或启用 OSS。
- 原生文字提取在服务器执行，模型继续用公司配置的在线服务。优先格式专用解析器，便于保留 PDF 页／幻灯片／段落位置；首版不引入 Office 转换服务、完整文档渲染器或本地 OCR 模型。以后若需要 OCR，可单独配置文档识别用途并按协议复用兼容服务；也可部署本地识别引擎，但需要承担运行资源。具体方案留到实际需要时选择。
- 文档作为 harness 的受控业务输入，通过权限校验后的工具逐段读取。沿用既有 Deep Agents／LangGraph runtime、任务恢复与人工确认，不向 Agent 开放宿主文件系统、任意 shell 或公司的全部文件。
- 先围绕会话与已确认业务来源使用材料，未来公司知识库的共享范围、检索、更新和保留规则另行确认；存了文件不自动赋予全公司查询权限。

## 核对依据与取舍

2026-09-13 核对官方资料：

- [pypdf 文本提取](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) 适合带文字层 PDF；不执行 OCR，复杂版式／表格提取有限，压缩文件的解析内存可能明显大于原文件体积。因此必须有单独的运行资源边界，不能只限制上传大小。
- [python-docx](https://python-docx.readthedocs.io/en/latest/user/documents.html) 与 [python-pptx](https://python-pptx.readthedocs.io/en/latest/user/presentations.html) 支持现代 DOCX／PPTX，不能把它们的能力推断成支持旧 DOC／PPT；PPTX 的[演讲备注](https://python-pptx.readthedocs.io/en/latest/user/notes.html) 有独立读取入口。
- [阿里云私有 OSS 应用方案](https://www.alibabacloud.com/help/en/oss/how-to-apply-the-private-permission-to-the-actual-business) 提供应用服务器代理及临时签名访问方式。将来选择哪种方式需结合权限撤销、下载流量和部署环境，当前仍沿用鉴权下载接口。

取舍是首版可较轻地运行并保留多端共享能力，但私有磁盘需要配对备份，文本解析不能替代复杂图表理解。具体格式、限制与用户行为只在 Spec／Plan 维护。

## Spec 019 扩展决策

2026-09-16 · 用户确认扩展发送体验、混合语音、MP3／HEIC／XLSX、图片与 PDF 预览及图片质量，范围及验收状态见 [Spec 019](../../specs/spec-019-assistant-attachments/spec.md)；原 Spec 012 的历史边界保留。

- HEIF 使用 [pillow-heif](https://pillow-heif.readthedocs.io/en/latest/) 接入已有 Pillow 管线，服务端提供受授权的浏览器预览，避免依赖每个浏览器原生解码；按 [Pillow 方向处理](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose) 保留正确显示方向。保留原件、独立派生缓存，不引入新模型服务。
- XLSX 使用 [openpyxl 只读模式](https://openpyxl.readthedocs.io/en/stable/optimized.html) 扩展现有解析子进程；其 [data_only](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html) 读取已保存缓存值，不负责计算公式。因此必须区分公式、缓存与缺失，不能将缓存当作实时计算结果；仍不运行 Office、宏或外部链接。
- PDF 原页预览采用本地打包的 [PDF.js display layer](https://mozilla.github.io/pdf.js/getting_started/)，统一桌面／手机控件与鉴权下载；不将私有文件发给公共在线预览服务。渲染可见内容与 Agent 提取文字是两条独立路径，不因能显示扫描页就声称完成 OCR。
