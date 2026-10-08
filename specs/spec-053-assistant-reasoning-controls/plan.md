# Plan：直接配置思考强度

## 数据流

管理员在模型设置保存可选强度和初始强度 → 本人设置接口返回实际字符串 → 账号保存所选字符串 → 消息接受时冻结模型版本和强度 → 协议层组装实际参数。

工作助手用途不再覆盖模型初始强度。报告保留必要的独立参数兼容。高级参数、供应商适配和历史版本读取集中在后端，不要求员工理解。

## 实施顺序

1. 删除新契约中的 CompanyPreset / Preset 与 presetId，模型增加直接 reasoning 配置，用户引用改为 effort；约束重复值、无效初始值和受保护参数。
2. 添加旧活动配置迁移，转换账号偏好和用途引用；历史 revision 与任务 binding 只读兼容。迁移不重加密密钥或修改不可变历史。
3. 改造 service、bindings、parameters、本人设置及发送路径，保持乐观版本、幂等和快照语义。
4. 删除预设编辑器/状态，新增模型内思考强度设置；用途分配去掉助手初始预设。更新助手 hook 和 picker 的引用契约。
5. 定向验证迁移、参数、快照与界面，新的独立 Agent 验收。

## 改造目录

`~` 修改、`+` 新增、`-` 删除。本树为本次简化涉及范围；上一阶段 token 限制与核对调用的修改保留。

```text
apps/server/app/
├── migrations/versions/0028_direct_reasoning.py                  + 活动配置与偏好迁移
├── modules/model_services/
│   ├── schemas.py                                              ~ 模型直接强度与参数
│   ├── service.py                                              ~ 保存、用途、导入
│   ├── bindings.py                                             ~ 新引用与历史快照
│   ├── parameters.py                                           ~ 实际请求参数
│   └── reasoning/
│       ├── policy.py                                           ~ 可选强度和初始强度
│       ├── schemas.py                                          ~ effort 引用
│       ├── settings.py                                         ~ 账号直接选择
│       └── legacy.py                                           + 集中历史转换
├── modules/messages/{schemas,commands,router}.py                ~ 发送引用兼容
└── agent/、tasks/                                              ~ 仅受旧预设引用影响调用点
apps/web/src/features/
├── model-services/
│   ├── components/catalog/ReasoningPresetEditor.tsx              - 删除预设弹窗
│   ├── components/catalog/ReasoningPresetEditor.module.css       - 删除私有样式
│   ├── components/catalog/ReasoningSettings.tsx                  + 模型内直接配置
│   ├── components/catalog/ReasoningSettings.module.css           + 私有布局
│   ├── components/catalog/ModelOptions.tsx                       ~ 新配置入口
│   ├── components/Routing.tsx                                   ~ 去掉重复入口
│   ├── hooks/{useModelServiceController,useServiceDraftSession}.ts ~ 编辑状态与旧草稿
│   ├── components/ModelServices.tsx                             ~ 移除预设弹窗组合
│   └── utils/{service-drafts,service-presets}.ts                 ~ 模型草稿及校验
└── assistant/
    ├── api/reasoning.ts                                         ~ effort 请求
    ├── hooks/{useReasoningEffort,useMessageSubmission}.ts        ~ 偏好与发送引用
    ├── components/composer/reasoning/ReasoningEffortPicker.tsx   ~ 实际强度选项
    └── lib/audio-capture.ts                                    ~ 旧待发引用兼容类型
packages/api-contracts/src/index.ts                              ~ 删除预设实体
scripts/benchmarks/agent-evaluation.py                          ~ 评测配置引用同步
tests/server/{test_model_services,test_assistant_reasoning,
              test_assistant_reasoning_migration,
              test_model_service_http_coverage,
              test_report_reliability,work_record_eval_runtime}.py ~ 迁移、隔离、恢复与报告参数
tests/web/model-service-drafts.test.ts                          ~ 直接配置
tests/web/dom/assistant-reasoning.test.tsx                       ~ 用户选择
tests/web/dom/model-routing-legacy.test.tsx                      + 旧用途草稿明确恢复
```

## 验证

本次涉及持久配置、迁移、共享契约和任务绑定，按 S3 做相关子系统检查，不跑全项目套件。重点覆盖：旧 simple/advanced 配置、报告不同参数、用户偏好、历史任务、迁移重复执行/升级路径；当前配置版本与账号隔离；发送及上传竞态；主任务/核对和输出限制回归。相关测试通过不重复运行。

源码使用项目格式化器整理本次涉及文件；共享 TS 契约变更做 Web typecheck、相关模块测试和改动文件 lint。浏览器检查管理员配置到用户选档的完整流程及窄屏布局；用固定响应验证真实请求组包，不重复上一轮付费模型质量采样。

## 风险与回滚

新增配置不再依赖预设实体。历史参数兼容仅用于迁移及旧 revision/任务读取，特殊参数不能以简化为由静默丢弃。数据库采用新的迁移版本，不修改已经应用的 0027；发布时 Web、API、worker 同步更新。已有业务数据和加密密钥保持。0028 不支持自动降级为命名预设；迁移前备份相关配置，回滚须恢复备份。
