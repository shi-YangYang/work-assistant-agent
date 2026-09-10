# Task Handoff — Spec 003 返工后独立验收

## Role / Goal

Acceptance / EXISTING。必须由未参与返工的新 Agent 执行；禁止修改业务、测试、配置，不创建子 Agent，不 commit / push。仅写 acceptance.md，保留 acceptance-round-1.md。按 .ai/prompts/acceptance-spec003.md 的全部工程边界验收，结合首轮具体问题与返工；不重新验收用户已确认的 Spec 决策。

## Required Reading

固定规范、Spec / Plan、implementation.md、acceptance-round-1.md、rework.md、implementation-rework-1.md、verification.md、当前相关 diff 与实际 CI 证据。主 Agent 会提供最终候选提交及 macOS / Windows run 结果。

## Focus / Verification

- 独立核对 pause 与已选块、认领 / worker 发送、快速继续和旧结果提交的同步机制；不能仅新增一次非原子 Event 检查，也不能控制路径锁住整段推理。
- 核对同步事件定向回归证明：暂停持续 paused、activity false、旧块不再启动，继续正常完成且无片段重复；worker 取消实际回收，跨平台测试可执行。
- 复用已明确通过且未变化的基础检查、真实模型质量、物理录音与重启定位证据，不为“独立”重复已通过测试。仅对修复留下的具体缺口做最小探测，并先说明依据。
- 最终平台结论必须来自候选提交实际 CI。Windows 新真实 ASR 和 Electron 场景明确开启，旧 4 项平台受限 skip 仍如实记录。
- 物理回采采用用户明确批准的内置扬声器播放公开 FLEURS、人声声波进入真实麦克风的方法；不是文件注入或用户讲话。31.74 秒样本回采37.035秒、首字18.383秒，错误率15.56%；2分钟文件基准是另一项测量，边界写在 verification.md。

## Output

先报告已确认的具体问题（如有），不替实施者改代码。没有问题但远端仍在运行时，向主 Agent 交代码审查结果并等待平台证据，不提前 PASS 或重复启动同类验证。最终 acceptance.md 必须逐项对齐 Spec，明确复用与独立执行证据、对应提交/run、剩余限制，结果仅 PASS / FAIL。
