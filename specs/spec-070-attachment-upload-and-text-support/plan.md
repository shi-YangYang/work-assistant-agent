# Plan：附件即时上传与广泛文本支持

## 对应 Spec

[附件即时上传与广泛文本支持](spec.md)。只提前上传；内容读取保持在发送后。所有目录沿用现有业务归属。

## 涉及模块

- 共享输入规则及附件分类：集中定义禁止后缀和分类优先级，前后端一致；未知类型进入通用文本候选。
- 聊天草稿上传：管理有界上传队列、单文件状态、移除、重试、会话归属和晚到响应；发送逻辑只消费已完成的附件。
- 附件 UI：空心圆 loading、失败提示与单文件操作；文档卡片采用约 48px 高的紧凑原型，长文件名／状态单行省略，保留完整名称查看和触摸操作范围；图片缩略图／试听保留现有布局。
- 后端附件生命周期：未发送附件删除、正式引用保护、物理文件清理与现有 24 小时回收。
- 文本解析及错误呈现：新增通用文本分支，复用现有解析结果和错误通道。
- 沙盒输入：保留原始附件引用和权限，只验证新增文本格式可传入，不扩展运行环境。

## 修改顺序

1. 明确并实现共享禁止规则、已知格式分类及通用文本候选；保留既有媒体和旧 Office 提示。
2. 实现仅删除未发送附件的服务及 API，复用持久删除标记与清理机制；核对消息绑定、工作材料绑定和删除的锁顺序。
3. 集中管理草稿上传状态，接入选择、拖放、粘贴、录音完成和草稿恢复路径；限制同时上传数为 2。
4. 将发送门槛移到草稿状态判定；保留长按语音直发的独立文件路径、幂等提交和不混入原草稿的行为。
5. 接入 loading、重试、移除与失败文案；HEIC 预览复用上传结果，避免两条上传路径。
6. 扩展发送后通用文本读取，打通读取失败直接展示及原文件沙盒输入，核对不增加模型步骤。
7. 完成定向验证与耗时对照，新的独立验收 Agent 根据 Spec 验收。问题明确后再返工，不重跑无关检查。

## 数据流

```text
添加入口 → 共享格式／限额检查 → 草稿文件条目
  → 上传协调器（最多 2 个）→ POST /uploads → Attachment ID
  → 上传成功状态 → 手动发送可用 → POST /messages
  → 绑定附件 → worker 文档解析／现有媒体识别 → Agent
    ├─ 文档工具：文本分段与来源
    └─ 现有沙盒：授权原始附件

移除草稿条目 → 出队／取消请求 → DELETE /uploads/{id}
  → 原子校验无正式引用 → 持久标记删除 → 清理文件
未发送孤儿 → maintenance 现有 24 小时清理
```

- 上传状态以稳定的账号、草稿和文件标识关联；编辑文字不能使上传结果失去归属。取消项使用代次或等价标识拒绝旧响应，不能通过删除组件来假定请求已终止。
- 上传成功收到服务端 ID 后才能标记成功；请求完成但客户端未收到回执的孤儿由过期回收兜底。单文件手动重试不影响其他成功条目。
- 上传等待不设置为整个聊天的任务执行状态，不占用现有 Agent 单会话执行锁；发送进行中继续保护消息快照。
- 保留 `File`／Blob URL 供本地预览和必要重试；成功发送、主动移除、身份释放时按各自所有权清理。
- 通用文本 MIME 使用安全的文档响应策略；禁止列表先于 MIME 分类。PDF／OOXML 继续专用解析，未知后缀只做一次通用文本读取，不自动串联多个解析器。
- 失败状态复用 `Attachment.extraction`，不新增“失败后让模型解释”的请求。上传错误由前端直接显示，读取错误从消息附件状态更新。

## 接口变化

### 现有上传与消息接口

- `POST /api/v1/uploads`：扩展允许的文本候选范围；保留现有返回 DTO、限额与必要格式检查。成功后文档仍为 `unsent`。
- `POST /api/v1/messages`：继续提交 `attachmentIds`，保持幂等行为；复核附件未删除、可用且归属正确，并与删除使用一致并发保护。
- `GET /uploads/{id}/content`、`/extraction` 与消息序列化继续沿用现有权限和结果格式；上传时不触发 `/retry` 文档 Job。

### 新增临时附件删除

- `DELETE /api/v1/uploads/{identifier}`：仅本人未发送、无工作材料及其他正式引用的附件可删除。
- 返回现有 `{ok: true}` 风格；重复删除同一已清理对象不产生副作用。其他人或不可见对象不泄露状态；已正式绑定的附件拒绝删除。
- 先在事务内锁定、复核引用并持久标记，再清理物理文件。清理失败复用 `cleanup_pending` 或等价可恢复语义，maintenance 能重试；对新后端返回的业务错误，前端不能伪报物理文件已删除。
- 新前端继续经唯一请求模块调用接口，不另建 fetch／身份处理通道。上传请求支持取消，不额外发送内容校验请求。

