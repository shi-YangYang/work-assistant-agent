# 问题清单

以下保留原审计发现；用户授权的修补已完成，并遵守尽量不增加 Agent 处理耗时的约束。当前结论见 [修复报告](repair-report.md)与[修复验收](repair-acceptance.md)，不将原始失败覆盖为通过。

以下是原审计交付时的问题汇总。当时产品源码和提示词未改动，测试脚手架纠正不等于产品修复。原结论对应基线 `0fd76fed8400d064d2585c4e753d542343eb864f`，不将小样本当作总体准确率。

## 优先处理：产品行为与架构

### B68-UI-01 · P2 · 新会话过渡期间的草稿归属错误

- 复现：登录后 `/assistant` 正在恢复旧会话，立即点击“新会话”；URL 变为 `/assistant?new=1` 后立即输入，再断网并按 Enter。
- 预期：点击新会话后输入归新会话；未就绪时不能悄悄存进旧会话。
- 实际：新会话输入变空，没有发送消息请求；恢复网络仍为空。后退到旧会话能找到原草稿，再前进新会话仍为空。
- 影响：快速 SPA 切换与输入的竞争条件。**没有永久丢失的证据**；稳定旧会话或直接打开新会话后的离线发送均能保留草稿。
- 建议：把路由目标与草稿身份同步切换，验证切换过程中输入、发送和恢复的归属，不清空所有草稿作为规避。
- 证据：[操作轨迹](../../artifacts/spec068/20261013-0fd76fe/browser/inspection-offline-route/observations.json)、[新会话截图](../../artifacts/spec068/20261013-0fd76fe/browser/inspection-offline-route/new-click-offline.png)、[针对性复验](../../artifacts/spec068/20261013-0fd76fe/browser/inspection-offline-spa/observations.json)。

### B068-STATE-01 · P2 · 报告成功后仍残留旧失败状态

- 复现：员工 high 模式请求本周周报，模型先给出错误来源参数，再纠正并成功生成；读取原消息的公开 API 状态。
- 预期：同一生成任务已成功，已纠正的错误不再列为待完成事项。
- 实际：报告、操作回执和生成任务成功，原消息的 `taskOutcome` 仍为 `partial`，`remaining` 保留旧来源拒绝。报告仅一份，无重复写入。
- 根因：`tasks/feedback/outcomes.py` 将 `source_tokens` 纳入失败身份；成功调用去掉来源参数后身份不同，旧阻断未被收敛。
- 建议：精确关联同一报告生成意图的纠错与成功回执，同时保留其他真正未完成项；不能删除授权校验或一律把状态改成功。
- 证据：[最终公开消息](../../artifacts/spec068/20261013-0fd76fe/backend/real-owned/J06-final-message.json)、[结果身份](../../artifacts/spec068/20261013-0fd76fe/backend/real-owned/J06-final-outcomes.json)、[操作记录](../../artifacts/spec068/20261013-0fd76fe/backend/real-owned/J06-actions.json)。

### B68-UI-02 · P2 · 图片回复正文出现冗长内部文件路径

- 复现：打开已保存的四图任务 B68-08，在 390px 手机视口查看完整回复。
- 预期：图片说明、缩略图及一次任务的查看入口清楚可读。
- 实际：正文直接展示四条 `/api/v1/deliverables/.../files/...revision=1`，每条在手机上占多行，图片前出现大段技术路径。
- 影响：真实模型输出与前端展示交界的体验问题；**不是密钥泄露或越权证据**。图片实际下载、预览、数量和权限未因此失败。
- 建议：将实际成果引用转成已有附件／图集呈现，避免把内部路由当正文；不要为了格式增加一次模型核对。
- 证据：[真实回复](../../artifacts/spec068/20261013-0fd76fe/browser/real-owned/B68-08/result.json)、[手机截图](../../artifacts/spec068/20261013-0fd76fe/browser/inspection/images-390.png)。

### B068-ARCH-01 · P2 · 工作正文模块循环依赖

- 复现：`tests/server/test_architecture.py::test_dependencies_are_acyclic_and_do_not_import_entrypoints`；独占数据库下仍失败。
- 实际：`work.content.checklist → work.content.document → checklist`，两个反向引用均在局部函数中。
- 影响：架构门禁失败，模块维护和后续改动风险增大；本轮**没有据此证明用户运行时崩溃**。
- 建议：抽出两方共用的文档／清单基础转换职责，解除环路；复验对应正文与清单行为。
- 证据：[独占环境日志](../../artifacts/spec068/20261013-0fd76fe/backend/server-owned/affected-first/server.log)、[去重结果](../../artifacts/spec068/20261013-0fd76fe/backend/server-reconciled.json)。

