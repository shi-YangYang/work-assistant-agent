# Plan：独立图片模型与聊天图片生成

## 对应 Spec

[独立图片模型与聊天图片生成](spec.md)。管理员用途分配、文字生图及兼容模型配置已实现；首批验证见[实施报告](implementation.md)，型号解耦扩展见[扩展报告](model-config.md)及[独立验收](model-config-acceptance.md)。Token Plan 方图真实回归通过，其他真实调用范围保留限制。

## 涉及模块

- 模型服务：扩展用途、图片协议和能力校验，沿用加密密钥、配置版本、冻结绑定、测试与用量。
- 图片集成适配器：处理 wan2.7-image 原生异步提交／任务查询、Token Plan 同步返回和结果下载；尺寸规则在后端确定性转换，不在这里判断用户数据权限。
- 图片业务模块：拥有生成操作、幂等、恢复、源授权、文件校验和成果发布，不与沙盒执行混为一体。
- Agent：按需发现图片工具，短规则说明调用时机；复用预算、回执和状态，不追加模型链。
- 私人成果：复用 PNG、版本、鉴权访问及展示，补实际宽高和未完成操作清理规则。
- Web：模型配置、用途分配、图片配置测试、用量与聊天图片展示；第一版不增加用户侧模型选择器或常驻尺寸选择器。

## 修改顺序

1. 按已确定的自动尺寸交互与下述官方协议落实适配器契约、实际区域地址与测试配置。首批只实现 wan2.7-image 文生图。
2. 明确用途与协议能力矩阵，扩展共享类型及前后端校验；修正非 chat 一律归为 ASR 的判断，兼容缺失 `image` 的旧配置。
3. 增加图片生成操作表和迁移，固定幂等键、租约归属、外部请求及发布状态。明确配置快照与老任务恢复规则。
4. 实现适配器、结果校验、私有落盘、成果发布与恢复；先通过可控服务夹具验证外部副作用边界。
5. 接入按需图片工具、能力目录、简短提示与进度，将成功回执挂回现有会话成果。未配置时保持清楚的能力边界。
6. 更新模型管理和成果 UI，复用 PNG 预览及鉴权下载，显示实测宽高；配置测试不自动触发生成。
7. 运行相关定向检查、故障恢复及有限真实调用／性能对比；再由新的独立 Agent 验收。

## 数据流

```text
管理员保存服务 → 用途分配 image → 图片模型配置版本
                                  ↓
用户消息 → 原聊天模型 → 按需加载图片工具
                                  ↓
                     冻结配置 + 领取稳定生成操作
                                  ↓
                        选定图片服务适配器
                                  ↓
                      取回图片 → 校验 → 私有文件
                                  ↓
                     租约／权限校验 → 发布成果版本
                                  ↓
                        会话预览／鉴权下载

重复调用／任务恢复 → 查询原操作 → 复用结果或继续查询／下载
结果无法确认且服务无恢复能力 → 明确未知状态，不自动再次生图
```

外部 I/O 不占数据库事务；图片字节不进入 Agent 的工具文本、checkpoint 或普通聊天 SSE。

## 接口变化

- `CompanyModel` 与服务配置增加选定图片协议及适用选项；`ModelRouting` 增加可空 `image`；测试用途和用量枚举同步。
- 图片配置测试使用独立的 `/settings/model-services/test-image` 请求和等待预算；旧 `/test` 的 `purpose=image` 仍兼容，不扩大普通聊天测试的等待时限。
- 用途字段缺失与显式 `null` 区分，避免旧客户端覆盖新配置。旧路由读取补默认，不强迫既有公司重新保存所有配置。
- 沿用提交消息接口；按已确定的管理员统一选择方案，用户请求无需携带生图模型 ID 或密钥。
- 新增 Agent 图片工具 `generate_image`，接收文字意图、比例／档位或明确宽高，返回内部可信成果引用；不提供参考图片或编辑参数。
- 继续使用成果详情／PNG 文件读取接口，文件元数据可选增加 width／height；旧文件无此字段仍能显示。外部服务 URL 不直接成为前端公开图片 URL。
- 内部增加持久生成操作表，保存 task_id 或同步结果回执、规范化尺寸和实际输出元数据；迁移编号按实施时最新版本确定，不伪装为已有沙盒任务。

## 万相协议与尺寸落点

