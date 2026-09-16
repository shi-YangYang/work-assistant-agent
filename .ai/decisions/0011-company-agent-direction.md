# 公司协作与业务 Agent

## 产品方向

以用户所在公司试点，优先解决老板提出的两件事：会议责任事项与安排容易遗忘；员工汇报分散，老板难以及时掌握进展。

先完成“员工消息 → 工作进展 → 本人确认或纠正 → 日报／周报 → 团队看板”。仅设管理员、员工两类角色，汇报安排由管理员配置。管理员可查看本公司员工已发送的上报；Agent 团队问答只使用已确认业务及关联材料，具体边界见 [团队授权](0014-team-assistant-authorization.md)。

- 产品可按 SaaS 交付，但会话只是入口，业务状态必须落到系统中的工作与报告，不能停留在聊天回复。
- 管理员保留工作助手和本人工作空间；本人督办遵循相同的操作规则，不代员工修改记录。会话历史独立，正式工作可按权限跨会话检索。
- 删除会话保留业务来源；管理员删除报告按既定范围清理原材料，不递归删除其他已确认工作或报告。详细规则见 [业务管理](../../specs/spec-011-web-function-management/spec.md)。
- 日报／周报使用站内待办和提醒，员工审阅后提交；无已确认工作仍需据实填写，未录入不等于免交。问题反馈独立于业务消息和 Agent 记忆，由公司管理员处理，不接站外工单。
- 组织架构、画像、RAG 和老板个性化日程属于后续方向，未定义的自动操作不提前授权。不做设备监控；未上报不等于没工作，画像须有依据并可纠正。

## 客户端与运行方式

- Web＋共享服务端适配电脑和手机浏览器，优先 Safari／Chrome；角色与设备无关，身份、权限和数据由服务端统一管理。
- 保留 Electron 本地会议功能，不自动上传会议、迁移本地资料或同步桌面密钥。Web 延续 [桌面设计原则](0009-interface-design-direction.md)，不另做一套手机视觉风格。
- 各端同仓库、独立运行／构建／部署，按 [多端目录方案](0015-multi-client-repository.md) 分工；暂不同时建设独立手机 App。
- 沿用 React／TypeScript／Vite 与 Python／FastAPI。PostgreSQL 保存业务、任务及 checkpoint；私有附件放持久卷。Linux Docker Compose＋Caddy、API、单 worker 进程起步，任务有界并发、同成员串行，不额外引入 Redis、Celery、向量库或构建调度层。

## Harness 与模型

- 允许使用 LangChain、LangGraph、AutoGen 等 runtime；业务 harness 掌握授权上下文、受控工具、来源、预算、持久恢复和人工纠正，框架为这些职责服务。
- 采用 Deep Agents／LangGraph 复用上下文和工具循环，关闭业务 Agent 的子 Agent、命令执行、宿主文件及任意网络工具。用户明确指令可通过受控业务服务直接创建、编辑本人工作或报告草稿；材料推断仍只提建议，报告提交与删除需预览确认。页面与助手共用授权、修订和持久结果，具体范围见[工作助手业务操作](../../specs/spec-021-assistant-business-actions/spec.md)。
- 报告采用结构化输出，由服务端校验并保存，避免把模型是否调用保存工具当成完成条件；聊天继续走受控工具循环。
- 图文理解、工具调用和短语音转写使用外部 API，小型业务服务器不自托管大模型或 faster-whisper。语音规范为 WAV 后提交，不需要公开音频地址；外发限于必要材料，不隐式重试结果未知的付费请求。
- 服务商、模型和协议可配置，见 [模型服务](0012-company-model-services.md)。不绑定初始参考型号；服务器容量、手机兼容及真实模型质量以实际验收为准，讨论方案不代表购买资源。

参考：[Deep Agents 定制](https://docs.langchain.com/oss/python/deepagents/customization)、[能力配置](https://docs.langchain.com/oss/python/deepagents/profiles)、[状态边界](https://docs.langchain.com/oss/python/deepagents/backends)、[长期运行 harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)。具体版本、路径和命令见 [技术栈](../../constitution/tech-stack.md)。
