# Implementation Report

## Summary

已实施附件即时上传、通用文本候选和未发送附件清理，等待独立验收。没有提交、推送或部署。

- 文件选择不再使用窄范围 `accept`；共享规则优先拒绝程序／安装包／编译产物、压缩包、镜像和含宏文档，旧版 Office 保留转换提示。未知后缀、无后缀及源码作为文本候选，HTML／SVG 按文档下载。
- 账号范围内的上传协调器随 Shell 挂载，扫描各会话草稿，最多同时上传 2 个；上传期间可编辑正文、导航、移除，失败仅由用户逐项重试。晚到结果不回写已移除或其他身份的草稿。
- 文档卡片约 48px 高，桌面 168px、手机 164px 宽；文件名和状态单行省略，支持查看完整名称，独立重试／移除，上传时显示空心圆。
- 手动发送和 Enter 只消费就绪附件 ID；上传阶段不创建 Agent Job、不解析文档、不进行 ASR。已有媒体有效性检查仍保留。HEIC 预览复用集中上传结果。
- 长按录音仍独立上传、直接发送本次语音，不混入正文或其他草稿附件，不等待其他草稿上传，不出现试听条闪现，不自动重试。
- 新增本人未发送附件 DELETE，复用公司／附件锁与正式绑定保护；提交删除标记后才清理磁盘，清理失败交由 maintenance 重试。24 小时孤儿也先退役后清理；已被工作材料引用的来源受保护。
- 文本解析仍在发送后运行，新增后缀复用 TXT 行分段。解析失败在现有附件错误通道直接显示，不额外调用模型解释错误；已有沙盒原始文件输入协议不变。

## Files Changed

### 规则与后端

- `packages/api-contracts/input-rules.json`、`apps/server/app/core/input_rules.py`：共享附件规则。
- `apps/server/app/modules/attachments/policy.py`（新增）：文件名后缀规范化、禁止项和附件分类。
- `apps/server/app/modules/attachments/documents.py`、`router.py`：通用文本 MIME、上传适配、未发送附件 DELETE。
- `apps/server/app/modules/attachments/lifecycle.py`（新增）：退役引用保护和可重试磁盘清理。
- `apps/server/app/modules/work/materials/service.py`：材料绑定与删除的并发保护。
- `apps/server/app/modules/operations/mutations/deletion.py`、`apps/server/app/tasks/maintenance/maintenance.py`：统一清理及 24 小时孤儿回收。
- `apps/server/app/integrations/parsing/document_parser.py`：通用文本读取、明确读取失败提示，解析版本 `text-v3`。

### Web

- `apps/web/src/api/attachments.ts`、`utils/attachments.ts`：临时删除 API、共享策略、宽泛选择和文件粘贴。
- `apps/web/src/app/layout/Shell.tsx`：集中上传生命周期挂载。
- `apps/web/src/features/assistant/lib/attachment-uploads.ts`（新增）、`hooks/composer/useAttachmentUploads.ts`（新增）：有界上传队列、草稿归属、失败重试、取消及晚到清理。
- `apps/web/src/features/assistant/lib/audio-capture.ts`、`composer-drafts.ts`：逐文件上传状态、直发录音标记、身份暂停／释放。
- `apps/web/src/features/assistant/hooks/composer/useMessageSubmission.ts`、`useRecording.ts`：就绪门槛、仅复用上传 ID、直发语音隔离。
- `apps/web/src/features/assistant/components/conversation/ConversationChat.tsx`：HEIC 预览复用，取消第二条上传路径。
- `apps/web/src/features/assistant/components/composer/MessageComposer.tsx`：发送禁用条件和通用文件粘贴。
- `apps/web/src/features/assistant/components/composer/attachments/ComposerAttachments.tsx`、对应 CSS、`ComposerAudioPreview.tsx` 和对应 CSS：紧凑卡片和上传状态。

### 测试

- 新增 `tests/web/assistant/attachment-uploads.test.ts`，修改 `tests/web/resources/files.test.ts`、`tests/web/dom/assistant/voice-recording.test.tsx`。
- 新增 `tests/server/modules/materials/test_attachment_upload_lifecycle.py`，扩展 `test_document_parser.py`。
- `tests/server/modules/work/test_work_materials.py`：已有回滚断言限定当前 work，不再依赖整个测试库没有其他工作材料；保留文件、原材料和 revision 断言。

## Important Decisions

- 不增加 schema／migration；删除恢复标记使用已有 `extraction_info.cleanup_pending`。仅为测试环境补跑已有 migration，没有迁移日常数据库。
- 正式工作材料使用附件副本，但原始附件 ID 仍保存在来源中，因此清理同时检查实际附件引用和 `source.attachmentId`。
- 取消客户端上传无法保证服务器从未写入；已知晚到 ID 尝试删除，未知 ID 由已有 24 小时回收兜底。
- 已有 `Documents` 错误呈现、原始附件沙盒输入和消息幂等协议满足本次需求，未为此增加模型调用、工具或依赖。

