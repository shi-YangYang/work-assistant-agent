# 实施计划

对应 [需求](spec.md) 与 [业务流程矩阵](matrix.md)。后端先固定 DTO、API、版本和材料绑定合同，再按不重叠文件分工：一名实施 Agent 负责后端与 Agent 调用，另一名负责 Web 与共享 TypeScript 合同，第三名负责真实流程评测。主 Agent 统一调度集成检查，完成后由新的独立 Agent 验收。

## 数据与模块职责

| 模块 | 改造 |
| --- | --- |
| WorkItem／WorkRevision | 新增正文 JSON、schemaVersion、纯文本派生值；保留兼容进展字段，修订标记变更种类并保存快照 |
| WorkUpdate／WorkUpdateRevision | 新增进展条目与不可变修订，关联工作、操作者、来源、材料及对应工作版本；支持更正／删除 |
| WorkMaterial | 记录工作范围内的文件绑定、源附件／成果版本及保留关系；文件处理继续复用 Attachment 与媒体目录 |
| work 服务 | 正文、属性、进展与材料写入在一个授权事务边界完成；更新当前投影、修订及真实差异 |
| operations | 扩充操作合同，统一确认、幂等回执与恢复；API 和 Agent 调用同一 work 命令 |
| attachments／executions | 支持工作材料授权、直接解析、图片上下文、沙盒输入及持久成果文件读取 |
| reports／team | 生成与查询使用期间进展快照和可信属性；历史报告来源保持固定 |
| Web | 轻量创建、正文编辑、材料预览、进展输入与动态；统一请求缓存按工作／账号失效 |

