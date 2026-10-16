# Implementation Report

## Summary

业务源码已完成并冻结。本报告保留初轮实施与检查记录；后续修复见 [返工结果](rework-implementation.md)，真实 low／high 对照见 [性能与准确性报告](performance.md)，桌面／手机流程见 [浏览器验证](browser.md)，最终结论以 [独立验收](acceptance.md) 为准。下文表格中的初轮待办不能替代这些最终记录。

- 原件提取改为有界、可续读的分段批次，保留已有进程、解压、内存、时间和输出限制。后续批次追加同一代次，已有 ordinal 与引用保持稳定；搜索可以继续到原来字符、分段、页数和表格上限之后。
- PDF、Word、PPT 与指定 Excel 工作表可在 worker 内产生页面派生物；旧 Office 沿用原有转换边界。页面像素直接装入当前回答模型，不增加图片描述模型、常规探测或固定核对阶段。
- 短文件共享 12,000 字符预载预算；只有能完整放入的正文才预载。纯文字路径不渲染；小型已知页数的扫描／混排 PDF、PPT 可共享页面预算预载，其他页面按工具请求读取。
- 分开记录提取范围、已准备正文、实际成功提供给模型的正文／页图、代码执行来源。页图只在当前压缩后消息仍引用且通过权限、版本和预算校验时装入；新批次优先，同一旧页再次请求也可重新取得优先级。
- 页面缓存、失败恢复、取消及删除接入现有附件生命周期；页引用复用现有来源 UI。上传未发送仍只保存原件，不执行提取、渲染或模型调用。

未进行 commit、push、线上迁移或线上服务操作；无数据库 migration。比较基线为 `3916434b2059b7366ba5f81d01c1e55eaa5afc23`。

## Files Changed

### 原件提取与页面渲染

- 新增 `apps/server/app/integrations/parsing/document_ranges.py`：文本／代码、Word、PPT、PDF、XLSX 的稳定源分段、范围游标和完整性元数据。
- 新增 `apps/server/app/integrations/parsing/document_rendering.py`：受控页面请求、派生 PDF、逐页 PNG、页引用及版本验证。
- 新增 `apps/server/app/integrations/parsing/office_visual_validation.py`：渲染前外部资源／活动内容校验及工作表选择。
- 修改同目录 `document_parser.py`、`process.py`、`office_conversion.py`、`office_process.py`、`office_preflight.py`：独立进程批次参数、原生转换／渲染和真实依赖预检。

### 持久化、私有缓存与 API

- 新增 `apps/server/app/modules/attachments/document_assets.py`：私有处理产物、原件校验、同内容受权复用、跨 worker 原生处理锁及磁盘空间保护。
- 新增 `apps/server/app/tasks/processing/document_ranges.py`：范围续提取、租约／代次校验、稳定追加及局部失败恢复。
- 修改 `apps/server/app/tasks/processing/documents.py`、`handlers.py`：首次准备、历史未知范围按需升级、短文预载及 checkpoint 输入版本。
- 修改 `apps/server/app/modules/attachments/documents.py`、`router.py`：范围 DTO、真实覆盖、已提供页面来源及私有页预览接口。
- 修改 `apps/server/app/integrations/media.py`：原件删除时清理对应派生物。

### Agent 输入和工具

- 新增 `apps/server/app/agent/context/document_input.py`：共享正文／图像预算、页面请求登记、实际模型载荷装配及成功提供记录。
- 修改 `apps/server/app/agent/context/context_usage.py`、`runtime/model.py`、`prompts/evidence.py`：上下文计量、当前批次页图输入、精简材料范围规则及明确视觉拒绝时的一次降级。
- 修改 `apps/server/app/agent/tools/resources/documents.py`、`tools/business/work_records.py`：真实原件搜索续读、页面读取和工作材料兼容。
- 修改 `apps/server/app/integrations/models/transport.py`：区分明确“不支持图片输入”与普通参数、鉴权、额度、网络错误，后者不静默删图继续回答。

### 客户端、部署与测试

- 修改 `packages/api-contracts/src/index.ts`、`apps/web/src/components/media/Documents.tsx`、`apps/web/src/utils/attachments.ts`：页面来源、扫描／局部失败状态及正确引用匹配。
- 修改 `deploy/company/Dockerfile`：worker 的 Poppler／CJK 字体依赖。
- 新增 `tests/server/modules/materials/test_document_ranges.py`、`test_document_vision.py`；修改同目录 `test_document_parser.py`、`test_document_preparation.py`、`test_documents.py`、`test_office_conversion.py`。
- 修改 `tests/web/dom/assistant/legacy-documents.test.tsx`：页面来源预览、旧引用失效和扫描／失败提示。
- 协调 Agent 维护 `docs/setup.md`、`docs/architecture.md`、`constitution/tech-stack.md` 和 Spec 文档；性能 Agent 维护独立对照脚本、合成原件与性能报告，本实施报告不替代其结果。

