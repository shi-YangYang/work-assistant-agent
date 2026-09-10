# Acceptance — Spec 003 · Round 1

## Result

**FAIL**

日期：2026-09-10。由未参与本轮业务实现的独立验收 Agent 执行工程审查；未重新验收 Spec 决策，未修改业务、测试或配置。

已发现并通过最小同步探测复现暂停状态竞态。该问题违反 R5，必须返工后由新的独立验收 Agent 复验。本轮结论不等待远端 CI；对应候选提交的 macOS / Windows CI 和物理麦克风流程仍由协调 Agent 收尾，不能提前记为通过。

## Spec Coverage

| 范围 | 本轮核对结果 |
| --- | --- |
| R1 模型准备与离线边界 | 固定官方来源、revision、逐文件大小 / SHA256，HTTPS 重定向受限；staging 校验并实际加载后发布。取消标记、有限网络超时和失败重试有实现与定向测试。实际应用下载及禁止 worker 联网的真实推理复用实施 / 协调证据。 |
| R2 采集与推理解耦 | 独立 spawn worker，原始 WAV 承接积压，读取当前有界窗口后关闭句柄再推理；单个推理、活动会议块优先、超时 / 崩溃清理和父进程死亡监视有实现。慢 worker 下帧增长、控制响应和收尾复用已通过测试。暂停与取块的并发协调存在下述问题。 |
| R3 Transcript | 片段 ID / chunk ID 稳定，结果与检查点事务提交；时间归属和有限上下文避免简单字符串去重。查询每页最多 50 段，renderer 按游标追加；保留用户上文位置和回到最新操作，录音期间禁播，已保存片段可定位。 |
| R4 尾部与重试 | 有效帧区间连续，短尾块与静音也推进检查点，只有目标帧处理完成才完成任务；原录音状态独立。完成任务重复开始不覆盖已保存文字；失败继续沿用任务快照。 |
| R5 生命周期 | 退出保存、重启 paused、恢复后人工继续、worker 回收已有实现及测试；但暂停恰逢已选中块时可被覆盖为 running / draining，随后永久停在活动状态，**不满足**。 |
| R6 数据与安全 | schema 1→2 的 DDL / user_version 处于同一事务；备份写 staging、成功后替换，有界数据库忙等待，失败清理 staging 并保留原库。旧会议不自动转写。新 preload 只暴露受控操作，main / Python 验证会议 ID 与游标，未开放任意 URL / 文件路径 / 命令。 |
| 真实质量与性能 | 复用固定 121.76 秒 FLEURS 人声与参考稿，最终业务分块 CER 18/276 = 6.52%，累计推理 44.659 秒；首轮边界失败证据保留，修正后无字符插入 / 删除。不能将该结果外推所有设备和声学环境。 |
| 物理麦克风与平台 | 应用下载已实际验证；首轮声学采集条件不足，没有当作质量通过。协调 Agent 第二轮物理采集正在完成流程。Windows 新真实 ASR / Electron 场景在 CI 中明确开启，没有沿用原有 4 项 Windows 跳过；远端对应提交尚未执行。 |

## Tests

### 复用已明确通过的实施证据

依据 [implementation.md](implementation.md) 和实际测试源码核对，不为独立验收重复运行未修改的检查：

- 19 项 TypeScript 单元测试、31 项 Python 测试；模型取消 / worker 退出调整后 11 项转写定向测试。
- 类型、lint、format、build；6 项原有实际 Electron smoke，以及显式启用的新真实模型 Electron 场景。
- `npm run test:asr`：固定公开中文语音、真实 small CPU INT8 worker，工作进程禁止 socket 连接；实际结果、时间范围、完成帧位置、幂等。
- 备份失败 / 忙等待、DDL 回滚、块事务失败 / 重放、分页上界、尾块、暂停恢复、缺失音频、慢 worker / 崩溃 / 超时、模型损坏与取消重试。
- 协调 Agent 的固定样本质量独立计算和实际应用模型下载证据。

### 本轮独立执行的最小探测

技术依据：`Transcription.pause()` 与 `run()` 对任务状态的写入没有共同原子边界；已有暂停测试只在推理已进入 running 后暂停，未覆盖选块后尚未标记执行的间隙。

执行一次内联 Python 探测，复用 `tests/python/test_transcription.py` 的临时仓库、3 秒 WAV、ReadyModel 和 InlineWorker，不加载真实模型、不采集麦克风、不改产品文件。步骤：

1. 建立已保存的 3 秒音频并创建转写服务。
2. 包装 `service.read_window`，在真实窗口读取完成、返回调度器前以 `threading.Event` 暂停。
3. 调用 `service.start(meetingId)`，等到上述间隙后执行 `service.pause()`。
4. 确认状态为 paused，释放窗口返回，等待 0.4 秒后查看状态和 worker 调用数。
5. finally 释放事件、关闭服务 / recorder 并清理临时目录。

实际输出：

```json
{
  "stateImmediatelyAfterPause": "paused",
  "stateAfterSelectedBlockResumes": "draining",
  "activity": { "active": true },
  "workerCallsAfterPause": 1,
  "processedMs": 0
}
```

该探测只制造真实并发间隙，没有伪造业务返回状态。结果证明暂停后仍启动推理并覆盖 paused；`pausing` 保持 set，下一轮不会调度，状态不能自行恢复。

## Issues

### P2 — 暂停可以被已选中的块覆盖，导致永久显示处理中

位置：`src/python/paa_core/transcription.py:178–191`，特别是第 188 行无条件 `store.state(..., 'draining' / 'running')`，以及第 205–210 行 `pause()`。

触发：休眠 / 生命周期暂停发生在循环已经检查 `pausing`、读取窗口之后，但尚未标记块执行之前。

当前行为：`pause()` 先置事件并持久化 paused；旧调度迭代继续将其改回 running / draining 并调用 worker。推理结束后因暂停事件仍在而不提交，后续循环也不再调度。`activity()` 永远返回 true；界面只为 paused / failed 提供“继续转写”，因此用户不能在当前会话正常恢复，只能重启核心 / 应用。

影响：违反 R5 的暂停状态与可继续处理要求；虽然原始音频和已提交文字未丢失，用户会看到没有实际进展的活动任务。

## Regression Risks

返工必须同时保留录音控制响应、有界 worker 中断、检查点事务与同一会议重复继续的幂等性。仅在第 188 行前追加一次非原子的事件检查仍会留下检查到写入之间的相同竞态。协调取块 / 标记执行 / pause 时，不应持有会迫使控制请求等待整个模型推理的锁。

原有 Windows 4 项平台受限录音 smoke、Windows 物理麦克风和最低系统版本不在本轮已验证范围；新的真实推理场景不能以这些 skip 代替。远端与声学流程缺口需在最终验收中如实补记。

## Required Rework

1. 让暂停和“认领并启动下一块”具有明确的并发状态边界；暂停后旧迭代不能把 paused 改回活动状态，不能静默启动新推理。已在执行的块应有界中断，未提交进度由以后继续重做。
2. 使用同步事件固定上述间隙，加入定向回归：暂停后保持 paused、activity 为 false、不会因旧迭代变为永久 running / draining；随后继续能够完成且不丢失 / 重复已提交片段。避免只依赖 sleep 碰运气。
3. 运行与该生命周期改动直接相关的检查，通过后停止重复验证。无需因本问题重新调整或重复已经通过的模型质量基准。
4. 由新的独立验收 Agent 检查返工，并结合协调 Agent 完成的真实物理麦克风流程和对应提交 macOS / Windows CI 证据给出最终结论。
