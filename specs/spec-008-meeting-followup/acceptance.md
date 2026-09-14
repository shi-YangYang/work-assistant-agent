# Acceptance — Spec 008

## Result

**PASS · 2026-09-12，独立工程验收通过。** 新的独立验收 Agent 已关闭第 4 项输入版本缺陷；首轮三项沿用上一位独立验收 Agent 的关闭结论。本轮只审查输入修订的恢复与写入边界，复用已通过的直接相关检查，没有修改业务代码或重复运行测试。

此结论覆盖当前工程实现与受控验证。真实外部服务、手机实机和生产部署仍有下述未验证边界，不能据此宣称全部外部验收完成。未提交、推送或触发远端 CI。

## Spec Coverage

- R1～R7 的既有覆盖沿用前两轮独立审查与[实施证据](implementation.md)：服务端身份与材料隔离、人工确认与发布、可追溯进展、报告快照／修订与调度、Web 页面和交互均已形成；静态原型不作为业务验收依据。
- 第 4 项修复满足 R2／R3 的文字纠正和恢复要求。[worker.py](../../src/python/paa_server/worker.py) 将实际消费的转写 revision 放入可信 RunContext；[harness.py](../../src/python/paa_server/agent/harness.py) 的消息 checkpoint 绑定公司／员工／job／revision／输入 SHA-256。纠正后启用新输入，旧 pending tools 和旧完成结果不再恢复；未变输入继续 pending steps 或直接复用完成答复。
- 工具和最终答复事务通过 `lease` 按 Job → Message 顺序加锁并校验源 revision，锁保持到写入结束。转写 PATCH 只锁 Message，不反向申请 Job 锁；处理中已提交的纠正会阻止迟到写入，并留下可理解的失败和手动重试入口。
- ASR 返回时在同一消息锁事务选择生效文字与 revision；途中人工纠正优先，迟到 ASR 不覆盖新文字，也不把新版本与旧文字组合。已落库的原始建议、音频、转写历史与人工确认修订保留；业务工具仍按同 job／内容幂等。
- 报告保持公司／员工／job 独立 checkpoint 和本 job 的已确认修订快照，未引入消息输入分支；授权历史边界和上下文上限保持。本次未改 API、schema 或依赖。

## Tests

本轮独立阅读实际实现与测试断言，复用输入返工 Agent 已执行的命令：

`node scripts/company.mjs test tests/server/test_transcript_recovery.py tests/server/test_recovery.py tests/server/test_boundaries.py::test_long_conversation_is_summarized_before_hard_context_limit`

**11 项通过（4.38 秒）**，其后业务代码未再修改。新增 7 项在独立 PostgreSQL 测试库使用实际 Deep Agents／checkpoint 和转写 PATCH／retry API，覆盖模型前失败、旧 pending tool、旧 completed checkpoint 后纠正重试、修订前后同输入工具幂等／完成复用、工具写入与最终答复前的纠正、ASR 途中纠正；另 4 项覆盖本次改动直接涉及的消息／报告 job 隔离、历史和长上下文。测试断言核对模型实际收到新文字、旧结果拒写、保留原始材料及已确认内容，非仅检查任务成功状态。

首轮返工已有 4 项恢复／历史／长上下文、1 项受影响主流程、5 项受控媒体及 1 项编辑映射通过；相关 Web 类型／lint 通过，修改的前端源码已格式化。原有 11 项服务端、3 项 Web、迁移、依赖和初轮普通构建结果仍按各自执行时点记录，不能称为最终源码重新构建结果；本次没有重跑这些已通过检查。

协调 Agent 已在正常 Web 环境走通员工发送 → 确认进展 → 报告提交到第 3 版 → 管理员只读查看提交内容、来源与原始建议；检查了汇报规则权限、360 px 布局、900 px 菜单与浅深主题。Electron 直接使用 `npm run dev` 和默认用户数据，共享主题与四条既有会议记录正常。最终 API／worker 已由协调 Agent 重启加载。本轮验收未重新操作 GUI、麦克风或真实服务。