正文选用 Tiptap 的 React 基础扩展，按需启用段落、标题、基础标记、列表、清单及自有材料节点，不接入其云服务、协同编辑或 AI 扩展。它提供无样式编辑内核与自定义节点，适合复用现有视觉：[编辑器说明](https://tiptap.dev/docs/editor/getting-started/overview)、[节点扩展](https://tiptap.dev/docs/editor/extensions/custom-extensions/create-new/node)。依赖加入 Web workspace 并锁定兼容版本。

正文顶层内容块使用稳定 ID。服务端接受受限编辑操作，支持追加块、替换指定块、删除指定块和显式全文替换；全文替换需保留或明确处理现有材料引用。Agent 不拼任意 HTML，不用脆弱的整篇字符串替换定位“第二点”。

### 材料持久化

- 上传仍使用 `/uploads`，工作保存成功后才建立持久绑定并调度必要解析；解析任务去掉“必须先有 message_id”的假设。
- 聊天附件与生成文件通过带来源版本的输入引用保存。已在统一媒体库中的对象可复用并保留引用；沙盒产物先复制到媒体库，再提交关联，不让成功回执指向临时文件。
- 当前绑定、正文／进展历史及报告快照均进入引用检查；存储清理必须识别这些保留者，不能因源聊天删除误删文件。
- 材料下载、预览、解析、Agent 读取、沙盒挂载采用同一工作范围授权；源材料来源受限时继承原限制，不借保存扩大权限。
- 材料解析失败不回滚已保存的文字；单个文件失败明确反馈，不把部分成功包装成全部完成。

## 接口与 Agent 合同

具体 DTO 统一放在 `api-contracts`；以下路径为已实现的资源边界。

| 接口 | 行为 |
| --- | --- |
| `POST /work-items` | 标题必填；正文、属性、已上传材料可选，携带幂等键 |
| `GET /work-items` | 返回有界概览，避免列表附带完整正文和全部历史 |
| `GET /work-items/{id}` | 返回当前／指定历史正文与属性，以及进展、材料的读取入口 |
| `PATCH /work-items/{id}` | 按 expectedRevision 修改正文或属性，缺省字段保持不变 |
| `GET/POST /work-items/{id}/updates` | 分页读取／追加进展，写入携带幂等键与版本 |
| `PATCH/DELETE /work-items/{id}/updates/{updateId}` | 更正／删除指定条目，校验条目版本和工作归属 |
| `GET/POST /work-items/{id}/materials` | 分页读取／绑定明确选中的上传或成果文件 |
| `DELETE /work-items/{id}/materials/{materialId}` | 移除当前关联，校验版本与引用位置，保留仍有效的历史引用 |

- 单次保存文字及材料采用原子业务命令，避免出现“正文保存成功但引用未绑定”；上述独立接口服务于明确独立的材料操作。
- 旧 `/progress` 与进展草稿确认在兼容层转换为同一命令：保留旧字段语义与返回结构，新增正文／材料不得被旧 schema 默认值擦掉。
- `find_work_items` 保留概览与分页；`get_work_item` 返回最新版本和可分页正文、材料／进展摘要，不输出无界历史。
- 增加工作进展与材料列表读取工具；文档读取、图片理解、语音文本与沙盒输入扩充工作材料范围，尽量复用已有读取工具。
- `execute_business_action` 扩展 typed changes 与必要 action，覆盖正文编辑、进展增改删、材料增删；`propose_progress` 转为同一进展命令的建议入口。
- 扩充工作变更计划，明确 preserve／正文块编辑／追加动态／属性修改／材料绑定；不再强制每次工具操作生成六字段表单。
- 成功回执返回 workId、revision、updateId／materialIds、实际变化和可打开的详情入口。后续修改依据真实 ID，未成功操作不能输出“已保存”。
- 旧持久任务保留已有回执，未完成操作先转换合同并重新校验，不重放已经完成的写入。

## 数据流

```text
手动编辑／Agent typed action
  → 同一 work 命令：身份、执行规则、源文件、版本、幂等校验
  → 事务保存正文／动态／材料 + 修订 + 操作回执
  → Web 定向失效并刷新对应工作

工作引用
  → 最新属性与有界正文／目录
  → 按需读取材料、进展或正文后续分页
  → 模型交付；明确保存意图才调用业务写入

报告生成
  → 所选期间有效进展 + 属性事实 + 用户要求的计划
  → 固定来源快照 → 既有草稿／提交流程
```

## 改造目录

`[改]` 为原位修改，`[增]` 为新增，`[移]` 为提取公共能力。目录级标注表示该职责下的相关文件；不迁移现有应用或建设平行业务模块。

```text
apps/web/
├── package.json                                      [改] 基础富文本依赖
├── src/api/attachments.ts                            [增] 共用附件请求
├── src/components/forms/AutoTextarea.tsx             [改] 隐藏弹层中的高度测量
├── src/components/media/                             [移] Documents、ImageGallery、PdfPreview 及私有 CSS
├── src/utils/{attachments,attachment-limits}.ts       [移] 共用文件检查与元信息
└── src/features/
    ├── work/
    │   ├── api/requests.ts                           [改] 正文、动态、材料 API
    │   ├── components/
    │   │   ├── editor/                               [改] CreateWork、WorkEditor
    │   │   ├── detail/                               [改] WorkDetail、WorkHistory 与私有 CSS
    │   │   ├── overview/                             [改] 概览与搜索展示
    │   │   ├── content/                              [增] 正文编辑／展示、受限节点、私有 CSS
    │   │   ├── updates/                              [增] 进展输入／动态／更正、私有 CSS
    │   │   └── materials/                            [增] 材料添加／预览、私有 CSS
    │   ├── hooks/useWorkUpload.ts                    [增] 材料上传、待保存附件与失败重试
    │   └── utils/                                    [改/增] 历史差异、文档转换与约束
    └── assistant/
        ├── api/requests.ts                           [改] 复用共用上传请求
        ├── components/attachments/                   [移] 通用媒体展示提取到 components/media
        ├── components/{composer,conversation,messages}/ [改] 共用媒体引用
        ├── components/interactions/                  [改] 新操作确认与真实回执
        └── utils/work-action-preview.ts              [增] 正文与进展变更摘要
apps/server/app/
├── migrations/versions/0025_work_records.py           [增] 正文、动态、材料与旧数据迁移
├── modules/
│   ├── work/
│   │   ├── models.py                                 [改] 正文快照、动态与材料模型
│   │   ├── router.py                                 [改] 新 API 与旧入口转换
│   │   ├── schemas.py                                [改] 新旧输入合同
│   │   ├── record_schemas.py                         [增] 正文、动态与材料请求合同
│   │   ├── record_commands.py                        [增] 统一内容写入、版本与材料事务
│   │   ├── agent_commands.py                         [增] Agent 操作转换与预览
│   │   ├── service.py                                [改] 版本事务与兼容投影
│   │   ├── queries.py                                [改] 搜索和分页
│   │   ├── serializers.py                            [改] 有界 DTO 与历史快照
│   │   ├── projection.py                             [改] 模型读取投影
│   │   ├── content/                                  [增] 文档校验、块编辑、纯文本派生
│   │   ├── updates/                                  [增] 进展增改删与期间快照
│   │   └── materials/                                [增] 材料绑定、读取和保留关系
│   ├── attachments/                                  [改] 工作文件可见性与解析入口
│   ├── members/commands.py                           [改] 删除账号时回收工作材料
│   ├── conversations/task/{task_schemas,task_state}.py [改] 进展确认结构、中断任务来源与回执保留
│   ├── executions/                                   [改] 工作材料输入与生成文件保留
│   ├── operations/                                   [改] action 合同、授权、回执与来源发布
│   ├── reports/sources.py                            [改] 期间进展与固定事实
│   └── team/                                         [改] 工作详情、来源与期间查询
├── agent/
│   ├── tools/{work,actions,documents,registry}.py     [改] 工具 schema、读取和统一写入
│   ├── tools/work_records.py                        [增] 分页进展、材料目录及真实内容读取
│   ├── actions/{work_change_plan,intent,operations,task_items}.py [改] 内容变更计划、报告字段授权与原子步骤身份
│   ├── context/task_context.py                       [改] 明确续接时读取已取消任务上下文
│   ├── prompts/policies.py                           [改] 记录、讨论、材料和汇报边界
│   ├── harness.py                                    [改] 无效收尾的有界协议恢复
│   ├── completion/delivery.py                        [改] 区分收尾结构与引用错误
│   ├── completion/{reply_review,response_repair}.py  [改] 核对进展／材料的新合同与准确操作说明
│   ├── completion/work_receipts.py                   [增] 已保存进展及材料副本的可信回执证据
│   ├── runtime/{middleware,model}.py                  [改] 冲突时强制重读、收尾恢复工具范围
│   ├── runtime/progress/phases.py                    [改] 收尾纠错提示
│   ├── runtime/tool_nodes.py                         [改] 工作材料读取来源
│   ├── runtime/progress/tools.py                     [改] 操作阶段名称
│   └── reports.py                                    [改] 新报告输入合同
├── security/versions.py                            [改] 受控冲突重读仍保持来源版本检查
└── tasks/
    ├── context.py                                    [改] 待重新读取的工作版本状态
    ├── nodes/node_execution.py                       [改] 持久恢复标记
    ├── lease.py                                      [改] 工作材料解析任务识别
    └── maintenance/                                  [改] 删除、失效和文件清理
packages/api-contracts/src/index.ts                   [改] 工作、动态、材料与操作 DTO
package-lock.json                                    [改] 编辑器依赖锁
tests/
├── web/dom/work-records.test.tsx                      [增] 正文、动态与材料交互
├── server/test_work_records.py                       [增] 新业务命令和版本
├── web/dom/{business-action-card,work-history,draft-submission,assistant-persona}.test.tsx [改] 相关交互回归
├── web/dom/auto-textarea.test.tsx                     [增] 隐藏到可见时高度恢复
├── server/test_response_delivery.py                  [改] 无效收尾引用有界恢复
├── server/test_execution_permissions.py              [改] typed 删除的执行规则
├── server/test_work_conflict_refresh.py               [增] 版本冲突重读与撤权阻断
├── server/test_conversation_task_state.py              [改] 明确续接、原子步骤身份与旧任务隔离
├── server/test_report_work_context.py                 [增] 计划与事实分离、报告改写及固定来源
├── server/test_work_record_tool_access.py              [增] 工作不可用的语义反馈与权限保持
├── server/test_operation_attempt_recovery.py          [改] 成功回执重放、取消确认后明确续接
├── server/test_work_reply_evidence.py                 [增] 回执事实映射与收尾核对
├── server/test_work_change_plan.py                    [改] 十字段分类、原子范围与跨模式合同
├── server/test_work_record_actions.py                 [增] Agent 写入、权限、期间报告及恢复
├── server/{conftest,test_freeform_actions,test_recovery,test_business_actions,test_password_schema_migration}.py [改] 隔离配置与兼容断言
├── server/test_work_materials.py                     [增] 材料读取与生命周期
├── server/work_record_eval_cases.py                   [增] 真实模型多轮场景
├── server/work_record_eval_{runtime,materials,assertions}.py [增] 隔离执行、真实材料与持久结果断言
└── e2e/web/business/work.spec.ts                      [改] Web 完整记录流程与截图
scripts/benchmarks/agent-evaluation.py                 [改] work-records 定向真实评测套件
docs/{architecture,setup}.md                          [改] 实施后的内容模型与使用说明
```

## 实施顺序

1. 确定文档节点、进展、材料和动作 DTO；先写新旧数据、权限与业务不变量的定向用例。
2. 增量迁移与统一 work 命令，接通材料保存／解析／保留，验证 API 和来源生命周期。
3. 重做工作创建、详情正文和进展交互，复用已有请求、错误、弹层和媒体能力；确需共享的纯展示组件移入公共层，不跨 feature 反向依赖。
4. 接通 Agent 工具、变更计划、授权、上下文、确认、回执与恢复；适配报告、团队和历史来源。
5. 执行矩阵中的 API、浏览器和真实模型流程，修复本次相关问题；更新使用与架构说明。
6. 独立 Agent 根据需求、实际 diff 和证据验收。未执行、失败与通过分别记录，不用模型自评代替结果检查。

## 迁移与风险

- 新字段和表增量加入；正文 schema 带版本。旧摘要原文导入正文，旧修订转为可读历史，不改已有 ID、日期及报告 sourceIds。
- 避免生成一批当前时间的“导入进展”，旧期间统计保持原口径；新写入只产生新的实际版本。
- 全部工作保存入口审计一次，尤其是 `Progress.model_validate(...).model_dump()`，不能过滤掉新内容。
- 部署同时更新 API／worker；迁移前备份数据库与媒体。只读兼容允许旧数据打开，但旧版本应用可能丢失新字段，出现新写入后不得只回退应用镜像；需兼容修复或恢复成对备份。
- 历史报告来源、新动态更正和附件删除必须有固定快照规则；验证权限撤销、源会话删除、报告引用保留和清理任务。
- 正文分页、动态分页和材料目录设服务端上限；不加载所有修订，不增加周期轮询。

## 验证计划

业务实施为 S3：新增持久化模型、文件授权和跨模块写入合同。先定向运行新增与受影响用例，再完成一次 Web 与公司后端回归；不跑无关 Electron／声纹测试。

- `npm run test:web`、`npm run typecheck:web`、`npm run build:web`：新编辑器、组件、共享合同及打包。
- `npm run test:server`：工作、操作权限、消息／成果／文件、报告与团队相关集成回归；隔离数据库及媒体目录。
- `npx playwright test --config apps/web/playwright.config.ts tests/e2e/web/business/work.spec.ts --project chromium`：定向完整 UI 流程，涵盖手机宽度；按现有测试环境说明启动隔离服务。
- 使用项目格式化器整理变更文件，并对变更源码做定向 ESLint；不格式化整个仓库。
- 在现有真实评测器加入 `work-records` 套件后，运行 `.venv-server/bin/python scripts/benchmarks/agent-evaluation.py --suite work-records --source-user <已配置模型的测试来源账号> --output artifacts/spec047/agent/results.jsonl`。评测写入隔离公司和数据库，仅从来源账号读取模型配置。
- 真实模型至少完成矩阵指定的 24 个多轮场景，读取保存的业务记录、版本、工具回执与文件作为判定依据；正常场景禁止事先写入预期结果。
- 权限、版本、幂等、源删除及文件泄露等边界使用确定性断言；真实模型部分允许受控故障注入，但注明注入点，不能冒充真实服务故障。
- 所有矩阵行必须有结果。失败分类为产品缺陷、测试错误、环境阻塞或模型能力；保存原始失败，不通过反复重跑筛出一次成功。
- 记录模型及配置、请求、工具轨迹、持久结果和浏览器截图到 `artifacts/spec047/`，脱敏且不提交临时数据。真实模型不可用时标记未执行，不能宣称 Agent 流程验收通过。

普通后端测试与真实模型评测串行运行，避免隔离夹具的密钥检查相互影响。
