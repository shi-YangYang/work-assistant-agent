# Implementation Report — Spec 003 · CI Rework

## Summary

新的实施 Agent 修复候选 `d7013c94f87c85f081f158012a8e23613e01fdca` 在[真实双平台 CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34448151461) 暴露的两个测试问题：macOS 慢 worker fixture 依赖输入生成定时速度；Windows 在真实推理断言完成后，输出中文 JSON 时遇到控制台编码错误。本轮没有修改业务代码、ASR 参数、模型、参考稿、依赖或平台 skip。

## Files Changed

- `tests/python/test_transcription.py`：慢推理测试改为按帧供给的合成输入，以及由跨进程 Event 控制的真实 spawn worker；保留并加强原行为断言。
- `tests/python/real_asr_check.py`：stdout JSON 使用 ASCII 转义，UTF-8 结果文件继续保留中文原文。
- 本实施报告。没有修改主 Agent 或验收 Agent 正在维护的文档。

## Important Decisions

### macOS：先明确音频和推理状态，再验证控制行为

原 fixture 每次生成 2048 帧后 `Event.wait(.005)`，测试从录音开始等待 6 秒进入 running。真实业务必须已写入 10 秒目标块和 4 秒后文，才开始首块推理；因此该等待实际还在检验 CI 调度器能否足够快地产生 14 秒合成音频。计时唤醒没有精确 5 ms 的保证。

定向复现仅将 fixture 的 `.005` 等待延长到 `.020`，原测试在 6 秒后失败：录音正常，已写 514048 帧 / 10.709 秒，转写仍 queued、没有错误，确实尚不具备首块输入。远端原日志只有超时栈、没有该时刻状态；上述具体帧数来自本机复现，不能冒充远端日志。

修复后输入仍经过产品 callback、有界队列和真实 WAV writer；测试以最多 32 个驱动块为一批供帧，等待对应写入水位，再供下一批。满足窗口后才发起转写。真实 spawn 子进程在 Provider 入口发出 Event，并保持推理未返回，直到测试释放或取消；不再用两秒 sleep 猜测推理仍然进行中。

断言仍要求 running、慢推理期间帧继续增长、积压可见、processedMs 为 0、stop 调用低于 100 ms、音频保存可用、队列不超过 64、暂停后为 paused。没有延长原 6 秒 worker 等待上限，也没有把 running 改成接受 queued。Event 和输入 fixture 均为测试控制，不是麦克风或识别质量证据。

### Windows：只改变日志序列化表示

远端日志定位到 `real_asr_check.py` 原第 120 行 `print(json.dumps(result, ensure_ascii=False), flush=True)`，cp1252 无法编码中文。前面的模型推理、CER、时间范围、进度与幂等断言，以及 UTF-8 JSON 文件写入已经完成。

stdout 改为 `ensure_ascii=True` 后仍是完整 JSON，消费者解码后得到相同文字与路径；文件保持 `ensure_ascii=False` / UTF-8。没有修改模型准备、推理或断言，也没有通过强制测试平台编码来掩盖应用问题。

## Tests

本轮为 **S1 局部测试修复**，按两项具体失败进行定向复现与检查。没有运行完整测试、build、lint 或 typecheck。

- 修复前执行 `.venv/bin/python artifacts/spec003/ci-rework/reproduce_slow_fixture.py`：原慢 worker 测试在 6.070 秒失败，诊断为上述不足窗口的 queued 状态。修复后执行相同命令：**1 项通过，0.352 秒**；实际创建并回收 spawn 子进程。
- 修复前用 `PYTHONIOENCODING=cp1252 .venv/bin/python artifacts/spec003/ci-rework/report_encoding.py` 执行真实报告脚本的 print AST：复现相同 `UnicodeEncodeError`。修复后相同命令成功；进一步解析输出，确认全为 ASCII 字节，中文参考、识别文本和中文 Windows 路径 round-trip 与输入完全相同。
- `git diff --check`：通过。针对改动检查 diff，确认没有业务、ASR 参数、参考稿或断言阈值变化。

诊断脚本和输出位于 ignored `artifacts/spec003/ci-rework/`。编码检查直接使用真实脚本中的输出语句，不再次下载模型或重跑已通过的完整推理链路。

## Known Limitations

本轮本机 macOS ARM64 验证不是远端双平台通过。主 Agent 仍须提交此候选并实际等待 macOS / Windows CI，随后由新的独立验收 Agent 检查。本报告不作最终 PASS。

没有重复两分钟 CER、物理麦克风回采、真实模型推理、旧 smoke 或已通过的其他测试；它们对应的实现未改变。没有使用新实机证据声称 Windows 物理麦克风已验证。

## Remaining Questions

无新产品决策。测试进程已结束，修改冻结，可交主 Agent 提交并启动对应双平台 CI。本 Agent 未创建子 Agent，未 commit / push，未替代最终验收。
