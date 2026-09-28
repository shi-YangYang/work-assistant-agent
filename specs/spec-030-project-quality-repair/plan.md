# 实施计划

行为和验收以 [Spec](spec.md) 为准。删除员工同步清理服务端声纹及登记录音，停用保留；历史遗留资料由管理员显式清理。

## 四维交付

| 维度 | 实施重点 | 验收证据 |
| --- | --- | --- |
| 功能代码 | R1～R4、R8：竞态、声纹、契约、认证权限、性能 | 定向回归、模块检查、查询前后对比 |
| UI 设计 | R6、R7：两端层级、阅读区域、响应式、空状态 | 逐页截图、尺寸检查、主题和键盘操作 |
| 流程设计 | R5 及 R2/R4 的业务路径：配置、重试、状态与删除 | 正常/失败/恢复路径、角色与入口一致性 |
| 目录结构 | R9：状态与组件职责、依赖方向、共用资源和测试归属 | diff、依赖检查、模型资源校验与构建定位 |

四维分别验收，不用代码测试结果替代界面、流程或结构检查。

## 分阶段实施

1. **固定回归与契约**：为保存竞态、会话搜索、声纹分块、姓名上限、限流并发建立最小复现；统一报告删除与手动重试规则。
2. **后端可靠性**：完成声纹读取、资料生命周期、登录限流、共享删除用例、报告重试。以权限、回执、版本和取消边界为主，不混入布局调整。
3. **Web 状态与体验**：提交保护、分页 Hook、报告重试、模型服务控制器；再处理详情空状态、手机导航/筛选、用量呈现和路由拆包。
4. **桌面修复与布局**：统一跨语言契约和错误，提取会议头部/文字工具区/模型状态；检查录音、播放和导航生命周期。
5. **性能与资源**：SQL 聚合分页、明确的并发只读路径，最后移动共用权重并更新所有消费者。保存性能基线及资源校验结果。
6. **集成与独立验收**：执行最终版本的相关完整模块检查，逐页查看主要状态，按四个维度与 R1～R9 交付结果和未执行边界。

高度耦合的后端修改由同一实施 Agent 串行处理；Web、桌面在 DTO/契约稳定后可按不重叠文件分工。最终由新的独立验收 Agent 检查，协调 Agent 处理问题闭环。文档阶段不创建子 Agent。

## 改造目录

`改` 为原位修改，`增` 为新增，`移` 为移动；列出主要实现和验证入口。按职责拆分，不为降低单文件行数制造空壳。