## Tests

验证级别为 S3，仅覆盖本次附件 API／权限／持久化和集成输入框，不运行全项目套件。

### Web 定向检查

初始命令：

```sh
npm run test:web -- tests/web/assistant/attachment-uploads.test.ts tests/web/resources/files.test.ts tests/web/assistant/message-submission.test.ts tests/web/assistant/session-drafts.test.ts tests/web/dom/assistant/composer-attachments.test.tsx tests/web/dom/assistant/voice-recording.test.tsx
```

共 39 项，初次 34 通过、5 失败：音频上传状态覆盖原有时长展示，及录音测试 Harness 尚未挂载新的上传协调器。修复后只重跑失败的两个文件，最后仅重跑 `voice-recording.test.tsx` 修正后的失败提示预期。最终上述 39 项全部通过；没有重复运行已通过且未变化的文件。

`npm run typecheck:web` 执行过一次：发现新增 Attachment fixture 缺失 `duration`，已补 `duration: null`；剩余报告的 6 处错误在未修改的 `tests/web/dom/assistant/message-voice.test.tsx:66–74`，为 mockImplementation 内 `this` 的隐式 any。已用 `git show HEAD:<文件>` 确认同样存在于 HEAD，该文件没有 diff。按任务边界没有顺改，也没有把整个 typecheck 记为通过。

本次修改的 TS／TSX／CSS／JSON 已使用项目安装的 Prettier 格式化；最后补充的 fixture 再单独格式化。

### 后端定向检查

命令由 `.venv-server/bin/python -m pytest -q` 执行；从本地 Settings 读取连接配置后，仅把 database 设置为 `paa_company_test`，通过 `DATABASE_TEST_URL` 注入。没有打印连接密钥。覆盖文件：

```text
tests/server/modules/materials/test_attachment_upload_lifecycle.py
tests/server/modules/materials/test_document_parser.py
tests/server/modules/materials/test_attachment_experience.py
tests/server/modules/work/test_work_materials.py
tests/server/integrations/sandbox/test_input_names.py
```

- 初次运行 66 项：64 通过、2 失败，另有 31 个 teardown 错误。定位为隔离测试库缺少已有 `company_announcement_read` 表，导致清理回滚；非日常数据库或产品 migration 新增问题。
- 在确认数据库名后，只对 `paa_company_test` 执行现有 `python -m app.cli migrate`。不重复已经通过的 33 项 parser 检查。
- 重跑 33 项数据库相关检查：32 通过、1 失败。剩余为已有工作材料回滚用例使用全库 `count == 0`，受前次 teardown 留存数据影响。将其限定当前 work 后单独重跑，通过；未删除未知来源的全库记录。
- 新增且仅执行两个未覆盖用例：删除先于工作材料绑定的事务竞争；TXT 对照新增 PY 混合二进制文件的实际 worker／解析／工具链。
- 最后命令仅指定上述回滚用例及两个新增用例：`3 passed in 4.33s`。最终覆盖 68 项后端检查，全部通过；这里汇总的是各次必要运行的结果，不表示重复跑了完整 68 项。

新增混合文件对照：TXT 与 PY 均真实解析成功、未知二进制文件直接标记读取失败；同一固定 Agent 替身均调用模型 3 次、文档工具 2 次，原文／引用一致，下一条消息读取复用解析版本，不再次运行解析进程。没有调用真实模型。

### 根侧证据

详见 `artifacts/spec070/verification.md`、对应 JSON 与截图，根侧已完成：

- 1440／390／320px 实际 Web 上传交互验证，卡片尺寸、省略和横向滚动正常；最大并发 2，失败重试、切换会话、移除和 Enter 禁发均通过。
- 受控网络旧／新各 5 次：上传每个 300ms、受理 80ms，选文件后编辑 1 秒；发送至受理中位数由 1102ms 降至 131ms。此为上传时机变化的受控对照，不是模型回复加速结论。
- 同一 96,179 字节文本在旧 TXT 和新 TXT／PY／未知后缀／无后缀各 5 次真实隔离解析，分段／行位置一致，中位数均约 20–21ms。
- 真实本地沙盒读取 `.py`、`Dockerfile`、未知后缀文件原始字节成功；为固定输入协议验证，非完整模型执行链测速。

## Known Limitations

- Web 全量类型检查受上述既存测试 `this` 类型错误阻塞；不声明类型检查全部通过。
- 没有执行真实钉钉／Windows 系统文件选择器、真实麦克风或真实模型测试；浏览器模拟移动视口不替代这些环境。
- 请求已经在服务器完成但客户端未收到 ID 时，立即删除无法定位对象，依赖 24 小时清理；这是既定回收边界。
- 本报告不是最终验收结果，由新的独立验收 Agent 检查。

## Remaining Questions

没有需要用户补充的产品决策。等待独立验收。
