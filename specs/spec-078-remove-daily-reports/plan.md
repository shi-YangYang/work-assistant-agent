# 实施方案：移除日报功能

## 前置条件

按 [Spec](spec.md) 直接删除历史日报及关联业务快照，使用隔离测试库开发和验证，未授权生产清理。所有耦合修改交由一个 high 实施 Agent 串行处理，随后由新的 high 独立验收 Agent 验收。

## 修改顺序与数据流

1. **统一周报契约**：公开报告类型、工具参数及缺省值限定 weekly；入口和共享命令拒绝明确 daily，不能依赖 `kind != daily` 就当周报的旧周期逻辑。保留共享路径和操作名称。
2. **关闭旧执行入口**：查询、详情／来源、修改／提交／候选、待办准备、业务确认及回执复用按统一范围收口；授权验证先于不可用结果。检查 generic report 查询，不能只搜索 daily 字面量。
3. **迁移与任务停用**：直接清除日报正文、候选、修订、关联快照和 daily 配置、历史安排、待办、提醒；只保留无正文的必要失效／审计元数据。运行中的任务在启动、恢复和落盘处拒绝日报；旧等待得到明确终态。新调度同时过滤当前周期和历史补偿路径。
4. **页面简化**：我的报告保留周报；团队只保留周报日历模式与统计；设置去掉日报；通知与助手卡片不能展示可执行日报操作；导航、快捷建议、模型用途说明同步。
5. **替换有效样本**：保留日报拒绝与迁移用例；将检验共享权限、来源、幂等和任务恢复的日报 fixture 改为周报，避免直接删掉原有保护测试。更新仍使用的验收入口和原型文案，历史日志与历史 Spec 不重写。
6. **相关验证与独立验收**：只覆盖实际改动的子系统，复用已有测试；结果与限制写入实施／验收记录，不追加真实模型回合或全量矩阵。

目标调用路径：页面／助手 → weekly 契约 → 共享报告命令与权限 → 工作进展来源 → 周报任务 → 版本／租约校验 → 周报／待办／回执。所有旧日报路径在相应边界结束，不进入周报链路冒充成功。

## 预计改动目录树

标记 `[改]` 为原位修改或精简日报分支，`[增]` 为新增；共享目录和模块均保留。不预设整文件删除，确认只服务日报且无周报引用后才删除相应私有实现。

```text
apps/
├── web/src/
│   ├── app/layout/navigation-items.ts                 [改] 导航说明
│   └── features/
│       ├── reports/api/requests.ts                    [改] 默认周报请求
│       ├── reports/components/{overview,detail,notifications}/
│       │                                               [改] 周报页面、操作及提醒
│       ├── team/components/{TeamWorkspace,TeamResults}.tsx
│       │                                               [改] 周报入口与结果
│       ├── team/components/report-period/              [改] 精简按天模式，保留周选择
│       ├── settings/{api,utils,components/rules}/      [改] 日报配置及校验移除
│       ├── assistant/components/composer/AssistantSuggestions.tsx
│       │                                               [改] 快捷建议
│       ├── assistant/components/interactions/BusinessActionCard.tsx
│       │                                               [改] 旧日报卡片失效展示
│       └── model-services/components/Routing.tsx       [改] 模型用途说明
└── server/app/
    ├── modules/reports/
    │   ├── {schemas,periods,router,queries,commands,service}.py
    │   │                                               [改] 周报契约及读写边界
    │   ├── scheduling/                                 [改] 周报规则、待办和通知
    │   └── retirement.py                               [增] 日报动作及任务存活校验
    ├── modules/members/models.py                       [改] 公司默认规则
    ├── modules/team/                                   [改] 查询、统计和来源访问
    ├── modules/operations/                             [改] 日报动作、回执与恢复失效
    ├── security/{ownership,access}.py                  [改] 复用所属及来源校验收口
    ├── agent/{prompts,actions,tools/business,runtime/progress}/
    │                                                   [改] 工具、能力、执行与进度
    ├── tasks/{maintenance,runtime,feedback}/            [改] 调度、任务恢复及等待终态
    └── migrations/versions/0034_remove_daily_reports.py [增] 清除历史日报及关联数据
packages/api-contracts/src/index.ts                      [改] 周报与规则契约
tests/
├── server/{modules/reports,modules/team,agent,tasks,_support}/
│                                                       [改] 相关回归与周报 fixture
├── server/modules/reports/test_daily_report_retirement.py
│                                                       [增] 旧日报入口与迁移边界
└── web/{dom/reports,dom/team,dom/settings,resources}/    [改] 页面及规则检查
scripts/{company/web-acceptance,benchmarks}/             [改] 仍使用的日报调用与 fixture
docs/{setup.md,design/prototype/src/pages.tsx}            [改] 当前能力说明及原型
specs/
├── README.md                                           [改] Spec 索引
└── spec-078-remove-daily-reports/
    ├── spec.md                                         [增] 删除范围和历史日报清理策略
    ├── plan.md                                         [增] 实施与验证边界
    ├── implementation.md                               [增] 实施结果、验证证据及限制
    ├── acceptance.md                                   [增] 独立验收结论及首轮失败证据
    └── rework.md                                       [增] 旧日报等待状态返工范围
```

