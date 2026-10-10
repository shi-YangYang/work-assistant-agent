# 失败项修复

## 范围

继续处理上一轮 FAIL、BLOCKED 和已记录质量问题，原始 60 例成绩保持不变。S03、E02 等已有有效修复不重复测试，除非新修改影响其路径。

| 问题 | 处理方向 | 验证 |
| --- | --- | --- |
| A05／Q03／X-F04 | 检查材料改写、代码示例和事实条件是否被通用提示或上下文流程破坏；优先可验证证据，不按原句特判 | 原失败和预先冻结的变体，分别记模型正确性与工程断言 |
| X-LONG／C04 | 检查明确长度／页数约束在生成与修改中是否保留；工具返回可测结果，不能靠自称完成 | 实际正文计数、文档渲染／页数、内容不被删减 |
| R02／R07 | 检查多余查询、收尾核对与节点期限分配；保留有界执行和安全核对 | 受控超时／恢复及原真实流程，不简单放大超时 |
| S02／S05 | 公开网页无法直接读取时提供可用的链接／来源搜索恢复能力，准确区分读到和未读到 | 受控 DNS／403／域名过滤与一次真实检索 |
| H02／H09／H11 | 避免把标题标识当事实、已回答却等待补话、混淆对象 ID | 与上述通用修改相关的变体检查 |
| 其他覆盖缺口 | DOCX 中文渲染尽量在已具备字体的隔离镜像完成；补明确可执行的细分断言 | 不用环境模拟冒充真实钉钉或物理设备 |

## 边界

- 不修改首轮输入、预期或成绩；复测独立保存在 `artifacts/spec054/20261008-repair/`。
- 不增加每次答复都执行的多轮自评，不取消期限、权限、隔离或重复执行保护。
- 不为某个题目、域名或错误文本写专用放行逻辑；外部访问受限如实保留。
- 模型修复效果通过原例和事前冻结变体判断，一次答对不代表永不出错。
- 新建带所有权标记的临时环境，只读读取模型配置，结束后清理；日常数据和服务保持不变。
- 按 S2／S3 做相关模块和真实失败路径检查，不再次运行整套已通过测试。

## 涉及目录

```text
apps/server/app/
├── agent/completion/
│   ├── answer_length.py                        [新增] 引用原请求的可选本地字数校验
│   └── {delivery,response_repair,quantitative_review}.py
│                                                [修改] 有界修正、减少无关数字核对
├── agent/runtime/middleware.py                  [修改] 当前任务与完成条件
├── agent/prompts/evidence.py                    [修改] 保留未知事实与条件
├── agent/tools/{completion,actions,documents,web}.py
│                                                [修改] 完成契约、授权目录、联网来源
├── agent/tools/sandbox/documents.py             [修改] 页数约束转发
├── integrations/web_research.py                 [修改] 真实链接和搜索域名过滤
└── modules/executions/builtin/schemas.py         [修改] 可选 max_pages 契约
apps/sandbox/runner/noria_tools/
├── contracts.py                                [修改] 沙盒页数边界
└── documents/{blocks,pdf,word}.py                [修改] 可读紧凑排版与实际计页
tests/
├── server/test_{answer_length,document_constraints,dynamic_branch_edges}.py
│                                                [新增] 对应约束及覆盖缺口
├── server/test_{documents,quantitative_review,web_research,web_research_recovery}.py
│                                                [修改] 定向回归
└── sandbox/toolkit/test_documents.py            [修改] gVisor 中实际生成／失败边界
specs/spec-054-web-comprehensive-testing/
├── rework.md                                   [新增] 追加修复范围
├── implementation.md                          [更新] 原始结果与修复结果分开
├── acceptance.md                              [保留] 首轮独立验收
└── acceptance-repair.md                        [新增] 修复独立验收
artifacts/spec054/20261008-repair/               [新增，不入 Git] 冻结、复测与清理证据
```

最终实际文件和验证结果在实施报告追加，不覆盖先前结论。

## 来源交付与活跃流追加修复

- 已读取的网页来源由工具结果随本条消息持久保存，最终答复下可展开查看；搜索摘要、仅发现的链接、失败页面及前一条消息的来源不混入。列表表示读取记录，不替模型证明所有结论。旧消息不回填。
- 流式模型节点区分 60 秒无有效生成进展与既有总期限；正文、工具参数或非空推理字段可报告进展，心跳不续期。隐藏推理不公开、不持久化。保留 420 秒节点、450 秒处理期限、取消、重试、租约与 2 MiB 响应限制。
- 用量列表依据同 job/fence 的有效运行租约显示长流请求，避免两分钟后误标未知；失联与终态的未知用量规则保留。
- 原 Q03／X-F04／V03 另做简短直连诊断，区分模型表述和系统截断；不是同时同历史的严格 A/B，不把诊断响应成功当完整任务通过。
- 复测预冻 7 个任务、14 轮，包含原 5 个未通过任务和来源切换／失败边界。观察窗口为 480 秒，仅让测试驱动等待现有产品期限结束，不扩大产品执行期限。首轮证据保存在 `artifacts/spec054/20261008-followup/`，既有成绩不变。

