# 0012 — 公司模型服务与用途分配

2026-09-12 · ACCEPTED。用户审查 [Spec 009](../../specs/spec-009-company-model-services/spec.md) 后明确要求“开始实施”；以下作为实施依据，实际交付与验证以实施／验收报告为准。

## 决策与理由

- 多服务和推理预设沿用 [决策 0008](0008-meeting-minutes-provider.md)，公司服务配置归公司所有，由管理员维护；凭证仅供服务端使用，不能复用 Electron 的 safeStorage 文件或读取其 Key。
- 服务连接与业务用途分开。工作助手、报告、语音各自分配，报告可显式跟随工作助手。现有报告也通过工具写入草稿，因此纯文本连通不足以证明报告模型可用。
- 按接口协议适配，不维护厂商／型号／推理档位大全。首版聊天继续 Chat Completions，语音支持当前 Qwen-ASR 兼容方式与文件转写接口；模型目录失败时允许手填。其它私有协议随后按实际需求扩展，不将兼容接口理解为所有能力相同。
- 复用现有 Deep Agents／LangGraph 和已安装的网络、加密依赖；模型目录、连接测试、用途解析置于受控服务边界。无需引入网关产品、向量库、Redis 或另一个 Agent 框架。
- 使用服务器独立主密钥加密公司 API Key；主密钥不入库或版本库，备份时与数据库分别保管。业务配置变更会使旧检测失效，任务恢复必须区分输入版本与配置版本，避免恢复旧模型的待执行步骤后换用新模型。
- 三类用途的小样本测试与真实业务联调分别证明接口可用和业务质量。复用轻量 CI 检查固定响应／故障，真实调用不成为每次 PR 的自动步骤。

## 依据与兼容性限制

本机已安装 SDK 提供 Chat Completions、`/audio/transcriptions` 文件转写及自定义请求参数入口；现有 `worker.py` 的 Qwen-ASR 使用聊天端点，不能原样发给文件转写接口。路径、字段和适配职责集中在 [Plan](../../specs/spec-009-company-model-services/plan.md)，不在运行时按模型名猜测。

[LangChain 的 ChatOpenAI 文档](https://docs.langchain.com/oss/python/integrations/chat/openai) 区分标准参数与第三方 `extra_body`，并提示第三方能力有差异。保留显式 Chat Completions，禁止配置触发 SDK 自动切换 Responses；通用预设不携带本项目禁止用户覆盖的工具或输入字段。

[Qwen-ASR 文档](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference) 的兼容方式使用 `input_audio`，与文件上传转写不同；不同模型／地域支持方式不同。[百炼模型目录](https://help.aliyun.com/zh/model-studio/list-models) 也有独立分页接口。以上于 2026-09-12 核对，属于接口依据，不能替代用户实际账号测试；不把某一地域 URL 或模型 ID 设为唯一可选项。

## 取舍

配置进入数据库后需要凭证保护、版本冲突和任务快照，代价大于简单增加表单，但可以让管理员日常切换服务而无需重启。首版限制为已定义的协议和有限参数，避免任意 HTTP 模板或自动探测全部能力带来的复杂度与额外调用。原业务规则、Electron 数据及公司部署方向继续遵循 [决策 0011](0011-company-agent-direction.md)。
