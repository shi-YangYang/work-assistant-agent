# Specs

| Spec | 范围 | 状态 | 验收 |
| --- | --- | --- | --- |
| [001](spec-001-product-and-technical-foundation/spec.md) | 产品、技术与桌面骨架 | DONE | [PASS](spec-001-product-and-technical-foundation/acceptance.md) |
| [002](spec-002-meeting-recording-and-storage/spec.md) | 麦克风录音、保存与回放 | DONE | [PASS](spec-002-meeting-recording-and-storage/acceptance.md) |
| [003](spec-003-local-transcription/spec.md) | 模型准备、持续转写与恢复 | DONE | [PASS](spec-003-local-transcription/acceptance.md) |
| [004](spec-004-meeting-minutes/spec.md) | API 管理、会后纪要与重试 | ACCEPTANCE | [工程缺陷已关闭，待外部验证](spec-004-meeting-minutes/acceptance.md) |
| [005](spec-005-desktop-distribution-and-controls/spec.md) | 内置运行时打包、设置折叠、暂停录音与播放器 | ACCEPTANCE | [许可缺陷已关闭，待平台／交互验证](spec-005-desktop-distribution-and-controls/acceptance.md) |
| [006](spec-006-interface-and-navigation/spec.md) | 配色层级、页面导航与会议交互重设计 | ACCEPTANCE | [工程 PASS，平台／交互范围见报告](spec-006-interface-and-navigation/acceptance.md) |
| [007](spec-007-meeting-library/spec.md) | 会议搜索与筛选、重命名、复制导出及删除 | ACCEPTANCE | [工程 PASS，日期控件界面复验待解锁](spec-007-meeting-library/acceptance.md) |
| [008](spec-008-meeting-followup/spec.md) | 员工工作助手、进展、日报／周报与老板看板；Web 延续桌面设计 | ACCEPTANCE | [工程 PASS，待真实服务／设备与部署验证](spec-008-meeting-followup/acceptance.md) |
| [009](spec-009-company-model-services/spec.md) | 公司模型服务管理、用途分配与真实业务联调 | ACCEPTANCE | [工程及真实文字／周报通过，图文／ASR 待验证](spec-009-company-model-services/acceptance.md) |
| [010](spec-010-web-layout-and-responsive/spec.md) | Web 全页面排版、控件尺寸与响应式维护 | DONE | [PASS：Web 定向检查与逐页视口对照](spec-010-web-layout-and-responsive/acceptance.md) |
| [011](spec-011-web-function-management/spec.md) | 多级面包屑、工作／报告管理、多会话、角色入口与汇报控件 | DONE | [PASS：管理与会话检查，实测边界见记录](spec-011-web-function-management/acceptance.md) |
| [012](spec-012-assistant-documents/spec.md) | 工作助手文件发送、解析、来源引用与私有存储 | PASS | [验收](spec-012-assistant-documents/acceptance.md)；七格式真实解析，模型使用固定响应 |
| [013](spec-013-local-model-library/spec.md) | Electron 六款转写模型、三语言模式、旧会议重转写；展示错误率与内存 | DONE | [PASS；base 中文实测异常如实保留](spec-013-local-model-library/acceptance.md) |
| [014](spec-014-admin-business-assistant/spec.md) | 管理员团队问答、业务来源与本人督办；服务端授权及历史失效 | DONE | [PASS；真实同名及督办确认已补齐，保留接口 500 与恢复记录](spec-014-admin-business-assistant/acceptance.md) |
| [015](spec-015-monorepo-structure/spec.md) | 多端仓库、npm workspaces、构建路径迁移与无用文件清理 | DONE | [PASS](spec-015-monorepo-structure/acceptance.md)；Windows／远端 CI 未运行 |
| [016](spec-016-web-search-metrics-and-feedback/spec.md) | Web 工作分页与搜索、看板统计口径、聊天反馈与模型用量 | DONE | [PASS](spec-016-web-search-metrics-and-feedback/acceptance.md)；固定模型与本地页面验证 |
| [017](spec-017-report-reliability-and-reminders/spec.md) | 多人任务处理、报告可靠性、汇报待办与提醒 | DONE | [PASS](spec-017-report-reliability-and-reminders/acceptance.md)；固定响应与电脑／手机 Web 验证 |
| [018](spec-018-web-pilot-experience/spec.md) | 网络异常、首次使用、问题反馈与定位、手机实际操作 | ACCEPTANCE | [软件与本地验证 PASS](spec-018-web-pilot-experience/acceptance.md)；实体手机与 HTTPS 待实测 |
| [019](spec-019-assistant-attachments/spec.md) | 粘贴／拖拽、语音混发、MP3／HEIC／XLSX、附件预览与图片质量 | DONE | [工程 PASS](spec-019-assistant-attachments/acceptance.md)；音频来源误判已修复，真实混合附件定向复测通过，真机未测 |
| [020](spec-020-dingtalk-login/spec.md) | Web 钉钉登录、管理员配置与员工自动开户 | ACCEPTANCE | [软件验证 PASS](spec-020-dingtalk-login/acceptance.md)；真实授权与公网部署待外部条件 |
| [021](spec-021-assistant-business-actions/spec.md) | 工作助手执行工作／报告操作、汇报待办与统一业务入口 | ACCEPTANCE | [PASS](spec-021-assistant-business-actions/acceptance.md)，含真实模型联调 |
| [022](spec-022-company-voiceprints/spec.md) | 桌面公司登录与游客模式、员工声纹管理同步及本地姓名识别 | ACCEPTANCE | [软件与公开语音实测 PASS](spec-022-company-voiceprints/acceptance.md)；原生桌面交互待解锁，Windows 未实测 |

