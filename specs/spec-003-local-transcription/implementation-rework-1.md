# Implementation Report — Spec 003 · Rework 1

## Summary

按 [首轮独立验收](acceptance-round-1.md) 和 [返工目标](rework.md) 修复暂停与已选音频块的竞态。新的实施 Agent 未参与首轮业务实现，不负责最终验收。未修改模型、解码参数、分块边界算法或真实参考样本。

暂停、任务继续、块认领和结果提交现在使用同一个短控制锁协调。每次暂停取消当前调度代的令牌；继续创建新令牌，旧迭代即使随后返回文字或抛出错误，也不能改变新任务的状态或提交结果。读取 WAV 与模型加载 / 推理期间均不持有控制锁。

## Files Changed

- `src/python/paa_core/transcription.py`：短控制锁、调度代有效性校验、暂停 / 继续 / 退出的令牌失效；将读取末尾时的完成状态写入移到认领边界，保持读窗阶段无任务状态副作用。
- `src/python/paa_core/asr_worker.py`：可选的 `InferenceToken` 贯穿加载和推理；令牌取消与私有管道发送共用短锁，阻止已取消的请求在认领后再次发送。等待 worker 结果时按既有 100 ms 轮询检查取消，有界清理进程。
- `tests/python/test_transcription.py`：新增 4 项事件同步回归，测试替身支持可选令牌。
- 本报告。没有改动其他业务、配置、Spec 决策或主 Agent 所有的文档。

## Important Decisions

单次 Event 检查无法消除检查与状态写入之间的竞态；仅在提交时检查暂停状态，也无法阻止暂停后立即继续复活旧结果。因此使用不可复用的每代取消令牌，并分别在持久状态边界与 worker 请求发送边界协调。

取消不等待整个加载或推理。令牌锁只覆盖取消标记 / 有界请求发送，控制锁只覆盖状态和检查点操作。原有 worker 全局串行锁仍管理进程；Provider 与持久化 schema 未变化。

## Tests

验证级别为 **S2**：调度器、工作进程取消和检查点生命周期的局部交互。扩展到 worker 定向检查的具体原因是取消发生在认领后、请求发送前时仍必须阻止新推理；不扩大到无关功能。

### 修复前的确定性复现

先加入并执行两项回归，原实现均失败，合计 3 个断言失败：

- 通过 `threading.Event` 固定读窗返回前的间隙；暂停后释放，调度器进入下次空闲再检查，实际状态为 `draining`，预期为 `paused`。
- 通过事件固定推理返回前的间隙；暂停后立即继续，再释放旧迭代。旧结果与旧异常两种分支都使新推理无法开始。

上述同步点不依赖 sleep 碰撞线程时序。

### 修复后的相关 Python 检查

以下 9 项通过，耗时 3.160 秒：

```sh
PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest \
  test_transcription.TranscriptionTests.test_pause_after_reading_window_cannot_restart_the_selected_block \
  test_transcription.TranscriptionTests.test_immediate_continue_discards_the_previous_iteration_result_or_failure \
  test_transcription.TranscriptionTests.test_cancelled_worker_generation_cannot_dispatch_after_a_continue \
  test_transcription.TranscriptionTests.test_cancelling_running_worker_is_prompt_and_reclaims_the_child \
  test_transcription.TranscriptionTests.test_slow_worker_does_not_block_recording_controls_or_frame_growth \
  test_transcription.TranscriptionTests.test_worker_crash_and_timeout_are_bounded_and_leave_no_child \
  test_transcription.TranscriptionTests.test_failure_keeps_checkpoint_and_retries_without_new_task \
  test_transcription.TranscriptionTests.test_tail_restart_resume_and_completed_start_never_duplicate \
  test_transcription.TranscriptionTests.test_corrupt_model_is_not_ready_and_download_cancel_and_retry_are_atomic -v
```

新增回归验证：暂停后保持 paused / activity=false、旧块没有调用 worker；继续后只提交一次；旧迭代的文字与错误均不能覆盖新代；已取消的 worker 请求没有向管道发送 infer，新令牌仍能正常推理；已发送的慢推理取消调用在 100 ms 内返回，子进程在 1 秒等待上限内被回收。测试使用跨平台 Python Event 和真实 spawn 子进程，不依赖 POSIX shim 或物理麦克风。以上命令写法适用于本机 macOS，新增测试由既有 unittest discovery 纳入 Windows CI。

### 真实 worker / Electron 定向检查

- `npm run test:asr`：**通过**。修改 worker 调用边界后，使用原固定 4.281 秒公开人声和本地 small 模型验证真实 spawn 推理，worker 禁止 socket 联网。实际推理 1.434 秒；输出与此前一致，完成帧位置、时间范围、幂等断言通过。该命令同时创建后续 Electron 所需的新历史 / 待恢复隔离会议。原报告保存为 ignored `artifacts/spec003/real-asr-before-rework-1.json`，本次结果为 `artifacts/spec003/real-asr.json`。
- `PAA_REAL_ASR_SMOKE=1 npx playwright test tests/smoke/transcription.spec.ts`：**1 项通过**，14.3 秒。实际 Electron 完成模型就绪、历史补转写、持久文字、片段定位、关闭确认取消、保存进度退出、重启 paused 和继续完成。Python 核心从源码运行，未为本次纯 Python 修改重复构建 renderer。

必要检查通过后停止验证。未重复两分钟中文质量 / 性能基准、物理麦克风回采、原有 6 项 smoke、无关 TS / lint / format / build 或完整 Python 套件。

## Known Limitations

- 本轮本机环境为 macOS ARM64 / Python 3.12.14；没有将本机结果称为 Windows 通过。
- 远端双平台 CI 与新的独立验收由协调 Agent 继续完成，本报告不是最终 PASS。
- worker 请求发送临界区只传输一个有界音频窗口；模型加载 / 推理等待在该临界区外。数据库忙等待仍受现有 Repository 超时约束，没有改变存储策略。
- 真实中文误识别、设备噪声等已记录的产品限制保持不变；此次仅修复生命周期并发问题。

## Remaining Questions

没有新增产品决策或代码返工待办。已结束本轮测试进程，业务修改冻结，可由协调 Agent 进行候选提交、对应双平台 CI 和新的独立验收。本 Agent 未 commit / push，未创建子 Agent。
