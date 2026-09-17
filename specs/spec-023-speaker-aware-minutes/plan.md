# 实施计划

## 分工与数据流

- 核心：Python 纪要快照、等待说话人、持久化版本、结构校验、搜索与导出，以及相关核心测试。
- 桌面：共享类型、受限 IPC、文字双视图与复制、纪要模式和新版分析展示，以及相关桌面测试。
- 两者按以下契约并行，文件分别限于 Python 核心／tests/core 与桌面 TypeScript／tests/desktop。协调 Agent 完成联调、文档与真实服务验证，随后由新的独立 Agent 验收。

## 契约

- `inputMode: 'speakers' | 'text'`，省略时默认 `speakers`。`summary.generate` 接收 `meetingId` 和可选 `inputMode`；自动生成默认含发言人。
- 结果增加 `inputMode`、`speakerIncomplete`；历史结果缺省按 `text` 解读。任务可增加 `waiting_speakers` 状态；等待不占用网络 worker，不影响模型管理请求。等待有界，超时／失败以现有资料生成一次，后续识别完成不额外自动生成。
- 快照锁定有序片段、发布版本、模式和使用到的说话人信息。含发言人片段增加 `speaker: { id, name, identitySource: 'manual' | 'voiceprint' | 'anonymous', assignmentSource: 'manual' | 'automatic' } | null`；仅文字完全不带此字段。不能发送员工 ID、模板或未发言成员。
- 当前任务及结果按快照比较维护过期状态；身份或归属变化仅使含发言人结果过期，转写版本变化使两种模式均过期。保留失败重试之前的成功结果。SQLite 增量迁移先备份；旧版本内容不强制重写。
- 新纪要 `version: 2`：`title`、`abstract`、`overviewSources: string[]`；`topics`、`agreements`、`decisions`、`disagreements`、`risks`、`openQuestions`、`suggestions` 为 `{ text, sources: string[] }[]`；`speakerSummaries` 为 `{ speakerId, name, points: Cited[], commitments: Cited[] }[]`；`actions` 为 `{ task, owner: string|null, deadline: string|null, status: string|null, dependencies: string|null, blocker: string|null, sources: string[] }[]`。
- 引用仅允许本次输入真实片段，姓名／说话人 ID 必须与快照对应，逐人条目的引用须属于该发言人；仅文字模式 `speakerSummaries` 必须为空。结构校验不能代替语义验收。保留 version 1 阅读／导出／搜索支持。
- 自动声纹身份在模型输入、保存分析、搜索与导出中附带待确认说明；原文与原始快照不改名，同名人员以发言时间辅助区分，不显示内部编号。仅自动身份不能确认负责人，引用中的人工确认与原话明确分工优先。
- `ExportOptions` 增加可选 `speakers: boolean`，缺省 true 保持旧行为；Python `library.start(kind='export')` 接收相同可选字段。新增桌面 `copyTranscript(id, { speakers, timestamps })`，main 通过现有完整快照导出链路复制，不只复制已加载分页；原 `copyMinutes` 保持兼容。
- 搜索定位沿用 `字段:索引`，逐人摘要使用 `speakerSummaries:索引`，概览使用 `abstract`；界面对应定位属性。原文定位／时间回放仍用稳定片段 ID。

## 页面

文字记录增加紧凑视图切换与复制，发言人视图保留已有纠正入口。纪要生成区独立选择输入模式，显示结果实际使用的模式及必要的待更新／信息不完整状态。六类分析区有内容才显示，建议明确标为 AI 建议；不增加大面积说明或重复标题。

## 验证与交付

存储／任务协调属 S3，执行受影响的核心、资料库、说话人边界测试及桌面类型／定向 IPC 检查；不默认全仓测试或发行包。固定样例覆盖等待降级及去重、改名／改归属／生成期间变更、仅文字隔离、新旧内容搜索导出、未知或混合身份、负责人不等于发言者。

在用户日常桌面环境检查双视图、定位、布局和导出，使用已授权服务做真实模型样例，检查明确承诺、替他人分工、提议与决定、未确认身份的语义。测试不改用户既有会议，临时样例用完清理。真实服务不可用或原生操作受阻时如实报告，不以 mock 代替。
