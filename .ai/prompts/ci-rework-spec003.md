# Task Handoff — Spec 003 真实 CI 失败修复

> 历史交接，任务已完成。文中分轮报告已归并至 [实施摘要](../../specs/spec-003-local-transcription/implementation.md) 与 [最终验收](../../specs/spec-003-local-transcription/acceptance.md)；原文见 [历史索引](../../specs/README.md)。以下旧指令不作为当前待办。

## Role / Context

新的 Implementation Agent / EXISTING。不创建子 Agent，不做最终验收，不 commit / push。用户授权实施，并明确要求真实验证通过后再宣告完成。分支 codex/spec-003-local-transcription 已推 d7013c94f87c85f081f158012a8e23613e01fdca，真实 run https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34448151461 失败，不能以本机绿色代替。

## Required Reading

AGENTS.md、constitution/mission.md / tech-stack.md、.ai/rules/、Spec003 spec / plan / implementation / implementation-rework-1 / verification，以及相关代码测试。先读当前已提交代码，不覆盖其他 Agent 文档。暂停竞态已通过新独立审查，ASR 参数和质量基准不变。

## Confirmed Failure

macOS job102777445779：19 TS passed，35 Python仅一项失败，其他34项包括4个新增暂停事件测试均过。失败名 test_slow_worker_does_not_block_recording_controls_or_frame_growth，tests/python/test_transcription.py365，wait_for(lambda:service.status(mid)['state']=='running',timeout=6) 超时；test_recording.py66抛 Timed out waiting for recorder。完整日志主Agent从Chrome已登录的GitHub页面读取；REST日志403、公开step URL404不是测试原因。

Windows job102777445529：依赖、typecheck/lint/format、npm test均成功；npm run test:asr在约11秒后失败，主Agent正在获取完整日志，稍后补充，不先猜测放宽模型断言。

## Scope / Constraints

你拥有与两项CI失败直接相关的 tests/python/test_transcription.py、tests/python/real_asr_check.py、必要时 model_manager.py 等相关业务，以及确实需要的诊断/CI配置。先定位macOS确定失败，分析fixture与业务真实状态；禁止只加大等待或放松running断言、绕过真实模型、skip失败平台、替换参考稿、禁用TLS。Windows详情到后再修对应问题。需要更改业务时解释具体依据与影响。

单个实施Agent串行处理耦合测试和必要业务。主Agent正在读取Windows日志并维护治理文档；验收Agent只补一个最终参数下10秒真实纯静音证据，不做其他重验证。不要重跑2分钟CER/物理录音或升级无关依赖。可以对已失败测试做确定复现与最小修复，并保留失败状态诊断帮助CI定位；新提交后由主Agent实际跑双平台，不能宣称未经运行已支持。

## Output

implementation-ci-rework.md：根因、最小修改、实际验证命令/结果、未执行项、可提交交接点。先及时给主Agent具体发现/所需日志，再在工作完成后交正式报告，清理自己的测试进程。