## 测试计划

文档阶段 S0，仅检查 diff、需求一致性和引用。实施阶段涉及上传安全、公共 API 与删除持久化，按 S3 对附件子系统做定向验证；不默认执行全项目测试、全量 build 或真实模型评测。

### 定向行为与边界

| 范围 | 必须验证 |
| --- | --- |
| 文件策略 | 源码、多种未知后缀、无后缀、大小写、复合后缀、伪造 MIME、HTML／SVG 源码、旧 Office 和禁止名单；图片／Office 不因二进制或 ZIP 结构误拒绝 |
| 解析 | UTF-8／BOM UTF-16、非法编码、二进制、空内容、长文本部分读取、损坏／加密文档；语法错误源码照常读取，已知文档失败不走通用兜底 |
| 上传 UI | 单文件和多文件、分批添加、最多 2 个上传、loading 完成消失、失败重试、Enter 不能绕过禁用、输入文字不被锁定 |
| 生命周期 | 排队删除、上传中删除、完成后删除、响应乱序、切换会话／身份、页面卸载、过期后发送、网络失败后重新进入 |
| 服务端安全 | 他人／跨公司删除、已发送／工作引用保护、发送与删除竞争、工作绑定与删除竞争、磁盘清理失败恢复、24 小时孤儿回收 |
| 既有行为 | 无附件发送、HEIC 预览、录音试听、长按只发本次语音、直发失败不重试、不闪入草稿、原始文件送入沙盒 |
| 失败反馈 | 一份失败与多份成功混合、部分可读、附件错误不暴露内部路径、失败不额外调用模型或重复工具 |

- UI 请求使用可控上传延迟、失败和乱序回执；断言实际请求次数和提交内容，不能只验证按钮文案。
- 服务端使用隔离测试文件和数据库；竞争测试控制事务先后，分别验证发送先成功／删除先成功。不能用真实用户附件做删除测试。
- 解析使用真实固定文件；沙盒先用已有协议／输入测试验证授权与原始字节，配置具备时增加一次固定输入的真实 Python 读取。没有启用真实沙盒时明确记录未执行，不以 mock 结果替代。
- 浏览器检查桌面与 320／390px 手机视口的选文件、loading、移除、重试和发送门槛；确认没有横向溢出或控件遮挡。模拟移动视口不等于已验证真实钉钉／系统选择器。

### 耗时与调用次数对照

- 用相同文件内容、文件数、网络条件比较修改前后：记录选择时间、上传开始／结束、发送时间、消息接收时间；将上传耗时与发送后的任务耗时分开报告。
- 旧版基线使用其已支持的 TXT；新版将同一文本分别命名为 TXT、PY、未知后缀和无后缀。使用相同解析进程测量，固定样例各取 5 次中位数并保留范围，不拿不支持格式的旧版失败时间比较。
- 检查成功文件每次草稿仅上传一次、发送不重复上传、读取缓存仍复用；用固定 Agent 替身确认不增加模型调用或工具轮次。
- 若读取时间有稳定回退，定位新路径、重复 IO 或进程开销后处理；不能用真实模型随机波动掩盖应用流程回退。没有真实模型测速时不声明端到端回复已提速。

### 执行范围

- Web：以现有 `tests/web/resources/files.test.ts`、`tests/web/assistant/message-submission.test.ts`、草稿生命周期和 `tests/web/dom/assistant/composer-attachments.test.tsx` 为基础，新增集中上传生命周期的定向用例；通过 `npm run test:web -- <本次相关文件>` 执行。
- 后端：`.venv-server` 下按现有测试环境运行附件格式、上传／删除、文档解析、消息绑定及沙盒输入的相关 pytest 文件。新增删除测试放在 `tests/server/modules/materials/`；避免运行所有业务 Agent 用例。
- TypeScript 契约／跨组件接入完成后运行一次 Web typecheck；源码编辑按项目配置格式化本次文件。其他检查只在对应失败或实现范围变化时追加。
- 独立验收优先检查已有定向结果、相关 diff 与未覆盖风险，不机械重复所有通过检查。测试证据放 `artifacts/`，最终记录到 `acceptance.md`。

## 风险

- 未发送附件数量随提前上传增加：通过有界队列、单文件限额、主动删除和现有过期回收控制，不引入无限后台上传。
- 删除与发送／工作材料绑定竞争：必须共享锁顺序和引用检查；不能只根据前端是否显示判断文件可删。
- 请求取消与服务器实际完成可能不同步：忽略晚到 UI 回写、清理已知临时 ID，未知孤儿由 maintenance 兜底。
- 通用文本后缀广泛：禁止项只是产品策略，不能替代现有解析隔离、文档安全下载和资源限制。
- 上传成功不保证可读：明确区分上传错误与发送后的读取失败，不将后者追溯显示为上传失败。
- 草稿和录音直发共用代码：独立保护直发快照及原草稿，防止新增上传门槛吞掉录音或顺带发送其他内容。