```text
apps/web/
├── package.json、vitest.config.ts               # 改：真实 DOM 测试依赖与 TSX 用例入口
└── src/
    ├── app/
    │   ├── AppRoutes.tsx、AppRoutes.module.css  # 改：路由延迟加载、局部加载/失败状态
    │   ├── Breadcrumbs.tsx、Breadcrumbs.module.css # 改：手机导航层级
    ├── components/TimeField.tsx、styles/layout.module.css # 改：禁用时间选择及手机标题
    ├── hooks/useDraftSubmission.ts             # 增：提交快照、代次、busy 与条件清理
    └── features/
        ├── work/components/
        │   ├── WorkEditor.tsx、ProgressEditor.tsx、ProgressFields.tsx # 改：安全保存
        │   └── WorkDetail.tsx、WorkDetail.module.css # 改：空内容与主要编辑入口
        ├── reports/components/
        │   └── ReportDetail.tsx               # 改：提交保护，复用任务重试组件
        ├── settings/components/RulesPage.tsx   # 改：保存期间字段与草稿保护
        ├── assistant/
        │   ├── api/requests.ts                # 改：分页取消信号
        │   ├── hooks/useConversationSearch.ts # 增：搜索与游标的单一状态所有者
        │   └── components/ConversationPicker.tsx、Conversations.tsx # 改：接入分页 Hook
        ├── jobs/components/JobNotice.tsx       # 改：报告单入口及异步任务隔离
        ├── team/
        │   ├── components/TeamFilters.tsx、TeamResults.tsx、TeamWorkspace.tsx # 改：手机筛选收纳
        │   └── styles/team.module.css         # 改：统计和结果区密度
        ├── model-services/
        │   ├── hooks/useModelServiceController.ts # 增：配置流程状态所有者
        │   ├── hooks/useServiceDraftSession.ts、useServiceCheck.ts # 改：受控草稿与检查
        │   ├── components/ModelServices.tsx、ServiceEditor.tsx # 改：配置主流程
        │   ├── components/Routing.tsx # 改：模型与用途衔接
        │   ├── components/ModelUsagePage.tsx # 改：已知/未知统计
        │   └── styles/model-services.module.css # 改：分层与窄屏
        ├── members/api/requests.ts、components/DeleteMember.tsx # 改：声纹删除影响
        └── voiceprints/                       # 改：遗留清理入口、影响预览与恢复提示
            ├── api/requests.ts
            ├── components/VoiceprintsPage.tsx
            ├── components/VoiceprintCleanup.tsx # 增：清理预览和恢复
            └── styles/voiceprints.module.css
apps/server/app/
├── http/dependencies.py、security/locks.py     # 改：显式只读共享锁与写入排他边界
├── agent/tools/actions.py                   # 改：报告删除的最小目标授权
├── migrations/versions/0014_voiceprint_cleanup.py # 增：持久化清理队列表，不清除历史资料
├── tasks/
│   ├── voiceprints.py                        # 改：有界完整读取、取消与迟到写入防护
│   ├── router.py                             # 改：报告重试使用最新配置
│   └── maintenance.py                        # 改：可恢复清理，不自动清除历史未知资料
├── modules/
│   ├── auth/router.py            # 改：原子登录失败限流
│   ├── members/commands.py、router.py         # 改：删除账号与声纹生命周期
│   ├── voiceprints/service.py、router.py      # 改：额度、清理与删除入口
│   ├── voiceprints/models.py                 # 改：最小清理意图记录
│   ├── voiceprints/cleanup.py                # 增：删除意图与可重试文件清理
│   ├── operations/targets.py                 # 改：复用现有报告删除授权
│   ├── reports/router.py                     # 改：HTTP 接入相同业务用例
│   ├── model_services/bindings.py、usage.py、usage_router.py # 改：SQL 统计/分页与只读依赖
│   └── team/metrics.py、router.py、workspace.py、workspace_router.py # 改：授权查询复用与并发读
└── core/config.py                            # 改：共享声纹权重默认位置
apps/desktop/
├── src/main/core-manager.ts、json-line-client.ts # 改：姓名读取契约与安全领域错误
├── src/shared/speaker-contracts.ts            # 改：统一姓名计数/上限
├── src/renderer/
│   ├── App.tsx、MeetingWorkspace.tsx、MeetingMinutes.tsx # 改：会议详情编排
│   ├── MeetingDetailHeader.tsx                # 增：详情标题与动作栏
│   ├── TranscriptionToolbar.tsx               # 增：文字模式与次级处理信息
│   ├── Transcription.tsx、SpeakerPanel.tsx     # 改：读取空间与命名
│   ├── MeetingLibraryList.tsx、MeetingProcessingState.tsx、meeting-processing-queue.ts # 改：阶段状态语义
│   ├── ModelSettings.tsx                      # 改：保留展示，状态交给 Hook
│   ├── useModelSettings.ts                    # 增：桌面模型配置状态
│   └── styles.css                             # 改：现有黑白灰布局
└── core/src/paa_core/
    ├── speaker_store.py                       # 改：一致的姓名校验
    └── speaker_worker.py                      # 改：开发态共用资源位置
packages/
├── api-contracts/src/index.ts                  # 改：删除影响与清理 DTO
└── voiceprint-engine/
    ├── src/paa_voiceprints/__init__.py         # 改：统一模型定位
    └── resources/models/speaker-community-1/  # 移自 apps/desktop/resources/models/；权重与许可证原样
scripts/
├── company/install-voiceprints.py              # 改：共用资源位置
├── desktop/build-core.mjs                      # 改：构建输入迁移，冻结包内路径不变
└── benchmarks/
    ├── company-voiceprints.py                 # 改：共用资源位置
    └── company-queries.py                     # 增：测试数据查询/锁等待对比，不写生产
deploy/company/Dockerfile                       # 改：共用资源 COPY
tests/
├── web/dom/                                   # 增：真实 React DOM 的定向交互回归
│   ├── helpers.tsx、draft-submission.test.tsx、draft-pages.test.tsx
│   ├── conversation-search.test.tsx、route-recovery.test.tsx
│   ├── report-retry-model-services.test.tsx、job-notice.test.tsx
│   └── voiceprint-cleanup.test.tsx
├── web/business-form-validation.test.ts、routes.test.ts # 改：表单与路由回归
├── server/
│   ├── test_auth_concurrency.py               # 增：限流、并发读取与撤权顺序
│   ├── test_voiceprint_lifecycle.py            # 增：分块、取消、账号删除和清理
│   ├── test_business_actions.py               # 改：HTTP/Agent 删除规则一致
│   ├── test_member_deletion.py                # 改：声纹生命周期
│   ├── test_report_reliability.py              # 改：报告重试、配置与版本
│   └── test_model_services.py、test_password_schema_migration.py # 改：重试与迁移
├── desktop/core-manager.test.ts、speaker-contracts.test.ts、json-line-client.test.ts、fixture-core.mjs # 改：跨层边界
├── desktop/meeting-library.test.ts              # 改：阶段状态
└── core/test_speakers.py                        # 改：姓名与两种资源定位
.prettierignore                                 # 改：保留上游资源原始字节
package-lock.json                               # 改：仅必要 DOM 测试依赖
docs/architecture.md、docs/setup.md              # 改：仅同步实际变化的路径/使用方式
constitution/tech-stack.md                      # 改：共享权重归属
```

