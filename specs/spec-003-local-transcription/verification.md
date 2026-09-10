# 验证记录 — Spec 003

2026-09-10 实际运行证据整理；[最终独立验收](acceptance.md) PASS。模型、音频、数据库及完整输出位于 ignored `artifacts/spec003/`，不入 Git。以下均保留实际测量和失败历史，不是本次文档整理重新执行的结果。

## 环境与固定参数

参考机 macOS 26.4 / ARM64、Apple M5 / 16 GiB，Node 24、Python 3.12.14。引擎 faster-whisper 1.2.1 / CTranslate2 4.8.2，CPU INT8、4 线程、beam 5、zh / temperature 0 / word timestamps、关闭跨窗口文本条件，提示仅“简体中文”。目标块约 10 秒、静音切分、前后各最多 4 秒上下文，VAD 区间分别解码；没有输入参考稿。

| 锁定项 | 值 |
| --- | --- |
| 模型 | Systran/faster-whisper-small，MIT |
| revision | `536b0662742c02347bc0e980a01041f333bce120` |
| model.bin | 483546902 bytes；SHA256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671` |
| 下载 / 空间 | 完整清单 486214370 bytes；两份文件 + 50 MB 预留，UI 提示 1.1 GB |
| 最终 Provider 源码 | asr_worker.py SHA256 `14a8662c4e129578a5567b0ec7e37aad6af369fefc0cc1d0b458628bbfc35ac2` |

其他文件的大小 / hash 固定于 model_manager.FILES。

## 固定中文质量与计算性能

来源 [Google FLEURS](https://huggingface.co/datasets/google/fleurs)，CC-BY-4.0，revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`，cmn_hans_cn validation 行 1、2、3、5、6、7、8、9、10、11、12，含 WiFi。先固定样本再看识别结果；原音频不裁剪，转 PCM16 mono 16 kHz，句间加 0.5 秒，共 121.76 秒。

组合 SHA256 `acbb245530b0a744c3446afa0316debc5eac8378da057d3068a29750525c3ebb`。人工参考来自数据集，CER 使用 NFKC + casefold，只保留 Unicode 字母 / 数字；不做繁简、同音或数词等价。

| 项目 | 最终结果 |
| --- | --- |
| 276 字符参考 | 整段 15/276=5.43%；业务分块 18/276=6.52%，均仅替换，无插入 / 删除，WiFi 保留 |
| 加载 / 推理 | 加载 0.412 秒；16 块累计 44.659 秒，小于音频时长；第一块计算 2.906 秒，非实录首字延迟 |
| 峰值 RSS | 1071710208 bytes，约 1.0 GiB，包含整段及分块基准进程 |

首轮 beam 1 / 短上下文 / VAD 拼接的分块 CER 14.49% 虽达平均阈值，但确定性漏句和 WiFi，未通过边界要求；按决策 0007 调整后用同一音频复测。证据：`reference-audio/`、`benchmark.json`、`reference-evaluation-revised.json`；原失败为 `benchmark-initial.json`、`reference-evaluation-initial.json`。

## 应用下载与离线 / 静音

全新隔离 Electron userData，设置中实际点击下载，真实字节增长，约 45 秒完成校验 / 加载并就绪，录音保持 idle；沿用用户系统代理，不硬编码代理或关闭 TLS。证据 `interactive/session.json`、`model-state.png`。取消、损坏与失败重试由定向测试覆盖。