```text
apps/server/app/
├── agent/runtime/model.py                       [修改] 生成进展、空闲与总期限
├── agent/tools/web.py                           [修改] 读取记录不被发现链接挤掉
├── integrations/models/{chat,transport}.py       [修改] 进展信号与有界传输
├── modules/messages/
│   ├── web_sources.py                          [新增] 实际已读来源提取与去重
│   └── serializers.py                         [修改] 消息 webSources 契约
├── modules/model_services/usage/usage.py         [修改] 活跃长流的用量状态
└── tasks/
    ├── nodes/node_execution.py                 [修改] 输入 scope 改变时清除旧来源
    └── processing/handlers.py                  [修改] 来源随最终消息提交
packages/api-contracts/src/index.ts              [修改] 已读网页来源 DTO
apps/web/src/features/assistant/components/messages/reply/
├── AssistantReply.tsx                          [修改] 最终答复展示来源
└── WebSources{.tsx,.module.css}                 [新增] 紧凑、可展开来源列表
tests/
├── server/test_{model_stream_deadlines,web_source_delivery}.py
│                                                [新增] 期限、来源持久化与隔离边界
├── server/test_search_metrics_feedback.py       [修改] 活跃与失联用量
└── web/dom/assistant-web-sources.test.tsx         [新增] 来源渲染、失败与流式状态
specs/spec-054-web-comprehensive-testing/
├── {rework,implementation,plan}.md              [更新] 范围与独立结果
└── acceptance-followup.md                       [新增] 本次独立验收
artifacts/spec054/20261008-followup/              [新增，不入 Git] 诊断、冻结、原始复测与清理
```

## 回答与实际证据的一致性

- S02 与 V03 的错误出现在最终正文，原文和运行输出已到达模型，但未进入核对。服务端根据本轮真实成功读取／执行记录选择证据一致性范围，不依赖模型自报是否需要验真。
- 核对复用现有一次 review 与一次语义修正预算，只处理正文与已有观察的具体矛盾。引用逐字正文、实际证据 ID 和冲突原因；不因缺资料、合理推断或文风删除回答，不扩大业务授权或要求用户重复补话。
- 工具输出绑定实际调用参数、当前 job 和执行状态，压缩时保留归属。网页原文、代码和 stdout 均视为资料，不是指令。
- 普通知识不强制搜索、运行或增加独立审稿。收紧概念比较中的条件表达，避免由单个属性推导额外能力；不增加题目、语言 API 或日期的关键词特判。
- 纯新增的一致性检查因容量或服务不可用时保留普通答复，内部标记未核验。既有业务／显式核验／数值规则，以及已经确认矛盾后的修正失败，不降级为直接通过。
- 冻结 3 个原失败任务及 3 个新变体，共 11 轮；另外用两份原错误正文和真实回执检验检查器，不能只因重新生成碰巧答对便宣称修复。失败样本及成绩不覆盖，不重复未受影响的全量检查。

```text
apps/server/app/agent/
├── harness.py                                  [修改] 本轮证据与真实调用参数绑定
├── context/compaction.py                       [修改] 压缩保留证据归属
├── completion/
│   ├── evidence_consistency.py                 [新增] 成功证据范围与匹配
│   ├── {delivery,reply_review,fact_review}.py   [修改] 有条件的一致性检查
│   └── response_repair.py                      [修改] 按结构化问题修正正文
├── prompts/evidence.py                         [修改] 条件与推导规则
└── tools/completion.py                         [修改] 显式验真与内部一致性的区别
tests/server/                                  [修改／新增] 对应模块的最小回归
specs/spec-054-web-comprehensive-testing/
├── {rework,plan,implementation}.md              [更新] 范围、文件与实际结果
└── acceptance-grounding.md                     [新增] 新的独立验收
artifacts/spec054/20261008-grounding/            [新增，不入 Git] 冻结、回放、首次复测和清理
```

### 结果简写的误判返工

真实 V03 中，核对器以带标签多行日志与答案简写不逐字相同为由判错；两者实际值和分支一致。这个误判触发多余修正，最终耗尽既有总时限。

- 允许忠实提取、重新排版和保持关键行为的最小示例；核对事实一致性，不要求代码或输出整串相等。
- 真正的值、顺序、异常、条件、版本或分支冲突仍须报告。修正判据时递增核对版本，避免复用旧判定。
- 三份固定真实核对回放覆盖简写正例、日期冲突和输出冲突；保留首轮证据。另外对原 V03 消息执行一次正常重试，验证恢复，不重新跑已通过任务或调高时限。
- 本轮只修改 `agent/completion/evidence_consistency.py`、`reply_review.py` 及对应最小测试；独立结果另记 `acceptance-grounding-rework.md`，不覆盖首次 FAIL。

## 在线收尾简化

- 替代上面的自动证据核对方案：聊天、资料读取、计算及业务答复不再默认调用额外模型审稿；用户要求核验时由主 Agent 执行原任务。
- `completion/delivery.py` 仅检查结构、当前回执、显式长度和未完成标记；`response_repair.py` 不消费历史语义审稿结果。缺失回执或无效结构仍有有界修正，权限、版本和幂等流程不变。
- `reply_review.py` 保留为显式评测 helper，不参与在线交付。不将移除审稿解释为所有回答都正确。
- 真实验证为五类任务六轮，累计395.93秒、19次模型请求，额外答案审稿0次。三类内容通过；列表／元组遗漏前提，asyncio主结论正确但附带措辞不严谨，保留为质量样本。
- 334项唯一受控用例通过。完整请求、回答、耗时、失败与修正日志见 `artifacts/spec054/20261008-direct-answer/report.md`；不覆盖此前验收结果，也不宣称整个Spec全部通过。
- 列表／元组条件遗漏、asyncio附带表述和历史新闻日期混淆保留为模型回答质量样本，接受现有限制并停止专项修补，不再作为本轮工程修复阻塞，也不改记为测试通过。外部依赖的未验证项仍保留原结果。
