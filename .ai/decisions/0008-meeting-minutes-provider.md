# Decision 0008 — 会议纪要的模型接入

状态：已确认，2026-09-10；用户要求恢复实施。

## 决策与依据

用户选择在线模型 API，在应用设置中保存多家服务的地址、模型和密钥，选定一家在转写完成后自动生成纪要；支持动态模型列表、自定义推理预设和实际连通性检测。共享 OpenAI 兼容传输，不新增本地大模型。产品行为与验收见 [Spec 004](../../specs/spec-004-meeting-minutes/spec.md)，协议、存储和运行边界见 [Plan](../../specs/spec-004-meeting-minutes/plan.md)。

多服务保存取代起草时单组配置的限制；本轮不引入多模型并行、自动路由或故障切换。

采用 Chat Completions 的文本请求协议。官方接口支持 `model`、`messages` 和非流式返回；本项目为满足第三方兼容需求采用该接口，未采用面向 OpenAI 原生新项目推荐的 Responses。各模型可选参数支持不同，因此不把专有结构化输出能力设为通用前提，应用仍负责校验返回结构与原文引用。[官方接口文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

密钥由 Electron 主进程使用异步 safeStorage 保护：macOS 依赖 Keychain，Windows 依赖 DPAPI，密文保存在应用数据目录；不增加普通明文回退。该机制用于静态存储保护，不能承诺防止同一用户权限下的其他程序访问；无可用系统保护时应明确报错。[Electron safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)

## 自定义推理预设

用户提出还需支持 MiniMax、Kimi 及其他未列出的模型，要求自行输入多个推理强度并选择，随后指示恢复实施。采用按服务／模型保存的自定义推理预设：简单模式填写 reasoning_effort 字符串，高级模式填写受约束的 JSON 参数。保留服务默认和实际连接检测；用户声明的选项不标记为服务已证实支持。

取消原先逐厂商／型号硬编码强度的计划。参数由用户维护，可扩展新型号；同时校验请求边界，禁止覆盖会议输入、凭证、模型、工具和传输控制。参数被服务接受不等于其必然生效，不通过额外付费试探或静默降档来判断。

## 模型能力依据（2026-09-10 核对）

[OpenAI models](https://developers.openai.com/api/reference/resources/models/methods/list) 与 [DeepSeek models](https://api-docs.deepseek.com/api/list-models/) 返回基本目录，不能据此推断推理档位；[百炼目录](https://help.aliyun.com/zh/model-studio/list-models) 使用独立分页路径，可提供模态等元数据。目录可见与生成权限须分别验证。

参数差异说明自定义方案的必要性：[DeepSeek](https://api-docs.deepseek.com/guides/thinking_mode/) 区分思考开关和 effort；[GLM](https://docs.bigmodel.cn/cn/guide/start/concept-param) 的不同版本支持不同参数；[Qwen](https://help.aliyun.com/zh/model-studio/deep-thinking/) 使用 enable_thinking 和 thinking_budget，部分模型要求流式。保留这些依据，不维护容易过期的型号／强度清单，也不将资料核对写成真实账号实测。

## 取舍

- 在线生成引入网络、费用和文字外发；在设置中显示接收方及自动生成开关，录音文件继续只保存在本地。
- 首版完整转写单次生成，优先完成可核对的会后闭环；分层长文本整理留后续，超限明确失败。
- 结构正确与引用存在不能证明内容准确；真实服务质量验收必须与 CI 模拟故障测试分别记录。