两平台真实集成在 worker 禁止 socket 连接后加载本地模型并推理。短样本为 [Wenet / AISHELL](https://github.com/wenet-e2e/wenet/blob/d17059667d6afe0680d19b3a4948ab825ef25105/test/resources/aishell-BAC009S0724W0121.wav)，固定 commit `d17059667d6afe0680d19b3a4948ab825ef25105`，4.281 秒，SHA256 `2f9fc9c912bb71c85fb286cb88b599c81efb8f727c727a5ea8f6d1c89c55ac13`。参考“广州市房地产中介协会分析”，输出“廣州市法地产中介协会分析”，CER 2/12=16.67%，错误未修饰。

第二轮独立验收仅补最终参数纯静音缺口：候选 d7013c9、上述 Provider hash、加载前禁止 socket，10 秒 / 160000 零样本 / mono PCM16 16 kHz，`words=[]`，加载 0.558721 秒、推理 0.110693 秒。证据 `final-provider-silence.json`；纯静音不能外推所有噪声无幻觉。

## 物理麦克风与桌面闭环

用户指定公开真人语音经内置扬声器→物理麦克风回采。实际 MacBook Pro 麦克风 / 扬声器、48 kHz，沿用输出 25% / 输入 100%，不修改系统设置；助手用系统播放器播放固定 FLEURS 行 1、2、3、11（31.74 秒，含 WiFi），经过正常 Recorder，不是 PCM 注入或用户现场发言。

第一轮播放晚约 9 秒且声压低，40.064 秒录音虽保存转写，不计为质量 / 延迟通过；保留 `interactive/session-first-recording.json`。第二轮仅改播放时机和公开参考分句增益（峰值≤0.95），Provider / 原参考不变。播放文件 SHA256 `56b28914768bbc149c46fcaebac871f2aa5fb952e3a8fb1eaf09e23f1c3f0b9c`。

| 第二轮测量 | 结果 |
| --- | --- |
| 启动 / 首字 | 开始后 0.154 秒播放，18.383 秒出现持久文字（轮询 0.7 秒） |
| 录音与补尾 | 37.035 秒、1777664 帧、mono PCM16 / 48000 Hz；录音先 completed、转写仍 draining，之后处理全帧并 completed / pending=0 |
| 文字 | 4 段，人工参考 90 字符，14/90=15.56%，WiFi 保留 |
| 重启与定位 | 状态、ID、文字、时间一致；点第二段定位 9.266 秒，实际播放至 9.9418 秒、readyState=4，随后暂停退出 |
| 录音 SHA256 | `abc13c334ee13948ac871d8c9bd1d3354a94f845d1f728ce03d4c773e4ed4c42` |

证据：`microphone-evaluation.json`、`interactive/session.json`、`interactive/microphone-restart.json`、`interactive/microphone-playback.json` 及对应截图。两分钟原文件的累计性能和短回采的首字延迟分别测量，不混称同一次两分钟实录。

## 实际 CI 与失败闭环

| 提交 / run | 实际结果 |
| --- | --- |
| d7013c9 / [34448151461](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34448151461) | FAIL：macOS 35 Python 中慢 worker 等 running 失败，其余 34 与 19 TS 通过；Windows 单元和 ASR 断言通过，stdout cp1252 输出失败，smoke 未跑。 |
| 9a8dc78 / [34449407056](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34449407056) | Windows 全部成功；macOS 其余检查和 6 旧 smoke 通过，新 smoke 90 秒、teardown 30 秒超时，原附件无正文栈。 |
| 9aa788b / [34450871426](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34450871426) | 有界关闭和阶段诊断生效。Windows 成功；macOS 重启 paused / 关闭保护通过，30 秒恢复等待到期仍 draining，已处理 8460 ms / 剩余 8664 ms、error=null，正常清理。首块约 24.305 秒是轮询观测，不是精确 worker 计时。 |
| 0b84fe1 / [34451673078](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34451673078) | **工作流和两个平台 job 全部 success**。按实测设恢复等待 60 秒 / 总 120 秒，模型、fixture 与 completed 断言不变。 |

最终完整 SHA `0b84fe1c6349aa7c413da2d24bc700e43849d97e`。macOS 26.6.2 ARM64 / Windows Server 2025 x64，Python 均 3.12.10；各通过 19 TS、35 Python、依赖 / 类型 / lint / 格式 / 构建。macOS smoke 7 通过，Windows 3 通过、4 个既有跳过（原生 macOS 权限适配和 3 个 POSIX shim），新增真实转写必跑。

最终短 ASR macOS 8.956 秒 / Windows 3.500 秒；新 smoke 含清理 70.598 / 37.004 秒，恢复阶段 44.445 / 23.239 秒。两平台均处理完 17124 ms / 273984 帧，completed、pending=0、error=null，正常退出。云 runner 耗时不替代 M5 性能基准。

原始 API 为 `ci/<完整提交SHA>.json`，各轮附件在 `ci/<run>-{macos,windows}/`。附件摘要与官方 API 核对；最终 macOS zip SHA256 `c05950572ab3f868163045c05ab85eac574162b00bce6ae5f06ee5c665d3ef30`，Windows `6c356aaebb11829e0501f81212e8c2a9f3b4fdd005a409e8a471a74852f13b04`。失败复现另见 `ci/failure-evidence.json`、`ci-rework/`；完整旧记录在 [Git 快照](https://github.com/shi-YangYang/work-assistant-agent/blob/23ba685f5af58039ec30297d8e20af91eef61f10/specs/spec-003-local-transcription/verification.md)。

## 未验证范围

Windows 物理麦克风、首次 macOS 授权弹框、最低配置、其他架构 / GPU、正式安装包及内置运行时。固定清晰样本和纯静音不保证所有硬件、口音或噪声条件的质量 / 实时性。