- 使用管理员配置的百炼原生区域主机或精确 Token Plan 官方主机及匹配密钥；适配器明确解析原生 `/api/v1` 根地址，不能简单把聊天 `/compatible-mode/v1` 后拼生图路径，也不跨主机／区域复用凭证。
- 按[官方异步 API](https://help.aliyun.com/zh/model-studio/wan-image-generation-and-editing-api-reference)提交 `POST /api/v1/services/aigc/image-generation/generation`，携带 `X-DashScope-Async: enable`；保存 task_id 后通过同一服务的 `GET /api/v1/tasks/{task_id}` 恢复查询。首版只发送文字，关闭组图，默认 n=1。
- Token Plan 按[官方同步 API](https://help.aliyun.com/zh/model-studio/token-plan-multimodal-gen)提交 `POST /api/v1/services/aigc/multimodal-generation/generation`，不发送异步请求头。同源复用已有服务密钥；将同步图片 URL、用量和 request_id 保存为内部回执，再执行下载／发布。超时无回执不自动重发，已保存回执的下载或发布失败只复用原结果。
- `sizes.py` 接受明确像素或比例／档位，按 Spec 规定的优先级输出单个 size；常见 2K 比例复用[官方推荐表](https://help.aliyun.com/zh/model-studio/text-to-image)，其他合法比例按总像素档位确定性计算，避免让 LLM 反复试尺寸。
- 规范化后的 size 纳入操作摘要和配置／输入冻结，重试不重新推断比例。输入错误在外部提交前结束；收到图片后解码真实宽高并保存，避免使用请求尺寸冒充输出尺寸。
- task_id 已知时恢复查询；提交与 task_id 持久化之间的未知窗口仍按不自动重放处理。任务／结果有有效期，完成后及时下载，不把临时 URL 当长期成果。
- 图片模型未显式指定的思考等选项沿用服务商默认，不能为了提速私自关闭；聊天 low／high 不控制图片模型。

## 改造后的目录树

原位扩展现有模块，不迁移 Agent 治理目录。以下与最终实现对应；尺寸换算单独封装，编辑能力不纳入。

```text
packages/api-contracts/src/
└── index.ts                              [修改] 图片用途、模型与测试契约
apps/server/app/
├── modules/model_services/
│   ├── schemas.py                        [修改] 图片配置及用途校验
│   ├── service.py                        [修改] 能力矩阵、兼容读写和绑定保护
│   ├── bindings.py                       [修改] 图片模型版本快照与恢复
│   ├── probes.py                         [修改] 图片服务测试分支
│   ├── router.py                         [修改] 独立图片测试入口
│   └── image_probe.py                    [新增] 图片测试与既有用量记录衔接
├── integrations/models/images/           [新增] 原生异步与 Token Plan 同步万相协议
│   ├── wan.py                            [新增] 同步／异步提交、任务查询与错误归一化
│   ├── sizes.py                          [新增] 比例／档位转换、明确尺寸校验
│   └── results.py                        [新增] PNG 解析与安全下载
├── modules/image_generation/             [新增] 图片业务操作
│   ├── models.py                         [新增] 持久状态与幂等约束
│   ├── service.py                        [新增] 操作领取、恢复、私有存储与发布
│   └── files.py                          [新增] 待发布 PNG 缓存完整性检查
├── modules/deliverables/serializers.py    [修改] 成果实际宽高元数据；复用 PNG 下载接口
├── modules/executions/cleanup.py          [修改] 兼容图片成果与未完成操作的清理
├── modules/executions/quota.py            [修改] 提取既有存储锁供清理与图片发布复用
├── agent/
│   ├── tools/resources/images.py         [新增] 图片工具的业务入口
│   ├── tools/{catalog,registry}.py        [修改] 按需能力与工具注册
│   ├── prompts/{main,policies}.py         [修改] 简短能力说明及允许工具
│   └── runtime/
│       ├── tool_nodes.py                 [修改] 图片工具加载与并发边界
│       ├── progress/tools.py             [修改] 图片步骤名称
│       └── tool_progress/evidence.py     [修改] 图片回执证据与成果进度
├── db/registry.py                        [修改] 注册新增 ORM
└── migrations/versions/
    ├── 0029_image_generation.py          [新增，已应用] 操作表与唯一约束
    └── 0030_image_provider_result.py     [新增] 同步结果回执；兼容已应用 0029 的数据库
apps/web/src/api/client.ts                [修改] 独立图片测试等待预算
apps/web/src/features/
├── model-services/
│   ├── types.ts                          [修改] 图片用途与协议名称
│   ├── utils/{service-presets,service-drafts}.ts [修改] 能力识别和草稿兼容
│   ├── hooks/useModelServiceController.ts [修改] 图片用途保存
│   ├── api/requests.ts                   [修改] 图片测试请求分流
│   ├── components/ModelServices.tsx      [修改] 图片设置上下文
│   ├── components/Routing.tsx            [修改] 独立选择图片模型
│   ├── components/catalog/ModelOptions.tsx [修改] 图片适用配置
│   ├── components/service/ServiceModelLibrary.tsx [修改] 图片模型标识
│   ├── components/testing/ModelTestDialog.tsx [修改] 主动图片测试交互
│   └── components/usage/usage-display.ts [修改] 图片用途显示
└── assistant/components/deliverables/
    └── GeneratedFiles.tsx                [修改] PNG 预览、实际宽高与下载
tests/
├── server/modules/image_generation/
│   ├── test_configuration.py             [新增] 用途、绑定、配置与测试权限
│   ├── test_operations.py                [新增] 持久化、Agent 流程、幂等、隔离与恢复
│   ├── test_protocol.py                  [新增] 万相协议、尺寸与下载安全
│   ├── test_token_plan.py                [新增] 同步回执、幂等、取消与恢复
│   └── test_migration.py                 [新增] 0029／0030 隔离 schema 升降迁移与旧数据保留
├── web/model-services/image-model.test.ts [新增] 模型分类与用途匹配
├── web/dom/assistant/generated-image-size.test.tsx [新增] 图片真实宽高及旧文件兼容
└── web/requests/api.test.ts               [修改] 图片测试独立超时
README.md                                [修改] 图片能力说明
docs/setup.md                            [修改] 两种官方图片接口配置与运行说明
constitution/tech-stack.md               [修改] 图片协议边界
specs/
├── README.md                             [修改] 规格索引
└── spec-065-image-generation/
    ├── spec.md                           [新增] 需求、边界与待确认问题
    ├── plan.md                           [新增] 实施和验证计划
    ├── implementation.md                 [新增] 实施与测试证据
    ├── rework.md                         [新增] 缓存文件失效恢复返工与验证
    ├── token-plan-fix.md                 [新增] 官方同步协议纠错与定向验证
    └── acceptance.md                     [实施后新增] 独立验收与限制
```

模块中新 Python 包按项目惯例包含 `__init__.py`。如现有文件存储工具可安全复用，优先调用，不借机做大范围迁移；不能为了复用把图片生成导向沙盒服务。

## 测试计划

文档阶段 S0，仅检查内容、引用和 diff。实施涉及新协议、迁移、授权及外部副作用，按 S3 选择相关子系统检查，不默认运行桌面、物理麦克风或整个项目的测试。

- 配置：旧路由无图片字段、旧客户端保存、用途错配、移除在用模型、配置冻结／撤销、未配置场景与管理员权限。
- 适配器：固定图片／外部任务响应覆盖成功、429、拒绝、空结果、错误 MIME、超大／超像素、恶意 URL／重定向；不依赖用户密钥或真实网络故障。
- 幂等：重复 call ID 和不同 call ID 的同操作、并发领取、发送后断线、进程在回执保存前退出、结果保存后发布失败、租约换代、取消迟到结果；分别断言生成请求数与发布次数。
- 隔离：不同公司／员工生成、管理员查看其他人私人结果、跨会话引用、会话／成员删除、源权限失效以及清理竞争；只用测试库和临时媒体目录做破坏性测试。
- Agent 先验案例：画海报调用一次；只写提示词不生图；分析图片不生图；数据图表沿用原工具；未配置不循环；下载失败不生图；“再来一张”产生新操作；修改原图明确不支持而不偷偷重画。
- 尺寸：预设及非预设比例、明确像素优先、比例／像素冲突、默认 2K、1K、4K 拒绝、总像素及比例边界、真实返回尺寸；校验失败不请求服务商，换算不调用模型。
- Web：模型列表／用途／配置测试、生成进度、预览和下载、刷新恢复、错误收敛、手机宽度以及原有 PNG 成果回归。
- 性能：普通问答、工作查询、搜索、沙盒各固定输入，low／high 同配置交替对比；先验证无新增模型阶段及图片请求，再比较首段文字与总耗时。生图任务单独记录规划、图片服务、落盘及展示时间，不把供应商生成时间归为普通聊天回归。
- 真实服务：测试配置可用后，使用 wan2.7-image 进行少量方图／横图／竖图文字生成，验证实际尺寸与 PNG 持久化；不测图片编辑。记录参数、耗时、调用次数和成果；不把画面审美或模型文字拼写保证为系统正确率。

实施时选用现有 `npm run test:server -- <相关路径>`、`npm run test:web -- <相关路径>` 与契约相关类型检查；精确命令随最终文件范围确定。格式化只覆盖改动源码，已通过且未受后续改动影响的检查不重复。

## 风险

- 协议误判：不能以“非聊天”推断 ASR，也不能以模型名称证明图像接口兼容。
- 重复外部副作用：持久操作和外部幂等／查询配合；不可恢复的未知结果显式保留，不自动重放。
- 临时链接和清理：生成成功不代表文件已经交付，需区分下载、持久化和发布，防止误删恢复中的文件。
- 内存／连接占用：图像尺寸受控，网络等待不持有数据库连接，图片不混入聊天上下文。
- 提示词和工具膨胀：能力按需加载，不新增普通聊天模型轮次。

## 迁移策略

- 新增图片操作表，并通过独立的 0030 迁移增加同步结果回执，不能只修改已应用的 0029；图片模型配置继续保存在现有服务版本和用途 JSON 中，读取旧值时补未配置默认。
- 无用户图片数据搬迁，不要求重新输入已有服务密钥，不修改既有任务快照。
- 回滚应用时保留新增表与已发布成果；支持的格式通过同一鉴权路径读取。实现前核对回滚版本对新用途／协议字段的容忍性，不能承诺任意旧版本均可无损降级。

## 图片模型配置化扩展

在现有图片模块内将接口请求、模型尺寸预设和业务持久化分离。先扩展模型配置与前后端契约，再接通草稿／版本绑定、测试及图片生成，最后调整模型设置界面与定向验证。继续复用现有任务回执，无新增数据库表或迁移；0029／0030 已应用的任务保持可恢复。

本次预计目录增量（其他已有文件保持原位）：

```text
apps/server/app/
├── integrations/models/images/
│   ├── wan.py                 [修改] 按接口配置分流，不按型号限制准入
│   ├── profiles.py            [新增] 已知型号预设与可配置尺寸规则
│   ├── sizes.py               [修改] 使用模型规则确定尺寸
│   └── results.py             [修改] 通用 PNG 资源边界，支持 4K
├── modules/model_services/
│   ├── schemas.py             [修改] 图片模型设置校验
│   ├── drafts.py              [修改] 测试草稿携带图片设置
│   ├── bindings.py            [修改] 冻结配置传入运行时
│   └── image_probe.py         [修改] 复用模型默认尺寸及接口设置
├── modules/image_generation/service.py [修改] 按冻结配置规划尺寸与恢复
└── agent/
    ├── tools/resources/images.py      [修改] 模型通用工具说明
    └── prompts/main.py               [修改] 生图尺寸说明不绑定具体型号
packages/api-contracts/src/index.ts     [修改] 图片设置类型
apps/web/src/features/model-services/
├── components/catalog/ImageSettings.tsx [新增] 接口、尺寸模式与可选尺寸
├── components/catalog/ModelOptions.tsx  [修改] 接入图片设置
├── types.ts                            [修改] 通用图片协议显示
└── utils/
    ├── image-settings.ts              [新增] 图片设置校验与已知预设
    ├── service-drafts.ts              [修改] 草稿携带图片设置
    └── service-presets.ts             [修改] 型号识别与设置保留
tests/server/modules/image_generation/ [修改/新增] 配置化、尺寸、安全、恢复回归
tests/web/model-services/              [修改] 前端配置与契约回归
tests/web/dom/settings/image-settings.test.tsx [新增] 尺寸标签及设置交互
specs/spec-065-image-generation/        [修改/新增] 扩展范围、实施证据与验收
```

验证按接口与持久化影响选择相关子系统（S3）：自定义模型的手动接口与默认尺寸省略、固定列表、4K PNG、安全边界、配置版本冻结、旧任务恢复与重复调用；Web 覆盖设置编辑和类型契约。原生异步／Token Plan 同步均不新增失败后自动换接口重发。既有未改动的基准与全仓检查不重复执行。