## Issues — 失败与关闭记录

以下历史保留首次 FAIL 的事实与修复依据；前两轮完整原记录另存于本地忽略产物[验收原记录](../../artifacts/spec008/review/acceptance-before-input-fix.md)。本节为持续保存的验收摘要。

1. **P1，跨 job 恢复错误：首次独立验收 FAIL。** A 失败、B 在工具前失败后重试 A，实际出现 `A_state=succeeded`，A 草稿标题为“仅属于第二条 B 的事项”；B 仍失败且无草稿。原因是同员工共享可执行 checkpoint。首轮返工改为公司／员工／job 独占状态，从授权业务记录重建有界历史；前次独立复验已关闭。本次 4 项相关恢复检查继续覆盖消息与同一报告的不同 job 隔离。
2. **P1，麦克风权限迟到：首次独立验收 FAIL。** 控制流审查发现等待权限时切页，卸载后返回的流仍可启动录音；重复申请还会覆盖流引用。未触发用户真实麦克风复现。首轮返工以请求代次、申请防重入、卸载失效及 session 自有流清理解决，5 项受控媒体检查覆盖迟到许可与失败清理；页面函数式草稿更新保留后来的输入。前次独立复验已关闭，本轮不重复验收。
3. **P2，无法解除工作关联：首次独立验收 FAIL。** `stored?.workId ?? draft.workId` 把明确选择的新事项 null 回退为旧 workId，普通保存及冲突恢复不能表达解除关联。首轮返工区分未缓存与明确 null，1 项编辑映射检查与真实页面调用一致；前次独立复验已关闭，本轮不重复验收。
4. **P1，纠正后仍恢复旧输入：第二次独立验收 FAIL，本次关闭。** 专用测试库的实际故障探针按“项目已全部完成”转写 → 模型前失败 → PATCH 为“项目尚未完成，仅初稿完成”（revision 2）→ retry 复现：数据库保留新转写、任务 succeeded，但 `retryModelSawOld=true`、`retryModelSawCorrection=false`，新增草稿仍为旧文字。原因是发现本 job checkpoint 后直接 `ainvoke(None)`，丢弃 worker 新输入。本次以输入版本及摘要选择 checkpoint，并在 ASR／工具／答复事务校验版本；上述 7 项新增场景直接覆盖旧失败路径和迟到写入。未变输入的恢复、幂等、已完成答复复用与人工修订保留同时通过。

两次历史探针均使用受控账号、固定模型和专用 `paa_company_test` 库，结束后清理各自样本；没有调用真实模型／ASR或接触真实用户材料。首次报告空白与 HMR 状态有关，稳定刷新后已确认持久化，不作为本次未解决缺陷。

## Regression Risks / External Limits

- 真实图文模型／ASR API 尚未授权联调。固定响应实际经过工具循环与 checkpoint，图片规范化和音频解码有真实处理证据，但不能代表服务商兼容性、图像理解或识别质量通过。
- iOS／Android 实机麦克风与移动键盘、锁屏行为、有效公网 HTTPS、2 核 2 GB 容量及生产备份恢复尚未实测；桌面窄屏视口不能替代这些结果。
- Docker 服务镜像在获取 Python 基础镜像的 Docker Hub 鉴权阶段遇网络超时，后续镜像构建和 Linux 完整部署未完成。Compose 与备份脚本语法通过不代表部署或恢复通过。
- 没有读取或迁移 Electron 真实密钥／会议资料，没有开通云资源。本轮无提交、推送和远端 CI 结果，旧提交 CI 不代表本次源码。

## Required Rework

无未关闭的本次工程缺陷。上述外部条件在授权联调或部署前补充验证；无需为本次工程 PASS 重复已通过的本地检查。
