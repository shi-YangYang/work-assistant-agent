# Implementation Report

## Summary

- 当前用户跨会话活动摘要接入 Shell；发送／上传后即时显示工作，回执接管不闪回空闲，任务结束或等待人工输入时恢复原头像。
- 宠物工作形象沿用已确认的生成素材与 32 源像素双爪动作；原脸、身体与键盘固定。正式素材不依赖预览目录，白色圆形外观、主题弹窗及空闲眨眼保留。
- 断线显示“状态待同步”；身份切换清空状态。只在规定同步时机读取账号摘要，任务事件复用既有 SSE，无定时查询、自动 POST 或额外模型调用。

## Files Changed

后端与契约：

- `apps/server/app/tasks/router.py`：新增需认证、禁止缓存的 `GET /api/v1/assistant/activity`。
- `apps/server/app/tasks/runtime/conversation_activity.py`：只查询本人有效消息与会话，排除终态、非聊天任务及失效业务权限；管理员无扩大范围。
- `packages/api-contracts/src/index.ts`：`AssistantActivity`、`AssistantActivityJob` 摘要类型。

状态与业务接入：

- `apps/web/src/api/assistant-activity.ts`：账号 store、本地提交令牌、回执／取消／重试版本合并、共享订阅、有限同步与跨标签页通知合并。
- `apps/web/src/api/job-feedback.ts`：有效活动快照可恢复其他消费者仍持有的 403／404 停止连接；新 attempt 清空共享旧错误，仍复用同一 SSE。
- `apps/web/src/hooks/useAssistantActivity.ts`：登录后应用层生命周期与聚合三态订阅。
- `apps/web/src/app/layout/Shell.tsx`：全页面挂载观察。
- `apps/web/src/features/assistant/hooks/composer/useMessageSubmission.ts`：上传／提交生命周期。
- `apps/web/src/features/assistant/hooks/conversation/useAssistantTask.ts`：已接受任务、重试与取消回执。
- `apps/web/src/features/assistant/hooks/conversation/useAssistantInteraction.ts`：回答临时问题后恢复处理的回执。

宠物：

- `packages/ui-web/brand/pet/working.png`、`packages/ui-web/package.json`：正式工作素材和导出。
- `apps/web/src/app/layout/pet/{NoriaPet,PetStage}.{tsx,module.css}`：形象切换与名字下方悬浮状态。
- `apps/web/src/app/layout/pet/NoriaWorkingPet.tsx`：素材预加载、失败后备、可见性／弹窗／减少动态效果的动画生命周期。
- `apps/web/src/app/layout/pet/typing-animation.ts`：已确认的双爪局部网格动画；30fps、204px 物理画布、最多 64 张小帧缓存。

测试：

- `tests/server/modules/conversations/test_conversation_task_state.py`：追加 2 条活动查询与权限测试。
- `tests/web/assistant/assistant-activity.test.ts`：新增 18 条状态、版本、竞争、断线、账号隔离、连接与通知去重测试。
- `tests/web/assistant/job-connection.test.ts`：补充新 attempt 清理旧错误、旧事件隔离及终态不能被重新发现凭据复活的检查。
- `tests/web/dom/shell/assistant-activity.test.tsx`：新增 3 条 StrictMode 冷启动／延迟请求／切账号生命周期测试。
- `tests/web/dom/shell/noria-pet.test.tsx`：工作形象、状态、暂停与失败后备覆盖。
- `tests/web/dom/assistant/assistant-task.test.tsx`：语音上传／回执／转写与失败的全局状态断言；补齐原语音 fixture 缺失的必填 duration。

## Important Decisions

- 摘要响应为 `{ jobs: [{ id, conversationId, targetId, state, stage, attempt, fence, seq, updatedAt }] }`，不返回正文、模型信息或操作参数。
- Store 仅保留任务标量，不将正文 token 放入应用快照；Shell 只因 idle／working／unknown 改变而更新。
- 终态回执可能不含反馈 seq；相同 attempt／fence 复用已知 seq，再比较时间，确保中断确认直接退出工作状态。
- 同一轮发送／任务 hook 的跨标签页通知合并；StrictMode 或网络快速恢复遇到已取消快照时，在旧请求结束后补一轮读取，防止冷启动长期停在空闲。
- 已不可访问的任务保留本地修订号，拒绝撤权／删除之前发起的在途快照；后续新发起的权威快照仍可重新发现任务，新重试回执也可立即接管。
- 403／404 后的共享连接只接受经过活动 store 竞态校验且 attempt／fence 一致的新快照作为恢复依据，再读取一次原反馈接口确认访问权限。普通重连、终态、失效身份和旧版本不能解除停止；恢复仍被拒绝时再次释放活动任务，不自动循环重试。
- 工作素材使用生成图首格，原图其余姿势不参与切换，避免脸型、围巾和键盘逐帧漂移。帧缓存有上限，页面不可见、外观弹窗打开或减少动态效果时停止逐帧渲染。

## Tests

S3 相关子系统验证，无全仓测试／构建、真实模型、用户数据或线上变更。

- 后端：使用专用 `paa_company_test` 数据库，运行 `pytest -q tests/server/modules/conversations/test_conversation_task_state.py -k account_activity`：**2 passed，46 deselected**。
- Web：以下 6 文件分组执行，最终去重 **78 项通过**：
  - `tests/web/assistant/assistant-activity.test.ts`：18。
  - `tests/web/assistant/job-connection.test.ts`：12。
  - `tests/web/dom/shell/noria-pet.test.tsx`：9。
  - `tests/web/dom/shell/assistant-activity.test.tsx`：3。
  - `tests/web/dom/assistant/assistant-task.test.tsx`：20。
  - `tests/web/dom/assistant/assistant-interactions.test.tsx`：16。
- `npm run typecheck:web`：通过。
- 本次修改及新增的 TS／TSX 文件定向 ESLint：通过；修改文件已用项目 Prettier 整理。
- 独立验收发现的 unavailable／在途快照竞争和消息区保留已关闭共享连接的恢复问题，均已加入正式回归：覆盖 403、404、旧快照拒绝、双消费者后续重新发现、再次拒绝无自动请求、原连接迟到事件、新 attempt 清理旧错误。最终返工只运行活动 store 与共享连接两个文件（**30 passed**）及这两个模块／测试文件定向 ESLint（通过），修改文件已格式化、diff 检查通过；未重复其他已通过检查。
- 协调 Agent 的 CUA 浏览器检查：1280×720／390×844 下发送立即工作、跨页持续、succeeded／awaiting_input 恢复空闲、冷刷新恢复、断线待同步、外观弹窗暂停与移动导航可用。截图位于 `artifacts/spec062/`；此记录不替代独立验收。

## Known Limitations

- 其他设备的新任务仅在登录／刷新、标签页可见、恢复网络或同账号其他标签页通知后发现；没有新增账号级实时广播。
- 动作是已确认的局部双爪形变，不是完整 3D 骨骼动作；工作时不叠加新眨眼，空闲继续使用原眨眼。
- 正式 PNG 约 1.8 MB，保留已确认素材原始四格，仅渲染第一格；画布帧缓存最多约 11 MB（204×204×4×64），未增加动画或 3D 依赖。
- 浏览器手机视口不等于 vivo／钉钉真机验收。没有 commit、push、CI 或生产部署。

## Remaining Questions

无待定产品问题；[独立验收](acceptance.md)已通过。
