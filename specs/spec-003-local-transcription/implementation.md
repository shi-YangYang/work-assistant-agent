# 实施摘要 — Spec 003

2026-09-10 · 原实施、暂停返工和 CI 修复已完成；最终 [独立验收 PASS](acceptance.md)。本文归并原实施记录，模型参数及所有实测值集中在 [verification.md](verification.md)。

## 最终实现

| 模块 | 实现 |
| --- | --- |
| model_manager.py | 固定 HTTPS 清单、revision / hash，下载字节进度、取消 / 重试；staging 校验并实际加载后发布，继承系统代理且保持 TLS。 |
| asr_worker.py | 受管 spawn 进程、一个离线 Provider，重采样、VAD 区间分别推理和规范化时间结果；超时 / 崩溃 / 取消回收。 |
| transcription.py | 有限音频窗与持久检查点、静音边界、时间归属去重、活动会议优先、尾块与恢复。 |
| transcript_store.py / repository.py | schema 1→2 增量事务、备份、有界忙等待、稳定块 / 片段 ID、文字和进度同事务、每页最多 50 段。 |
| recorder.py | 只增加短读与收尾重命名互斥；读取完整帧后关闭句柄再推理，原采集队列和 WAV 格式不变。 |
| protocol / desktop / shared | 有限模型 / 转写契约、响应校验、超时查状态、转写关闭保护及暂停退出。 |
| renderer | 模型准备卡、无模型录音提示、持续文字 / 积压、继续、滚动跟随与片段定位。 |
| 依赖 / tests / CI | 锁定推理依赖，增加真实模型集成、跨平台 Electron 场景及模型缓存，只上传报告和截图。 |

## 持久化与并发细节

备份先写 `meetings.schema1.backup.staging`，关闭成功后发布为 `meetings.schema1.backup.sqlite3`；失败清理 staging、保留原库，忙等待限 2 秒。迁移不改旧会议或音频。已确认片段与检查点原子提交；重启先恢复音频，再暂停未完成任务，用户继续。

暂停、认领与提交共用短控制锁，每次运行使用不可复用的 InferenceToken。暂停后旧迭代不得再启动推理、提交结果或错误；继续换新令牌。worker 发送与取消共享短令牌锁，模型等待在锁外；采集和控制不被整段推理阻塞。

## 已关闭的问题

| 阶段 | 发现 | 修复与验证依据 |
| --- | --- | --- |
| 模型预检 | VAD 拼接、短上下文和 beam 1 漏句；长提示在噪声中复读 | 分别解码 VAD、静音边界 / 有限上下文、beam 5、短语言提示；同一固定样本复测，决策依据见 0007。 |
| 首轮独立 FAIL / P2 | 读取窗口后暂停被旧迭代覆盖为 running / draining，无法继续 | 上述锁与令牌；4 个 Event 回归固定取块间隙、旧结果、旧异常、取消后发送，相关 9 项检查通过。 |
| 首次真实 CI | macOS fixture 按 5 ms 定时供帧，6 秒时未必已有 14 秒窗口；Windows cp1252 打印中文失败 | 按精确帧水位供给，经真实 callback / writer，跨进程 Event 持住真实 worker；stdout ASCII 转义，UTF-8 文件不变。 |
| 后续 macOS smoke | app.close 先断调试连接再遇确认，finally 掩盖正文错误 | 正文走真实窗口关闭与 10 秒 close 等待，失败清理回答确认、有界回收，保留原错；增加阶段 JSON。 |
| 明确的恢复超时 | 30 秒仍 draining，但已处理 8460 ms、剩余 8664 ms，无错误 | 根据首块约 24.3 秒实测设恢复等待 60 秒 / 总 120 秒；不改模型、fixture、completed 断言或参考机性能标准，最终双平台实际完成。 |

慢 worker 修复前用 20 ms 调度复现原失败：6.070 秒时仅有 10.709 秒音频；修复后同探测 0.352 秒通过，仍要求 running、processed=0、帧增长 / 积压、有界队列、stop<100 ms 和 paused。编码探测用 cp1252 执行真实 print 语句，修复后中文 / 中文路径 JSON 往返一致。

## 验证交接

原实施本机通过 19 TS、31 Python、类型 / lint / 格式 / 构建、6 个旧 smoke 和新真实转写 smoke；暂停返工补 4 个回归，定向 9 项通过。随后仅按具体 CI 失败修复测试，未改业务或 Provider。每轮实际 CI、最终 35 项 Python、物理录音及质量证据由 [验证记录](verification.md) 统一记载；最终验收者独立审查并复用证据，未无理由复跑。

无待确认产品问题或待返工事项。安装包、Windows 物理麦克风等限制见验收报告。原 implementation、implementation-rework-1、各 implementation-ci-* 与 rework 全文可在 [整理前 Git 快照](https://github.com/shi-YangYang/work-assistant-agent/tree/23ba685f5af58039ec30297d8e20af91eef61f10/specs/spec-003-local-transcription) 追溯。
