# 0011 — 公司协作与业务 Agent 方向

2026-09-12 确认，2026-09-13 补充业务 Agent 定位。已实施基础见 [Spec 008](../../specs/spec-008-meeting-followup/spec.md)，后续补充不代表已落地。本文件记录需求来源与取舍，具体行为与验证由对应 Spec 维护。

## 需求来源与优先级

老板明确提出两项需求：会议多，需要记住责任事项、重要信息和会议安排；员工通过图片、文字、语音及零散消息汇报工作，由 Agent 整理，老板通过看板了解进展。当前汇报主要依靠线下会议，不能假设公司已有固定线上模板。

以用户所在公司试点，优先完成“员工消息 → 关联工作与进展 → 员工确认或纠正 → 日报／周报 → 老板看板”，减少重复汇报，保留事实依据。首期只有老板／管理员、员工两类角色；管理员可查看本公司员工已发送的原始上报和附件，汇报安排由管理员配置。具体权限和草稿边界由 Spec 008 定义。

组织架构、画像、RAG 属于用户扩展愿景；会议跟进、提醒及关联汇报留待后续。用户希望按老板时间调整提醒、逐渐了解其偏好，但尚未定义日程来源或授权自动调整范围。未上报不等于未工作，不做设备监控；未来画像须有来源、更新时间并允许纠正，不生成无依据的人员评价。

## 业务 Agent 定位补充

用户明确产品可采用 SaaS 交付形式，Agent 要融入实际业务：通过会话理解请求，依据授权信息调用工具，把结果落实到可持续跟进的工作与报告中。会话是交互入口，业务状态由系统保存；不能让业务能力只停留在聊天回复里。

管理员也保留工作助手和自己的工作空间。后续可向助手询问员工进度，并把自己的督办事项纳入工作跟进；这些能力按具体 Spec 落地，不因管理员身份自动开放所有数据或授权 Agent 自主修改员工记录。[Spec 011](../../specs/spec-011-web-function-management/spec.md) 定义本轮管理与多会话范围，不自动扩展 SaaS 注册、计费或组织层级。

用户已确认会话历史独立、已确认工作按权限跨会话可检索，让业务跟进不依赖单一聊天窗口。删除会话保留业务来源，管理员删除报告才清理对应原始材料；共享消息清理不递归删除其他已确认工作／报告，避免整理会话绕过发布保护或意外扩大删除影响。详细规则以 Spec 011 为准。

## 客户端与架构

- 首期采用适配电脑、手机浏览器的 Web＋共享服务端；老板／员工是权限角色，不对应不同设备或服务端／客户端。业务接口、身份及数据在服务端统一管理。
- **保留 Electron** 的本地录音、faster-whisper、纪要、回放与资料管理，按后续需求接入共享业务；不自动上传会议、迁移本地数据或同步桌面密钥。
- Web 延续实际 Electron 的主题、导航和交互，按 [决策 0009](0009-interface-design-direction.md) 做响应式适配；首期不同时建设独立手机 App 与完整桌面协作端。
- 各端同仓库、独立运行／构建／部署，在现有 `src/` 内扩展；暂不迁移目录或引入 Turborepo。一次变更可共同审查接口与 UI，并保留桌面独立发布能力。
- Spec 008 沿用旧会议跟进草案的编号和目录，原单机公司业务方案撤回；目录名称不代表仍在实施会议跟进。

## Harness 与技术取舍

用户明确允许按需使用 LangChain、LangGraph、AutoGen；此前将其理解为框架禁令是误读。业务 harness 负责授权上下文、受控工具、持久状态、预算、失败恢复和人工纠正，框架／runtime 为这些职责服务。

| 选择 | 理由与边界 |
| --- | --- |
| React／TypeScript／Vite＋浏览器路由 | 沿用界面技术和共享语义主题，Web 不依赖 Electron IPC |
| Python 3.12＋FastAPI／Uvicorn | 沿用 Python 经验，公司 API 与本地核心独立 |
| PostgreSQL＋SQLAlchemy／psycopg／Alembic | 同库保存业务任务与 checkpoint，附件使用私有持久卷；首期不加 Redis、Celery 或向量库 |
| Deep Agents＋LangGraph＋PostgreSQL checkpoint | 复用上下文整理、工具循环和恢复，业务权限、来源及人工确认由系统掌握 |
| Linux Docker Compose＋Caddy、API、单并发 worker、PostgreSQL | 小规模单机起步；外部 API 承担模型推理，服务器处理业务与有界媒体转换 |

Deep Agents 首版关闭子 Agent、命令执行、宿主文件和任意网络工具，仅开放授权业务工具与线程内虚拟上下文；员工输入不能改变权限。Agent 只提出进展和报告草稿，正式确认、发布由员工执行。比如“初稿完成，等待报价”后补充“报价拿到了”，可关联同一工作，但不能据此判定整个项目完成；归属不明时澄清。

采用现成 harness 可减少上下文与恢复维护成本，代价是升级时须核对工具集合、checkpoint 及模型兼容。框架命名不构成行业唯一标准。版本、路径和命令在 [技术栈](../../constitution/tech-stack.md#公司-web-与服务端基线)，具体预算与恢复契约在 [Plan](../../specs/spec-008-meeting-followup/plan.md)。

## 模型与部署边界

用户接受小服务器初期通过外部 API 完成图文理解、工具调用和短语音转写；不要求在约 2 核 2 GB 的业务服务器自托管 faster-whisper 或 LLM，也不承诺该容量已通过实测。

初始参考接入为百炼北京地域 `qwen3.5-flash-2026-02-23` 图文／工具模型和 `qwen3-asr-flash`：图片需要实际视觉能力，短语音规范为 WAV 后直接提交，可避免公开音频链接；默认不深度思考、不隐式重试结果未知的付费请求。该参考不绑定部署账户，现有多服务、用途与协议选择以 [决策 0012](0012-company-model-services.md) 为准。

公司服务集中保管账号、材料与工作记录，外部服务收到完成识别所必需的输入，首期 Web 依赖网络。账户、额度、域名、服务器与试点人数须在部署前准备；讨论不代表开通收费资源。真实联调、恢复、手机和容量的通过／未验边界仅在对应验收报告维护。

## 工程参考

以下为当时的方案依据，不代替项目实测：

- [LangChain 产品分层](https://docs.langchain.com/oss/python/concepts/products)、[Deep Agents 自定义](https://docs.langchain.com/oss/python/deepagents/customization)、[能力配置](https://docs.langchain.com/oss/python/deepagents/profiles)、[状态边界](https://docs.langchain.com/oss/python/deepagents/backends)。
- [Anthropic 长期运行 harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)、[有效 Agent](https://www.anthropic.com/engineering/building-effective-agents)：持久进展、清晰工具与简单组合；将编码经验用于公司业务是本项目的设计推论。
- 百炼 [图文／工具](https://help.aliyun.com/zh/model-studio/vision-model/)、[ASR 输入限制](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference)、[思考参数](https://help.aliyun.com/en/model-studio/deep-thinking)。