任务恢复与查询的具体文件以现有调用链为准；迁移序号在实施前再次核对。上树是预计涉及范围，不要求为每一项制造无必要的改动。

## 迁移策略与风险

- **直接清除**：先识别日报及所有关联对象，再清理通知／待办／安排外键、任务／操作／幂等回执及结构化业务快照，最后删除日报修订与主记录。清理 company.rules.daily，保留周报配置与共用员工资格记录。必要失效标记只含 ID、状态、错误及审计元数据，不含日报正文。
- **保留边界**：原始工作、工作修订、消息、附件、普通聊天文字和周报均保留。不调用通用用户／聊天删除流程，不按文本关键词清除消息；关联上下文只定向失效。
- **旧进程与回滚**：交付说明先停止旧 API／worker 写入、备份、执行迁移、再启新 API／worker；本次不执行生产部署或真实用户库清理。破坏性迁移不能以空 downgrade 伪装可逆；正文恢复依赖备份。
- **旧客户端与历史卡片**：参数 daily 明确拒绝；旧日报对象不可用，历史名称不改为周报。已有完整聊天文字不做全局删除。
- **周报回归**：本次删除不改变工作事实来源或报告生成算法；确认移除 daily 后仍保留原周报周期、时区、版本、幂等与租约语义。

## 验证计划与停止条件

Spec 文档修改按 S0：检查需求一致性、路径及 diff，不为文档运行测试或构建。

后续业务实施 S3，原因是公开契约、持久化迁移及后台任务的交互变化。必要验证限定为：

1. 后端报告／规则／团队／助手动作模块：weekly 正常；daily 参数、旧 ID、待办准备、来源访问及旧回执均不可继续使用；租户与角色权限不放宽。
2. 迁移与任务恢复：混合日报／周报数据、已提交／未提交／已删除日报、活动安排、提醒及未完成任务；迁移后无新增日报或迟到写回，周报不受损，降级按数据方案约定。
3. 周报回归：生成、修改／候选采用、提交、来源版本、重复生成、删除后重建和调度；用受控模型，不调用真实付费模型。
4. 前端相关 DOM／资源测试及共享类型检查：日报入口移除、默认周报、规则保存、团队周选择、旧卡片不可操作。只因实际契约联动执行必要类型检查，不默认完整打包。
5. 对移除日报后确实无意义的专属成功用例删除或替换；不得删掉仍保护周报的共享测试。历史性能矩阵不重跑，历史验收证据不改写。

检查通过且没有与本次修改直接相关的问题后停止。实施前不运行这些检查，不提前写验收 PASS。
