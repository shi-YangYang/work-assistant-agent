# Implementation Report — Spec 003 · CI Smoke Diagnostics

## Summary

继续处理候选 `9a8dc78` 的[真实 CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34449407056)。Windows 整个 job 已通过；macOS 的 35 项 Python、19 项 TypeScript、真实模型推理与 6 项旧 smoke 已通过，新增转写 smoke 总超时 90 秒，worker teardown 又超时 30 秒。

本轮修正该测试的退出等待与失败清理，并增加阶段证据。尚不能断言远端正文超时的根因已经解决；需要对应新提交的实际 CI 结果。本轮无业务或模型改动，不延长 30 秒转写等待或 90 秒总上限。

## Evidence and Scope

主 Agent 已下载并核对 macOS artifact。`error-context.md` 只有总超时，没有 DOM、断言行或具体调用；唯一转写截图证明第一段历史转写已经完成。远端真实模型报告记录准备 9.680 秒、4.281 秒音频推理 9.707 秒。本机时间无法替代远端时间；不能据此直接判定后面的 17.124 秒恢复一定超出 30 秒。

已确认的测试缺陷：原 `finally` 无条件 `await app.close()`，正文若在有活动转写时失败，会触发产品的真实退出确认。Playwright 当前实现发送 `app.quit()` 后断开主进程调试连接，再等待退出事件；测试没有为这一失败清理处理确认，因此可能掩盖最初的断言错误并使 teardown 持续等待。正文另有未指定等待上限的 close event。

## Files Changed

仅修改 `tests/smoke/transcription.spec.ts` 和本报告：

- 正文正常重启和“保留进度并退出”通过 `BrowserWindow.close()` 触发产品真实退出链路，并等待有 10 秒上限的 close event；不再提前用 `app.close()` 断开调试连接。
- 保留原取消关闭、窗口仍可见、允许关闭、重启 paused、继续至 completed、恢复文字和定位断言。
- 最终清理先为测试桌面明确回答退出确认，再走真实窗口关闭。清理异常时仅回收该测试启动的进程；Windows 使用指定 PID 的 `taskkill /T /F`，macOS 向该进程发送 SIGKILL。回收不是通过条件：正文已失败时保留原错；正文通过而清理失败时测试仍失败。
- 每阶段使用 `test.step`，并将开始、完成、错误及恢复进度写入 `artifacts/spec003/transcription-smoke-stages.json`。现有 CI artifact glob 会保留该文件；即使总超时没有栈，也能定位最后阶段及 processedMs / pendingMs。

没有改变依赖、工作流、产品退出实现、Provider、参考稿或测试 skip，没有为了当前本机通过而放宽断言。

## Tests

本轮为 **S1 测试生命周期局部修复**，只处理具体失败场景。

1. 修改前为重放当前失败场景，用 `npm run test:asr` 生成新隔离会议，然后仅执行 `PAA_REAL_ASR_SMOKE=1 DEBUG=pw:api npx playwright test tests/smoke/transcription.spec.ts`：本机原测试通过 15.1 秒，不能复现远端失败。日志留存 `artifacts/spec003/ci-rework/smoke-before-fix.log`，没有因此宣称远端已解决。
2. 修改后生成一次新 fixture，执行 `PAA_REAL_ASR_SMOKE=1 npx playwright test tests/smoke/transcription.spec.ts`：**1 项通过，15.5 秒**。实际 Electron 完成全部阶段及正常清理。随后将清理错误的重抛移到 finally 之后以满足 ESLint，语义为保留正文错误、单独清理失败仍抛出；没有改变成功路径或重跑模型。
3. `npx eslint tests/smoke/transcription.spec.ts`、`npx prettier --check tests/smoke/transcription.spec.ts`、`git diff --check`：通过。首次定向 lint 发现 `no-unsafe-finally` 后按上述方式修正，不使用 lint 禁用注释。

未重复 2 分钟 CER、物理麦克风、6 项旧 smoke、完整 Python / TypeScript 套件或 build。实际转写 fixture 沿用固定公开音频与真实 small 推理，仅用于为该 smoke 创建未转写 / 可暂停的会议。

## Known Limitations

原远端 artifact 不足以确定正文最初的失败阶段。本轮使退出等待有界并保存更精确的阶段与状态，后续仍须实际跑远端 macOS / Windows，不能把诊断能力交付描述成所有问题已通过。

SIGKILL / taskkill 仅用于失败的隔离测试清理，不进入产品；本机正常 smoke 未走强制清理分支。没有因此声称 Windows 物理麦克风或最低性能配置已验证。

## Remaining Questions

修改冻结，测试进程已结束，可由主 Agent 提交并运行真实 CI。没有新产品决策；未 commit / push、未创建子 Agent，最终验收由独立 Agent 完成。上一轮两项 CI 修复报告保留于 `implementation-ci-rework.md`。
