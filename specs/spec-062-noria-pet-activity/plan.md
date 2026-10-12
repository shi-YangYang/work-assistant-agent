# Plan：Noria 宠物工作状态

## 对应 Spec

[需求与验收标准](spec.md)。任务状态与双爪敲键盘动画已接入，动作幅度使用预览中加大后的版本；实施和返工均已通过[独立验收](acceptance.md)。

## 涉及模块

- 后端任务查询：提供当前用户可访问的聊天活动任务摘要，不变更执行流程。
- 公共活动状态模块：接收本地发送／任务回执、读取账号活动快照、复用 job 反馈订阅，维护账号隔离与生命周期。
- 聊天提交模块：仅发布临时发送开始／结束及已接受任务，不把宠物作为业务依赖。
- `Shell` 与宠物：应用层持有观察，宠物消费聚合后的 idle／working／unknown 状态。
- 测试：覆盖身份边界、状态竞争、连接复用及界面行为，不测试模型答案质量。

## 修改顺序

1. 将已确认的敲键盘素材归档，沿用样片的 Canvas 双爪交替按压及 32 源像素幅度；按实际显示尺寸控制渲染成本，保留暂停和减少动态效果。
2. 补充活动任务摘要契约与只读查询，复用既有权限检查和任务状态，排除删除或不可见消息。
3. 实现公共活动状态模块及 hook，明确临时发送到服务器任务的原子交接、旧响应丢弃及清理规则。
4. 接入提交／重试回执与 Shell 生命周期，检查现有 visibility／online 恢复协调，合并同轮重复请求。
5. 在现有宠物组件接入已确认的空闲／工作素材与状态文字，保留眨眼、白色圆形外观与既有动画控制；CSS 不增加文档流高度。
6. 格式化修改文件，执行相关检查及浏览器验收；新的独立验收 Agent 按 Spec 检查，完成后交付。

## 数据流

```text
本地发送开始 ──→ 临时 sending ──→ 上传／提交回执 ──→ 注册真实 job
                     │                               │
                   失败清理                      共享 job 反馈
                                                     │
登录／刷新／可见／在线 ──→ 当前用户活动快照 ──→ 合并与新旧校验
                                                     │
                                             聚合活动／未知状态
                                                     │
                                             Shell → PetStage
```

- 本地临时项使用本次提交标识，任务回执中的 job ID 接管后清理该项，不能先清空再注册。
- 用户范围包含身份及请求 epoch；快照读取起点与本地事件修订号共同用于防止旧快照覆盖新回执。
- 任务订阅复用 `job-feedback` 已有 Map 与终态关闭逻辑；账号活动模块增加消费者，不能另建 SSE 客户端。只有实际活动或待恢复的 job 才持有订阅。
- 宠物只订阅聚合状态变化；token、工具节点和上下文估算变化不得触发无关的全页面重渲染或活动快照查询。
- 人工等待与所有终态释放工作计数；网络错误保留未知事实，恢复时做一次同步。后端快照只能表示其读取时刻，不能覆盖读取后发生的本地变化。

## 接口变化

新增 `GET /api/v1/assistant/activity`，只读、需登录、禁止缓存。

- 返回当前用户的 queued／running 聊天任务摘要，至少含 job ID、conversation ID、target ID、state、stage、attempt、fence、updatedAt，字段复用现有契约。
- 查询同时约束公司、用户、消息及会话有效性，并检查当前业务可见性；管理角色无扩大范围。
- 不返回其他账号任务、聊天正文、错误诊断或模型数据；不为每个会话发起单独查询。
- SSE 使用已有每任务接口。快照与事件的幂等合并由公共活动模块承担；不改变 job 的执行状态、调度和数据库结构。
- 后端暂不可用时不得按空列表解释为全部结束；通过统一请求层处理身份失效和网络错误。

## 测试计划

规格编写为 S0：检查文档 diff、引用及需求一致性，不运行业务测试。

实施涉及跨模块共享状态及新增需认证的只读 API，按 S3 的相关风险进行定向验证，不默认全仓测试：

1. 后端活动查询：本人跨会话活动、终态排除、账号／公司隔离、管理员不能看到他人、删除及权限变更；追加在现有会话任务状态测试中。
2. 状态与连接：临时发送交接、旧快照竞争、多个任务、失败／取消／等待输入／重试、新旧 attempt、断线恢复、登出清理；验证相同 job 共享 SSE、同轮同步去重及无定时请求。
3. DOM：工作状态文字、空闲与工作素材切换、各页面持续观察、手机导航与主题弹窗、可见性和减少动态效果；已有语音提交测试继续覆盖发送失败清理。
4. 真实浏览器：桌面与手机视口各走一条“发送→工作→切页→结束”流程，确认无额外空行和控件遮挡；截图记录空闲、工作、主题弹窗。用可控任务反馈验证长时间工作，无须真实模型多轮付费回放。