## 工具调用效率：有界纠错，未发现无进展循环

| 编号 | 观察与影响 | 调用与实际副作用 | 后续建议 |
| --- | --- | --- | --- |
| B68-AG-01（同 B068-OBS-02） | 四图任务先拆为四个默认 operation 单图调用，冲突后才改批量；可见总耗时 214.311 秒，首图 73.842 秒 | 4 次主模型调用、5 次图片工具请求，3 次冲突被拒；最后复用首图补齐。4 条成功图片记录、4 条用量、4 个唯一 provider request ID、4 份文件 | 优先核对批量工具说明与默认 operation 交互，减少不必要纠错；不能通过放松幂等保护解决 |
| B068-OBS-01 | 周报第一轮耗时 149.33 秒，生成参数多次试错 | 第一轮 12 次主模型调用、11 次工具调用；其中 5 次 `generate_report`：2 次字段错误、2 次来源错误、1 次成功。仅生成一份报告 | 用该原始失败轨迹补定向复现，精简参数契约或纠错提示；与上面的最终状态缺陷分别处理 |

这些任务最后恢复成功，不能称作无限循环，也没有重复生成／重复业务写入证据。没有核对服务商账单，不能据本地记录保证没有任何额外计费。图片证据见[调用轨迹](../../artifacts/spec068/20261013-0fd76fe/backend/browser-owned/B68-08-trace.json)及[数据库记录](../../artifacts/spec068/20261013-0fd76fe/backend/browser-owned/B68-08-database.json)；报告证据见[J06 轨迹](../../artifacts/spec068/20261013-0fd76fe/backend/real-owned/J06-trace.json)。

## 测试代码与门禁

这五项会影响自动验证，但目前不能据此认定真实用户功能失败。复现基线为 `0fd76fed8400d064d2585c4e753d542343eb864f`。

| 编号 | 级别 | 问题与影响 | 最小复现 | 建议 |
| --- | --- | --- | --- | --- |
| WEB-CHECK-001 | P2 | 消息发送离页用例的 Workspace mock 缺少 `identity`，读取 `identity.company` 即异常，尚未到达发送行为断言 | `npm run test:web -- tests/web/assistant/message-submission.test.ts`；`remembers the accepted conversation when navigating away during submission` | 补齐当前身份契约，再核对离页后的会话归属 |
| WEB-CHECK-002 | P2 | 模型服务保存用例仍查找已删除的“保存并设置用途”；当前按钮为“保存服务” | `npm run test:web -- tests/web/navigation/component-composition.test.ts`；服务保存用例 | 按现有保存服务、用途分配行为重写预期，不恢复旧按钮 |
| WEB-CHECK-003 | P2 | 同文件的输入栏静态渲染用例没有 `window`；新增移动端 Hook 在初始化时读取视口，导致 Node 环境抛错 | 上述命令；消息输入栏静态渲染用例 | 使用匹配浏览器组件的测试环境；项目未承诺 SSR，不能直接归为用户渲染故障 |
| WEB-CHECK-004 | P2 | 输入栏用例依赖旧父节点结构；移动面板拆分后旧 DOM 分组断言失效 | `npm run test:web -- tests/web/dom/assistant/assistant-interactions.test.tsx`；toolbar groups 用例 | 验证控件可达性、实际布局和禁用行为，避免以旧父节点代替语义 |
| WEB-CHECK-005 | P2 | 通知已读测试给 `getByRole` 传入 `ByRoleOptions` 不支持的 `exact` 字段，阻塞 Web 类型检查 | `npm run typecheck:web`；`tests/web/dom/notifications/notifications.test.tsx:129` | 修正测试查询参数；本轮通知 DOM 用例运行通过 |

首轮四个运行失败和一个类型错误均保留，未重跑到绿。详细预期、实际结果、源码位置和证据见 [确定性检查问题记录](../../artifacts/spec068/20261013-0fd76fe/checks/issues.json)、[运行日志](../../artifacts/spec068/20261013-0fd76fe/checks/test-web.log)和[类型检查日志](../../artifacts/spec068/20261013-0fd76fe/checks/typecheck-web.log)。

另有四项后端测试维护问题，均未修改原断言：

