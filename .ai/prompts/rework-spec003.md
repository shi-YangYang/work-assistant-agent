# Task Handoff — Spec 003 暂停竞态返工

## Role / Goal / Project Mode

Implementation / EXISTING。作为未参与首轮实现的新实施 Agent，只修复 Spec 003 首轮独立验收确认的暂停竞态。不得创建子 Agent，不做最终验收，不 commit / push。

## Required Reading

AGENTS.md、constitution/mission.md / tech-stack.md、.ai/rules/全部规则、Spec 003 spec.md / plan.md / implementation.md / acceptance-round-1.md / rework.md、相关 workflow 与业务代码。

## Scope

拥有 src/python/paa_core/transcription.py、必要时 asr_worker.py、对应 tests/python/test_transcription.py 和 implementation-rework-1.md。主 Agent 正在维护 docs、constitution、spec状态及平台验证，不覆盖其文件。其他业务文件只有修复确实需要时说明原因后修改，不调整已通过的 ASR 参数与中文样本。

## Acceptance / Verification

完整复现步骤和要求见 rework.md 及 acceptance-round-1.md。暂停不能被已选中的旧块覆盖；开始/暂停/结果提交的旧迭代有效性要明确。一次非原子事件检查不足，持锁整个推理也不接受。已有 worker.interrupt 是非阻塞模式，兼顾暂停后立即继续和旧结果提交。

先做事件同步的定向回归，修复后运行相关生命周期检查；必要时只运行新增真实模型 Electron 关闭恢复场景，不重复已通过的中文 CER/性能或物理录音。新增测试不得依赖真实麦克风 / POSIX shim，需要能在 Windows CI 运行。代码修改结束后给主 Agent 安全的构建/CI交接点。

## Context / Expected Output

主 Agent 已完成用户指定的内置扬声器播放公开 FLEURS → 内置麦克风物理采集：37.035秒，首字18.383秒，CER14/90=15.56%，结束补尾、重启片段不变，点击定位后实际播放推进。固定2分钟原始参考样本 CER6.52%、累计44.659秒。此次问题不需要调整模型或重做上述验证。

交付 implementation-rework-1.md：修改、并发机制、执行命令与通过数量、未执行及限制；不伪称 Windows CI 或最终独立验收通过。