## 迁移策略

- 预计不需要数据库 migration：复用附件归属、消息关联、删除标记、创建时间和现有清理任务。
- 如实现证明确需字段以保证清理可靠性，再更新本计划并补相应 migration 及检查，不把前端临时状态直接落到业务表。
- 先部署兼容旧上传流程的新后端，再更新前端；已有格式和历史附件不批量重解析。解析版本变化按现有缓存版本策略处理，保留旧证据失效保护。
- 回退前端可恢复发送时上传。后端回退必须评估已经新增的文本格式附件；不通过删除新附件完成回退。

## 实施文件与改造目录

沿用现有目录；消息绑定、错误展示和沙盒输入复用已有实现，不额外增加处理步骤。

```text
packages/api-contracts/
└── input-rules.json                         [修改] 共享附件禁止规则
apps/web/src/
├── api/attachments.ts                       [修改] 取消上传与临时附件删除请求
├── app/layout/Shell.tsx                     [修改] 跨页面保持草稿上传协调器
├── utils/attachments.ts                     [修改] 文件分类、禁止提示和宽泛选择
└── features/assistant/
    ├── lib/audio-capture.ts                 [修改] 草稿文件状态类型，保留采集逻辑
    ├── lib/composer-drafts.ts               [修改] 草稿暂停、释放与上传生命周期
    ├── lib/attachment-uploads.ts            [新增] 有界队列、取消、晚到回执和清理协调
    ├── hooks/composer/useAttachmentUploads.ts [新增] 上传协调器与当前草稿接入
    ├── hooks/composer/useMessageSubmission.ts [修改] 仅发送就绪附件，保留直发／幂等
    ├── hooks/composer/useRecording.ts       [修改] 区分草稿录音与长按直发
    └── components/
        ├── conversation/ConversationChat.tsx [修改] 接入上传、移除与预览复用
        ├── composer/MessageComposer.tsx     [修改] 文件选择与发送禁用条件
        └── composer/attachments/
            ├── ComposerAttachments.tsx     [修改] loading、失败、重试与移除
            ├── ComposerAttachments.module.css [修改] 空心圆及稳定附件布局
            ├── ComposerAudioPreview.tsx    [修改] 保留录音试听、显示上传状态
            └── ComposerAudioPreview.module.css [修改] 状态单行省略
apps/server/app/
├── core/input_rules.py                      [修改] 读取共享附件规则
├── modules/attachments/
│   ├── policy.py                            [新增] 后端分类与禁止规则适配
│   ├── lifecycle.py                         [新增] 未发送附件退役与清理服务
│   ├── router.py                            [修改] 扩展上传与临时删除 API
│   └── documents.py                         [修改] 类型与文档读取状态兼容
├── modules/messages/commands.py             [修改] 本人失效附件的重新添加提示
├── modules/work/materials/service.py        [修改] 工作材料绑定与删除使用相同锁顺序
├── modules/operations/mutations/deletion.py [修改] 复用可恢复的附件物理清理
├── integrations/parsing/document_parser.py  [修改] 通用文本读取与明确错误
└── tasks/maintenance/maintenance.py         [修改] 临时删除恢复与既有过期清理
tests/
├── web/resources/files.test.ts              [修改] 格式政策与文件分类
├── web/assistant/attachment-uploads.test.ts  [新增] 上传、取消、重试及竞态
├── web/assistant/message-submission.test.ts [原位回归] 发送快照
├── web/assistant/session-drafts.test.ts      [修改] 身份暂停／恢复和直发录音释放
├── web/dom/assistant/composer-attachments.test.tsx [原位回归] 附件控件
├── web/dom/assistant/attachment-send-errors.test.tsx [新增] 失效提示和未知回执保护
├── web/dom/assistant/voice-recording.test.tsx [修改] 即时上传与长按直发兼容
├── server/modules/materials/
│   ├── test_attachment_experience.py        [原位回归] 上传行为与失败反馈
│   ├── test_attachment_upload_lifecycle.py  [新增] 删除权限、竞争和回收
│   ├── test_document_constraints.py         [原位回归] 文档边界
│   └── test_document_parser.py              [修改] 通用文本与读取失败
├── server/modules/work/test_work_materials.py [修改] 回滚断言限定当前工作
└── server/sandbox/test_input_names.py        [原位回归] 原始文件名和输入兼容
specs/
├── README.md                                [修改] 规格索引
└── spec-070-attachment-upload-and-text-support/
    ├── spec.md                              [新增] 需求与验收标准
    ├── plan.md                              [新增] 实施、目录与定向验证
    ├── implementation.md                    [新增] 实施结果与检查限制
    ├── rework.md                            [新增] 初次验收的三项返工要求
    ├── implementation-rework.md             [新增] 返工结果和定向检查
    └── acceptance.md                        [新增] 独立验收结论
```

固定输入、浏览器截图和耗时对照证据保存在 `artifacts/spec070/`（本地验收产物，不纳入业务代码）。