前端使用项目 `npm run test:web -- <本次相关测试文件>`；后端按现有 pytest 环境定向运行 `tests/server/modules/conversations/test_conversation_task_state.py`。源码只格式化涉及文件；新增契约按相关包类型检查。失败后仅针对具体原因扩大范围，不重复已经通过且未变更的检查。浏览器模拟手机不等于实际 vivo／钉钉真机验收。

## 风险

- 把会话级 hook 提到布局直接调用，会造成公共层反向依赖与恢复请求重复；公共活动模块应独立，并复用原事件客户端。
- 多任务时连接数量随活动 job 增加；不得为同一 job 重复连接，不为历史／终态任务常驻订阅。
- 全局订阅收到正文事件时，不能让每段文字驱动整个 Shell 更新。
- 头像顶部已有名字重叠设计，额外状态文字需检查手机点击区域；不能通过新增整行或大面积 padding 解决。
- 新设备上的任务创建不会主动广播给所有设备；按 Spec 的有限同步时机发现，不能宣传为全设备即时监控。
- 图像生成与动画都可能偏离原小熊的比例、毛色和质感；先验证静态相似度，再检查动画中有无五官漂移，不能以增加动作掩盖角色不一致。
- 动画有下载、解码和内存成本；素材格式、尺寸与播放控制需用样片验证，不能因不使用 WebGL 就省略手机端检查。

## 迁移策略

无数据库、用户数据或生产配置迁移。新增只读接口随应用发布；保留原会话任务接口。回退时移除活动观察并恢复现有宠物素材即可，原任务、消息及主题功能继续使用。

## 预计涉及文件

以下包含预览与状态功能的预计范围，不迁移现有目录。预览保存在既有忽略目录 `artifacts/` 中；正式资源单独归档，不替换原品牌头像。停止的建模尝试不作为实施产物。

```text
artifacts/spec062/visuals/
├── working-preview.png                           [新增] 基于原图生成的工作形象预览
├── working-prompt.md                              [新增] 首版生成提示词与原图来源
├── typing-sheet.png                              [新增] 敲键盘动作帧素材
├── typing-prompt.md                               [新增] 动作帧生成提示词
├── typing-preview.html                            [新增] 独立可播放动画预览
└── typing-preview.webm                            [新增] 导出的打字动画样片
specs/
├── README.md                                      [修改] Spec 索引
└── spec-062-noria-pet-activity/
    ├── spec.md                                    [新增] 需求与验收标准
    ├── plan.md                                    [新增] 状态设计与验证范围
    ├── implementation.md                          [新增] 实施结果及验证证据
    └── acceptance.md                              [新增] 独立验收结果
docs/design/README.md                              [修改] 全页面状态与动画基准、素材登记
apps/server/app/tasks/
├── router.py                                      [修改] 当前用户活动摘要入口
└── runtime/conversation_activity.py                [修改] 活动查询及访问范围
packages/api-contracts/src/index.ts                 [修改] 最小活动摘要类型
packages/ui-web/
├── package.json                                   [修改] 工作形象素材导出
└── brand/pet/working.png                           [新增] 正式工作形象素材
apps/web/src/
├── api/
│   ├── assistant-activity.ts                      [新增] 活动快照、状态聚合、共享订阅
│   └── job-feedback.ts                            [修改] 新活动快照确认后恢复不可访问的共享订阅
├── hooks/useAssistantActivity.ts                   [新增] 应用层观察与 React 订阅
├── app/layout/
│   ├── Shell.tsx                                  [修改] 全页面挂载活动观察
│   └── pet/
│       ├── PetStage.tsx                           [修改] 消费工作状态并显示文字
│       ├── PetStage.module.css                    [修改] 悬浮状态标签及窄屏适配
│       ├── NoriaPet.tsx                           [修改] 空闲／工作素材切换及动画控制
│       ├── NoriaPet.module.css                    [修改] 状态形象外观与尺寸
│       ├── NoriaWorkingPet.tsx                     [新增] 工作动作 Canvas 及生命周期
│       └── typing-animation.ts                     [新增] 已确认双爪动作渲染
└── features/assistant/hooks/
    ├── composer/useMessageSubmission.ts           [修改] 发布临时发送生命周期
    └── conversation/
        ├── useAssistantTask.ts                    [修改] 注册回执与重试状态
        └── useAssistantInteraction.ts             [修改] 人工补充后继续任务的状态交接
tests/
├── server/modules/conversations/test_conversation_task_state.py [修改] 活动查询与权限
└── web/
    ├── assistant/assistant-activity.test.ts        [新增] 状态聚合、竞争与连接计数
    ├── assistant/job-connection.test.ts            [修改] 共享连接与受控恢复回归检查
    └── dom/
        ├── shell/noria-pet.test.tsx                [修改] 工作形象、状态与页面生命周期
        ├── shell/assistant-activity.test.tsx       [新增] StrictMode 冷启动与账号生命周期
        └── assistant/assistant-task.test.tsx       [修改] 发送／回执／重试衔接
```
