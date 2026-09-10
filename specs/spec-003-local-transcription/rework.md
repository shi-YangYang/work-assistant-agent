# Rework — Spec 003 · Round 1

## 状态与依据

2026-09-10，独立工程验收 [Round 1](acceptance-round-1.md) 为 FAIL。唯一确认问题为 P2 暂停与已选块竞态；真实模型参数、声学链路和原录音实现不在返工范围。主 Agent 已读取完整报告。

## 返工目标

- 暂停与取块 / 标记执行具有原子状态边界；暂停之后旧调度迭代不能把 paused 写回 running / draining，也不能再静默启动推理。
- 已执行块有界中断，不丢失已提交文字；继续时仅重做未提交块，避免暂停后快速继续让旧结果错误提交。
- 不能在整个模型加载或推理期间持有控制请求必须等待的锁。保留录音优先、控制响应和同一会议幂等。
- 使用同步事件固定 read_window 返回前的间隙，证明暂停后仍 paused、activity=false、没有新推理；继续后正常完成并防重复。不要靠 sleep 碰运气。

## 验证范围

此处为生命周期与检查点交互的 S2 定向返工；如修改 worker 共享协议，说明具体依据后扩展相关 worker 测试。运行最小相关回归以及涉及的新增 Electron 关闭 / 恢复场景。已经通过的中文基准、物理录音、旧无关 smoke、TS 检查不因本次 Python 局部返工重复执行。最终双平台 CI 覆盖本次最终候选提交。

## 交付

新实施 Agent 修改后写 implementation-rework-1.md；验收 Agent 不修改业务代码。随后创建新的独立验收 Agent，结合主 Agent 的声学回采、重启定位和实际双平台 CI 结果重新判断。

## Round 2 — 实际 CI 失败

候选 d7013c94f87c85f081f158012a8e23613e01fdca 的实际 run 34448151461 未通过，[第二轮独立验收](acceptance-round-2.md) 为 FAIL；原暂停竞态已确认修复。

- macOS：19 TS通过，35 Python仅慢worker场景等待running超时。需先定位真实状态与fixture，不盲目加大超时或放宽断言。
- Windows：npm test通过，真实模型与推理断言通过；测试脚本输出中文JSON时cp1252编码失败。修复报告输出，保持真实模型和语音断言。
- 新实施交接为 .ai/prompts/ci-rework-spec003.md。修复后对应提交重新运行实际双平台CI，再由新的独立验收Agent复验。
- 最终Provider纯静音已补实测：10秒零样本无输出，绑定d7013c9和源码hash，见verification.md与第二轮验收；不用重复该缺口检查。

## CI 集成收尾

两项 CI 测试修复后，Windows 通过；macOS 新增 smoke 的失败清理遮住正文超时。先修正有界窗口关闭与清理、保存阶段证据，实际下一轮明确定位到 17.124 秒多块恢复推理在 30 秒时仍正常 draining。根据首块约 24.3 秒的实测，将恢复等待设为 60 秒、总预算设为 120 秒，保留样本、模型和全部通过断言。

对应实施报告依次为 [CI 测试修复](implementation-ci-rework.md)、[关闭与诊断](implementation-ci-smoke-rework.md)、[实测等待预算](implementation-ci-time-budget.md)。所有中间失败和最终事实保留于 [verification.md](verification.md)。

最终代码 `0b84fe1c6349aa7c413da2d24bc700e43849d97e` 的 [真实双平台 CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34451673078) 已通过；macOS 的新增恢复阶段实际 44.445 秒完成，Windows 23.239 秒完成，均补齐全部帧且正常退出。没有修改产品性能目标或跳过新增场景，原暂停竞态及上述 CI 返工事项均已闭环。