## Important Decisions

1. **批次边界不等于文件结尾。** `sourceComplete` 只在受支持源范围已连续覆盖至真实结尾时成立；已有持久化分段的末尾、局部搜索未命中不能据此宣称全文结束。Word 的未渲染来源使用段落、表格行列及其他文字区域，不编造原页码。
2. **既有引用稳定。** 正常续读同代追加；解析策略变化建立新代次。历史升级失败保留旧分段及原件。页面缓存不按 24 页或短 TTL 淘汰，避免有效引用无从打开；派生物随原件生命周期删除。
3. **单次处理有界，处理产物跟随附件。** 单次页面请求最多 4 页，普通／详细栅格化边长分别为 1440／2400；与独立图片共享实际输入预算。处理产物不设总量或单附件累计额度，随附件持久化和删除；原生新写入预留最多 32 MB 输出空间并保留 512 MB 磁盘空闲底线。实际空间不足只使相应新范围读取失败，不删除既有页；扩容磁盘或正常删除附件后可重试。原验收中的固定容量限制用例是当时实现的历史记录。
4. **不在 API 渲染、不长持数据库事务。** 重转换／渲染经现有受限 supervisor 执行并共享跨 worker 槽位，轻量文档可继续处理。缓存成功与模型实际收图分别记账，durable 回执只保存受控引用，不保存重复 base64。
5. **失败粒度按页保留。** 页图失败按工作表、页、分辨率登记；同页成功只清理该页失败，其他失败不被掩盖。只有明确的图片输入不支持才允许一次保留文字的模型降级；普通 400、403、额度和网络错误保持原分类。
6. **普通请求不增加固定阶段。** 没有文件的请求没有文档预处理；纯文字不默认渲染；图文读取不经过另一个描述模型。实际等待和准确性必须由性能组对照决定，不能仅凭这些设计断言“没有变慢”。

## Tests

本次按 S3 执行文档／模型输入／权限生命周期子系统检查，没有运行整个产品测试套件。原件、解析子进程、LibreOffice 和 Poppler 为真实处理；需要稳定控制模型动作或故障的集成用例替换外部模型／ASR 响应，不据此宣称真实模型质量。

测试数据库为本次专用本地 PostgreSQL（端口 15472），未使用线上员工数据。详细最终输出位于 `artifacts/spec072/implementation/`。下面分别报告每次命令，数量有交叉，不相加为独立测试总数。

| 检查 | 实际结果与边界 |
| --- | --- |
| `pytest tests/server/modules/materials/test_document_parser.py tests/server/modules/materials/test_document_ranges.py` | **44 passed，6.52 秒**。含真实原件边界后续读、长单段／单元格、105 页 PDF／PPT、Word 其他区域、表格保存日期／公式／隐藏范围。 |
| `pytest tests/server/modules/materials/test_document_vision.py tests/server/modules/materials/test_documents.py` | 当时文件集 **29 passed，60.04 秒**。之后新增生命周期／历史批次用例和取消删除修复分别定向执行如下。 |
| `pytest tests/server/modules/materials/test_document_vision.py -k 'cache_capacity or four_accounts or real_legacy'` | **4 passed，14 deselected，30.30 秒**。缓存容量／清理重试、4 账号快慢故障隔离、真实旧 DOC／PPT 混排。 |
| `pytest tests/server/modules/materials/test_document_vision.py -k multiple_upload` | **1 passed，18 deselected，7.47 秒**。真实 API → worker 多批 16 个混合附件，读取 12 份历史文档，保存合并成果并刷新追问；外部模型／ASR 受控。 |
| `pytest tests/server/modules/materials/test_document_vision.py -k 'cancel_after or bad_page'` | 最后相关修复后 **3 passed，17 deselected，20.55 秒**。渲染后取消／并发删原件不遗留晚到登记或孤儿缓存；局部页失败恢复不丢其他资料。 |
| `pytest tests/server/modules/materials/test_document_preparation.py tests/server/modules/materials/test_office_conversion.py` | 初次 **41 passed、5 failed**；5 项为既有按整行字符串断言与新按单元格定位不一致。保留真实值断言并更新定位方式后，`test_office_conversion.py -k 'boolean or blank_padding'` **10 passed，29 deselected，10.89 秒**。不将最初失败命令表述为全绿。 |
| `pytest .../test_model_stream_errors.py .../test_model_stream_deadlines.py .../test_context_usage.py .../test_document_parser.py` | 初次 **70 passed、4 failed**，4 项均为 parser 用例，后续 parser 最终 44 项命令已通过。该次其余 **39 个模型传输／上下文检查通过**；其中包含流式错误／时限和上下文计量回归。 |
| `pytest .../test_documents.py .../test_document_constraints.py .../test_attachment_duplicates.py .../test_work_materials.py` | 较早检查 **41 passed、2 failed**；2 个文档断言问题已在最终 `test_documents.py` 组合修复并通过。其余重复身份、材料权限和资源限制路径未作相关后续修改。 |
| `npx vitest run --config apps/web/vitest.config.ts tests/web/dom/assistant/legacy-documents.test.tsx tests/web/resources/files.test.ts` | **2 个文件、14 个测试通过，1.12 秒**。 |
| `npm run typecheck:web` | 通过。 |
| 改动的 `Documents.tsx`、`attachments.ts`、`legacy-documents.test.tsx` 定向 ESLint | 通过；相关 TS／TSX 已按项目 Prettier 配置格式化。 |
| `PYTHONPATH=apps/server .venv-server/bin/python -m app.integrations.parsing.office_preflight` | 真实旧格式转换及 DOCX → PDF → PNG 预检通过；本机 LibreOfficeDev 26.8.0.0.alpha0 和 Poppler。**不是生产 Linux Docker 镜像构建结果。** |
| `git diff --check` | 业务冻结前通过。 |