录音／ASR 实录结果见 [Spec 003 验证记录](spec-003-local-transcription/verification.md)，纪要与最新工程检查见 [Spec 004 实施报告](spec-004-meeting-minutes/implementation.md)。旧 Spec 的报告保留当时验证范围，不代表当前产品仍停留在旧状态。

## 文档分工

- `.ai/decisions/`：只保留重要结论、必要理由和长期限制；不要求每项改动建档，写法见 [留痕规则](../AGENTS.md#10-重要决策留痕)。
- `spec.md`：目标、行为、边界和验收标准；通过引用使用已有技术决策。
- `plan.md`：模块、数据流、接口／恢复契约、迁移和针对性验证方案；不重抄需求、安装命令或通用 Agent 流程。
- `implementation.md`：最终实现摘要、必要实现细节和已关闭的返工记录。
- `acceptance.md`：独立验收结论、覆盖、证据来源和未验证项；不能由实施者自评替代。
- `verification.md`：仅在有较多实测数据时使用，集中样本、参数、计时与 CI 证据；其他文档引用它。

状态在本索引汇总；路线图写方向，技术栈写工程约束，README 写使用入口。每条事实只写一处，普通修复不默认更新整套文档；不套日期和编号前缀，不写过程流水账。

## 生命周期

目录用 `spec-XXX-short-name/`。协调 Agent 起草决策并轻量自查，交用户审查，不安排决策子 Agent 或独立验收。关键决策确认 → 实施 Agent 开发 → 新的独立验收 → PASS 交付；FAIL 记录具体问题，交新的实施 Agent 返工，再由新的独立验收 Agent 检查。不开 Spec 的修改由协调 Agent 直接完成。具体遵循 [Spec 工作规则](../.ai/rules/spec-decision-workflow.md) 及 AGENTS.md 的验证 / 停止和分支收尾规则。

## 历史记录

Spec 001～014 的实施命令、源码路径与结果描述对应当时版本，不作为当前启动指南。Spec 015 迁移前内容可在 [6e83d28 快照](https://github.com/shi-YangYang/work-assistant-agent/tree/6e83d289a16a0783705ae17c879d39d1e059e839) 查阅；现行目录见 [技术栈](../constitution/tech-stack.md#目录约定)，新旧路径映射见 [Spec 015 Plan](spec-015-monorepo-structure/plan.md)。持续使用的评测入口及文档超链接随迁移更新，历史测试记录不改写成新命令。

2026-09-10 按用户要求整理：保留编号、需求、历史 PASS / FAIL、修复依据及证据，把已结束的分轮报告归并到各 Spec 的实施摘要与验收记录。本次仅整理文档，没有重新运行测试或改变验收结论。整理前完整原文可在 [Git 快照 23ba685](https://github.com/shi-YangYang/work-assistant-agent/tree/23ba685f5af58039ec30297d8e20af91eef61f10/specs) 查阅，也可用 `git show 23ba685:specs/<目录>/<原文件>` 恢复。

已完成的 Spec 001～003 专用交接文件于 2026-09-11 删除，结论保留在各 Spec；旧交接可通过 `git show e91748f:.ai/prompts/<原文件>` 查阅。后续只维护当前交接，避免重复保存已归档任务指令。

2026-09-13 按用户要求再次精简：保留 Spec／Decision 编号、需求和验收结论，归并重复方案与实施过程。旧 Spec 006／008 静态原型及首版形态比较改用固定 Git 链接；移除已落后于 package.json 的 pnpm 锁文件，沿用现有 npm／package-lock。整理前完整内容在 [236a9c4 快照](https://github.com/shi-YangYang/work-assistant-agent/tree/236a9c4e32785e4d35b0673e2165e237cbe16b2c)，可用 `git show 236a9c4:<路径>` 恢复；本次只做文档与引用检查，不代表重新验收。
