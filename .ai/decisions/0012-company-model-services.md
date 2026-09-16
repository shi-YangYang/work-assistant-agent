# 公司模型服务与用途分配

- 服务配置归公司，由管理员维护；服务连接与业务用途分开，工作助手、报告、语音独立分配，报告可显式跟随工作助手。推理预设沿用 [桌面接入原则](0008-meeting-minutes-provider.md)。
- 按协议适配，不维护厂商／型号／推理档位大全。轻量预设只匹配已核实地址、地域与模型系列；未知项可手动选协议，目录失败仍能手填模型，不自动试探付费接口。
- 保存具体协议和选择模式，旧配置默认手动；规则更新不改变已保存任务。支持 Chat Completions、文件转写、Qwen-ASR 兼容及阿里原生语音协议，不能混用路径或字段。具体契约见 [接口方案](../../specs/spec-009-company-model-services/plan.md)。
- 公司 Key 只供服务端使用，以独立主密钥加密，不能读取或复用 Electron safeStorage 凭证。主密钥不入库或版本库，备份时与数据库分别保管。
- 配置变更使旧检测失效；任务锁定配置快照，恢复区分输入版本和配置版本，不能把旧工具步骤交给新模型继续执行。
- 工作助手保留受控工具循环与逐步反馈；报告返回固定栏目，经服务端校验后事务保存。纯文本连通不能证明报告模型可用。
- 用量区分服务商实际返回值与预算估算，保留调用时的模型归属。连通测试和真实业务质量分别验证；CI 用固定响应／故障，真实调用不成为每次 PR 的自动步骤。

复用现有 runtime、网络与加密依赖，不引入网关产品或任意 HTTP 模板。数据库配置增加了凭证、版本和快照管理，但支持管理员切换服务而无需重启。

协议依据：[ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)、[Qwen-ASR](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference)、[百炼模型目录](https://help.aliyun.com/zh/model-studio/list-models)。保持显式 Chat Completions，不让 SDK 自动切换 Responses；参数预设不能覆盖工具、输入或凭证。供应商文档不替代真实账号验证。