测试命令中的 `pytest` 使用项目 `.venv-server/bin/python -m pytest`；数据库相关检查设置本次隔离的 `DATABASE_TEST_URL`。详细测试路径可在下方矩阵定位；不要求为了报告重复运行已通过检查。

## Spec Coverage

### 功能矩阵

| 项 | 已有实施证据 | 尚需独立核对／明确限制 |
| --- | --- | --- |
| F01 普通路径 | `test_short_preload_budget_is_shared_and_pure_text_never_renders`、模型／上下文回归；预载完整短文件且共用预算。 | 无附件与代表短材料的正式 low／high、受控 30 对耗时由性能组报告。 |
| F02 文字截断 | `test_real_process_continues_past_old_source_caps_without_changing_ordinals`、`test_long_single_paragraph_cell_and_more_than_2000_paragraphs`；真实 TXT／DOCX 边界后可达。 | 受限进程仍可因真实资源上限失败，返回具体范围，不保证任意大小原件。 |
| F03 页数截断 | 105 页 PDF／PPT 原件续读；`test_search_continuation_retains_generation_citations_and_sparse_ranges` 核对尾部搜索、游标与同代引用。 | 真实模型是否正确使用范围信息由性能／独立验收补充。 |
| F04 表格范围 | `test_visible_sheet_cell_and_formula_saved_value_boundaries`、`test_dense_sheet_past_old_nonempty_boundary_and_rotated_blank_pdf`，含 B22050／C22050 稀疏尾部、超过旧非空单元格边界、21 工作表、日期／公式值／合并。 | 不重算公式、不读取隐藏区域；不能把图表图片作为完整统计数据。 |
| F05 Word 混排 | `test_word_other_regions_nested_tables_and_textboxes`；`test_pixels_reach_main_model_citations_are_private_and_repeat_uses_cache[inspection.docx]` 实际页面像素进入 `BoundedChatModel`。 | 批注、嵌入内容、修订删除文字等不能承诺全覆盖；有排除／页面补读提示。 |
| F06 PPT 混排 | 原生箭头／分组与备注探测；流程图 PPTX 和旧 PPT 实际转换、像素装配。 | 图中关系的真实 low／high 答案仍以性能组评分为准。 |
| F07 PDF 混排 | 真实扫描 PDF 页图、空白／旋转页及可读文字并存；无文字不整体判坏。 | 小字详细读取、跨页图表的实际模型解释未由实施 Agent 单独评分；不能用像素已送达替代理解正确。 |
| F08 旧格式 | `test_real_conversion_content_locations_and_original_immutable` 的 DOC／XLS／PPT／RTF／ODT／ODS／ODP；新增 `test_real_legacy_mixed_original_converts_and_provides_pixels` 的 DOC、PPT；原件字节不变。 | 本机真实依赖已测；Linux 镜像安装／字体效果和 Windows 本机未执行。 |
| F09 任务差异 | 可续读工具及精简全量范围要求；多批历史集成用例核对 12 份资料的实际合并成果和正文。 | 完整条款列举与两文件所有差异的真实模型质量不能由受控用例代替，后者尚无实施 Agent 的独立真实样例。 |
| F10 部分失败 | `test_bad_page_and_disk_failure_do_not_discard_other_pages_or_block_later_work`、历史升级失败保留原段落、明确视觉拒绝一次降级／普通协议错误不删图。 | 真实服务商拒绝概率与延迟不由 mock 推断。 |
| F11 图像预算 | `test_new_page_batch_takes_priority_over_old_batch_when_budget_is_full` 包含后续批次及“读旧页 → 多页 → 重读旧页”；共用正文图片预算，未提供页有明确缺口。 | 单张超大页的局部切片／详细读取组合未新增独立全流程评分；原生栅格化与图像输入均有硬边界。 |
| F12 注入与权限 | 私有页 API、缓存归属、跨会话拒绝、工作授权；`test_agent_scope_forged_citations_and_revision_fence` 验证伪造引用与代次边界。 | 未新增像素内攻击提示的真实模型演练；权限边界由服务端确定，材料内容不能形成授权。 |