| 编号 | 级别 | 失败原因与影响 | 建议 |
| --- | --- | --- | --- |
| B068-TEST-01 | P2 | 公告和图片生成各有 `test_migration.py`，默认 pytest 导入发生同名模块冲突，标准入口收集失败 | 统一测试导入方式或包边界；本次仅以 importlib 和显式模块路径继续审计，原错误保留 |
| B068-TEST-02 | P3 | 未登录路由测试固定预期 73，当前为 74；实际鉴权返回均为 401 | 从当前注册清单断言覆盖，避免固定总数成为过期约束 |
| B068-TEST-03 | P3 | 图片配置测试仍要求旧 `report` 用途返回 422；用途合并后旧字段忽略，实际 200 | 按已确认的统一用途契约验证，有效 assistant 模型能力仍需严格检查 |
| B068-TEST-04 | P3 | 旧 worker 恢复探针仅允许 Spec044／054，拒绝本轮精确归属标识 | 增加严格的本轮归属支持，不放宽为任意环境；新审计的实际 SIGKILL／租约恢复已过，但旧探针的所有阶段不能算通过 |

具体测试节点和首轮证据见[后端问题原表](../../artifacts/spec068/20261013-0fd76fe/backend/issues.json)。

## 待定位与体验建议

- **B68-TST-01 · P3 · 待定位**：用量表 UI-11 在连续视口／主题切换后，键盘横向滚动断言未稳定成立。第一次焦点导致偏移 9px，界面显示“左右滑动”其实正确；后续 blur 后 ArrowRight 又未移动，而独立直接观察可以移动。保留失败，尚不能断言产品故障，也未删除有效断言。证据：[直接观察](../../artifacts/spec068/20261013-0fd76fe/browser/inspection/observations.json)、[后续失败](../../artifacts/spec068/20261013-0fd76fe/browser/harness-v4-chromium/results.json)。
- **B68-UX-01 · P3 · 产品建议**：四图任务点开一张后预览为 `1/1`，不能切相邻图片。当前要求仅有点击放大，因此不判缺陷；可以后续决定是否支持同一图集切换。证据：[手机预览](../../artifacts/spec068/20261013-0fd76fe/browser/inspection/image-preview-mobile.png)。
- **模型内容观察**：J02 对元组可哈希的表述过度概括，并无依据声称 set 转换后的顺序碰巧相同；J03 日期间隔旁支文字有算术瑕疵；均未变成错误业务写入。单列记录，不据此添加逐条模型复核或宣称答案全部正确。

## 样本限制

- J05 第三轮“保留 10 月 12 日”与前两轮已更新为 10 月 18 日冲突，该日期子断言无有效结论；一个工作、三个版本和状态变化可以核验。未把歧义样本当产品失败或完整通过。
- J15 冻结文字预期沿用了另一份材料；实际附件是 A01/A02/A03，总额 300。按原始实际文件离线复核原回复正确，保留原错误预期，没有重新调用模型取有利结果。
- 真机麦克风／软键盘／钉钉 WebView、真实企业 OAuth 与声纹外部录音夹具等缺口详见报告，均不能算通过。

## 环境事件

- 首轮服务端与浏览器并行使用不同 schema，但仍共享同一 PostgreSQL 进程，发生连接耗尽。相关失败作为受污染结果保留，不能直接计为产品缺陷；后续改用本轮独占数据库，服务端故障／负载与浏览器／真实模型分开。
- 独立 Vite 端口仍复用了日常开发缓存，出现 `504 Outdated Optimize Dep`。仅隔离测试缓存后，复验受影响场景；未调整产品加载逻辑。
- 默认 pytest 收集遇到两个同名 `test_migration.py` 模块冲突。后续命令使用独立导入模式并补正确测试路径，原始收集错误保留，不能将未收集用例算作通过。

- 首轮备份演练使用不处理退出信号的 `sleep` 容器替身，导致脚手架超时。短对照确认后仅增加替身 init，原生产脚本未改，受阻步骤续跑通过；不是备份产品缺陷。
- 所有本轮拥有的测试服务、schema、容器及密钥副本已按 manifest 清理；日常服务没有被停止或改配置。首轮共享连接耗尽的影响仍如实保留，不能倒推为整个执行期完全隔离。

建议先修复四项产品／架构问题及阻塞验证的测试错误，再针对两条真实低效轨迹做小范围调整和对照。未取得用户修复指令前，仅交付问题和证据。