新增最小声纹文件清理队列表，记录公司、成员、私有路径及重试状态，不存声纹模板。迁移只建表，不自动清理历史资料；删除事务持久化清理意图，worker 可在失败或重启后继续。

## 数据流与接口

- 表单：当前账号/记录草稿 → 提交快照与版本 → 禁用编辑 → API → 仅清理相同快照 → 成功刷新或保留失败草稿。
- 会话：关键词代次 → 取消旧请求 → 首屏/游标页 → 核对代次与游标 → 合并；账号变化单独使整组状态失效。
- 声纹：在事务中停止任务、撤销模板并登记清理意图 → 提交 → 文件清理 → 可重复补偿；旧 worker 写入前重新验证成员和修订。
- 报告：页面或 Agent → 统一业务授权/版本/影响预览 → 用户确认 → 共用删除或重试用例。只读投影不因管理权限扩大。
- 查询：稳定筛选与授权范围 → SQL 聚合和 keyset 分页 → DTO。共享读锁、排他写锁使用同一公司锁标识，显式定义允许共享的路由及调用链，不做锁升级。
- 资源：公共固定权重 → 公司镜像/桌面冻结输入 → 现有运行时路径；用户缓存不变。

保持现有报告重试请求兼容；新前端明确采用最新配置，服务端强制执行报告策略，不能只删掉一个按钮。旧统计接口输出形状保持，查询实现迁移不改变数值含义。

## 验证计划

这是跨 Web/桌面/服务端并涉及认证、持久化及构建路径的 S3 实施；文档维护按 S0 检查。

| 范围 | 验证重点 |
| --- | --- |
| 真实 React DOM | 延迟保存/失败、关闭重开、切账号、分页乱序、重试反馈；使用现有 Vitest 加局部 DOM 环境，只新增必要开发依赖 |
| 服务端 | 并发限流、撤权与读写顺序、声纹大输出/超限/取消、清理失败重试、报告管理权限矩阵、最新配置与幂等 |
| SQL 与性能 | 固定小集结果等价；较大测试集分页稳定、无 N+1/全量实体装载；记录同环境 p50/p95、查询数和锁等待，不设易抖动的 CI 耗时阈值 |
| 桌面契约 | 40/41/100/超限、emoji、旧文字数据、错误白名单；不调用模型即可覆盖读取和传输边界 |
| 资源与构建 | 权重移动前后哈希及许可一致；开发、冻结、容器三种定位；定向检查 Windows 路径，不能冒充 Windows 实机通过 |
| 界面 | Web 全部主路由与主要空/有数据/失败状态；1440×900、390×844、浅/深色；Electron 常用/最小支持窗口、播放和说话人折叠前后 |

阶段完成后运行定向检查；集成完毕对最终版本执行一次：

```sh
npm run test:server
npm run test:web
npm test
npm run typecheck:web
npm run typecheck
npm run lint
npm run format:check
npm run build:web
npm run build
```

`npm run build:core` 在资源路径迁移完成后执行一次；公司镜像资源层做针对性构建/定位验证。完整安装卸载、真实模型下载/推理与双平台发行不默认重跑，不能用平台未执行替代失败结果。

改过的源码先按现有格式器整理。最终检查之后代码未变不重复执行；若发现问题，只重跑受影响项。新增迁移在专用测试库验证，不自动更新用户日常库。UI 验证使用日常开发启动命令，不改生产配置；破坏性回归不指向日常业务数据。

## 风险与完成条件

- 共享读锁不能隐含升级为排他锁，权限撤销必须有清晰的事务先后；不牺牲权限换吞吐。
- 报告最新模型策略不能丢失用户修改或重放已确认操作；变更配置后旧检查结果应失效。
- 账号删除和声纹文件清理不能依赖一个请求永远成功，必须验证回滚与重启后补偿。
- 权重 Git 移动保留单份实体，构建消费者一次更新；不删除原路径后遗留脚本指向不存在的资源。
- 独立验收按四个维度及 R1～R9 分别给结果；截图、复现和性能数据放 `artifacts/`。必要验证通过且具体问题关闭后停止，不为提高评分继续扩展需求。