### 用户流程与故障组合

| 项 | 已执行证据 | 边界 |
| --- | --- | --- |
| J01 上传时序 | API 集成断言上传未发送无 chunks／派生物；桌面／手机浏览器由协调 Agent 执行并保留 `artifacts/spec072/browser`。 | 浏览器最终冻结版结论由协调 Agent 单独报告。 |
| J02 多批历史 | `test_multiple_upload_batches_history_merge_deliverable_and_refresh`：两批各 6 文档＋图＋语音，真实 API、worker、数据库、解析，分页目录、读早期资料、合并成果内容、引用、刷新追问均断言。 | 外部模型动作和 ASR 受控；真实模型性能另报。 |
| J03 重复与同名 | 既有 `test_attachment_duplicates.py`、`test_same_content_pages_reuse_processing_but_keep_distinct_private_ids`；复用处理但不合并来源身份，跨会话访问拒绝。 | 不把不同身份的同字节原件变成公共缓存。 |
| J04 跨任务复用 | `test_pixels_reach_main_model_citations_are_private_and_repeat_uses_cache` 断言重复页不再调用 LO、像素真实装入、压缩掉引用后不误算当前提供；多批优先测试和浏览器来源刷新。 | 保留已准备缓存不代表当前模型仍看得到图片；必须重新引用／装配。 |
| J05 工作材料 | `test_saved_material_rebuilds_pages_after_original_message_deleted`：源消息删除后用独立工作原件重新渲染、读取和下载；既有 work materials 测试补充权限。 | 不依赖被删除源附件的唯一派生物。 |
| J06 取消恢复 | `test_api_cancel_conversion_at_each_boundary_then_retry`、数据库失败新租约恢复、渲染后取消／删原件；真实 supervisor／worker SIGKILL 测试验证进程组和临时目录回收。 | “终止 worker 并重启后继续同一完整 API 任务”没有新增单一端到端用例，取消、租约恢复和进程回收分别验证。 |
| J07 并发故障 | `test_four_accounts_fast_slow_and_failed_worker_preparation_remain_isolated`：4 个临时账号同时有慢旧格式、故障、快速文本、扫描文件，登录、私有身份、后续普通任务均断言。 | 重任务和外部模型故障受控，原件解析／页面渲染真实；不代表生产最大容量压测。 |
| J08 删除清理 | `test_cache_capacity_keeps_ready_citations_and_cleanup_retry_is_safe`：容量触限仍可访问已有引用，清理失败 503 后重试 200；既有 shared-source／work-materials 保留关系断言。 | 只处理测试拥有资料；未触碰线上存储。 |

## Known Limitations

- 本报告不声称全部矩阵的所有组合均已执行。正式准确性与耗时对照、浏览器结果和最终覆盖边界由开头所链接的报告记录；模型遗漏、网络阻塞和未执行项分别列出。
- Word 先转整份 PDF 才能按页渲染，首次转换会增加必要成本；同代 PDF／页面复用避免重复成本。源文字续读仍需在受限进程中重新扫描至指定稳定位置，不保证尾部读取耗时与文件大小无关。
- 不保证复杂 Office 原生对象、修订、批注、外部资源、嵌入程序和缺失字体无损还原。活动内容／外链仍禁止；表格公式只用已保存结果。
- 安全进程限制、图片输入预算、任务时限和磁盘空间检查继续生效。正常源范围可分批推进，但真正超过硬资源限制的范围会局部失败，不无限自动重试。
- 渲染缓存含内容／解析／渲染策略及 LibreOffice 指纹；后续改变栅格化策略或相关依赖时需维护 renderer 版本。已有页不会因简单页数上限自动淘汰。
- 初轮依赖预检在 macOS 执行；返工后已在现有 Linux worker 基础上新增依赖并通过真实原生预检，详见返工结果。未构建新的完整生产 worker 镜像，未运行 Windows 原生渲染或远端 CI。部署文件及 CI 已增加 `poppler-utils`、`fonts-noto-cjk` 和必要预检。

## Remaining Questions

无待定产品决策。源码已在对照期间冻结；最后一个 high 稀疏尾表对照因双臂网络失败未能取得答案，不能将其记为质量通过。其余结果与最终实现验收分别记录在性能报告及独立验收中。
