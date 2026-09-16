# 文档解析与附件存储

- 原件放私有文件存储，数据库保存身份、权限、引用、解析版本和可定位文本，供下载、纠正、重解析及回答溯源。受限文字先存 PostgreSQL，不因支持文件就引入向量库。
- 当前使用私有磁盘和持久卷，沿用附件生命周期；多实例或容量增长后可迁到私有对象存储。客户端始终经业务授权读取，不使用公开桶或永久匿名链接。当前不启用 OSS。
- 文档经受限子进程提取原生文字，通过授权工具逐段进入 harness；不开放宿主文件、任意 shell 或全公司资料。存了文件不等于开放公司知识库，共享范围另行确认。
- 首期不做 OCR、复杂图表理解或 Office 转换。以后确需 OCR 时再选择独立模型用途或本地引擎，不提前增加服务。私有磁盘需要配对备份，解析资源限制不能只依赖上传大小。

## 图片与文档处理

- HEIF 使用 [pillow-heif](https://pillow-heif.readthedocs.io/en/latest/) 接入 Pillow，由服务端生成授权预览并[纠正方向](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose)，不依赖浏览器原生解码。原件与派生缓存分开，不增加模型服务。
- XLSX 使用 [openpyxl 只读模式](https://openpyxl.readthedocs.io/en/stable/optimized.html)，区分公式、[已保存缓存值](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html)和缺失结果；不计算公式、不把缓存当成实时结果，不运行宏或外链。
- PDF 文字提取用 [pypdf](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)，原页预览用本地 [PDF.js](https://mozilla.github.io/pdf.js/getting_started/)，不发给公共预览服务。预览与 Agent 读取独立，能显示扫描页不代表完成 OCR。
- [python-docx](https://python-docx.readthedocs.io/en/latest/user/documents.html)／[python-pptx](https://python-pptx.readthedocs.io/en/latest/user/presentations.html) 处理 DOCX／PPTX，不据此宣称支持旧 DOC／PPT；保留段落、页码、幻灯片及备注定位。

格式、预算与用户行为见 [附件方案](../../specs/spec-019-assistant-attachments/plan.md)。对象存储演进可参考 [私有 OSS 应用方案](https://www.alibabacloud.com/help/en/oss/how-to-apply-the-private-permission-to-the-actual-business)，具体下载方式需兼顾撤权和部署环境。
