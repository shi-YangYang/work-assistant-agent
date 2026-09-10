# Plan — Spec 003

DONE。对应 [Spec](spec.md)；实施及返工见 [implementation.md](implementation.md)。

## 模块与数据流

`麦克风 → 既有队列 / WAV writer → 已写帧水位 → 有界音频窗 → ASR worker → 片段与检查点事务 → 分页 UI`。

| 模块 | 职责 |
| --- | --- |
| model_manager | 固定下载清单、进度、取消 / 重试、校验、实际加载后发布 |
| asr_worker | 一个 Provider、spawn 生命周期、重采样 / VAD / 推理及规范化结果 |
| transcription / transcript_store | 分块、活动录音优先、任务快照、连续检查点、静音 / 尾块、分页 |
| repository / recorder | 增量 schema、启动恢复、WAV 读取与收尾重命名的最小协调 |
| desktop / shared / renderer | 有限契约、模型状态、文字与进度、关闭保存 / 暂停、定位播放 |

## 实施顺序

1. 核对双平台 wheels，锁定引擎 / 模型 / 清单；用固定中文和混合语音验证质量与耗时，未达标先调整参数，不同时引入第二引擎。
2. 实现 schema 1→2、任务 / 块 / 片段与恢复，再接模型管理和受管 worker。
3. 先跑历史 WAV，再消费活动录音的已写水位；接入桌面状态、退出恢复与 UI。
4. 完成相关故障、真实模型、物理麦克风及实际双平台检查，独立验收后交付。

## 接口与并发

有限 API：getTranscriptionModel、downloadTranscriptionModel、cancelModelDownload、startTranscription(meetingId)、getTranscriptionStatus(meetingId)、listTranscript(meetingId,cursor)。命名与协议定义集中维护，禁止 renderer 指定路径 / URL。

短时读取完整帧后关闭 WAV 再推理，避免 Windows 收尾句柄冲突；范围有效区间连续不重叠，上下文可有界重叠，按时间归属去重，不全局删相同字符串。全局一次推理，录音 / 控制不持有长推理锁；状态查询不重叠、分页最多 50 段。

## 迁移策略

新库建立最新 schema，旧 v1 在事务中增加表 / 索引并更新版本，先备份；DDL 失败回滚，未知版本拒绝。音频与旧会议不移动，文字与块进度同事务。启动先恢复录音，再将未完成任务暂停；不自动处理历史。恢复备份与回滚说明见 README，不通过删表降级。

## 验证计划

S3 依据为 schema、IPC、下载安全和进程生命周期。按改动验证存储事务 / 幂等 / 迁移、静音 / 尾部 / 时间映射、慢与崩溃 worker、录音帧增长及有界控制、下载取消 / 损坏 / 加载失败；桌面验证模型、历史、文字、关闭与重启，契约 / CSP 变化配合类型与构建。

真实验证单列：固定两分钟中文及英文术语、静音 / 噪声 / 跨块，记录参考稿、CER 算法和耗时；物理麦克风明确输入方式；macOS / Windows 用同一锁定短样本和模型运行真实 ASR 与新增 Electron 场景。命令见 [技术栈](../../constitution/tech-stack.md)，实测只在 [verification.md](verification.md) 详述，不重复已通过检查。

## 风险

CPU 不保证所有硬件实时；断网要显示重试而非不可信镜像或云回退；VAD / 短窗可能漏字或幻觉，须固定样本核对。进程隔离仍共享物理 CPU；Windows spawn、文件句柄与退出必须实测。测试等待预算按实际 runner 证据设置，不降低业务终态或参考机性能标准。
