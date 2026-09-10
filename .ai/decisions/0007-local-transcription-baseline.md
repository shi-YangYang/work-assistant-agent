# Decision — 本地转写实施基线

日期：2026-09-10。

状态：Spec 003 工程验收中。macOS 已完成模型准备、固定中文基准和用户指定的物理声学回采；首轮验收发现暂停竞态，正在返工，双平台 CI 待最终候选提交。

## Context

录音与本地保存已完成，用户要求继续下一份 Spec，并明确选择中文为主、兼顾中英混合，首次使用由应用提示并下载默认模型。项目使命已要求本地持续转写、Provider 边界与录音不受推理阻塞。

## Decision

- [Spec 003](../../specs/spec-003-local-transcription/spec.md) 交付模型准备、录音中分批转写、结束补齐、持久 Transcript、历史补转写与中断继续。纪要及云 ASR 留给后续。
- 先用一个 `faster-whisper` Provider，默认候选为 `Systran/faster-whisper-small` 多语言模型，以 CPU / INT8 作为 macOS、Windows 通用基线。固定转写任务、中文为主，保留英文术语原文。
- 本次不要求 CUDA，不声称利用 Apple GPU。实施首步核对 wheels、锁定发布版本 / 模型 revision / 文件校验信息，并实测中文、混合语言与性能；不依据第三方跑分承诺用户电脑实时速度。
- 推理使用核心管理的独立工作进程，录音仍沿用已有输入流与 WAV writer；以磁盘音频及持久检查点承接积压。全局一次推理，不引入额外 HTTP 服务。
- 模型下载由用户在应用中明确发起，仅使用固定来源和清单；推理仅加载完整的本地模型，不外发音频或文字。模型未准备好时仍可录音，之后补转写。
- 已完成录音与已完成转写分别建模；应用可以保存进度后退出，重启后由用户继续。schema 从 1 增量扩展，不删除旧会议或音频。

## Reason

已有核心采用 Python，faster-whisper 提供 Python 接口、片段时间和 VAD 集成，便于保持一个真实 Provider。CTranslate2 文档列出 x86-64 与 ARM64 CPU 支持，GPU 路径为 NVIDIA；因此 CPU 是本轮更统一的初始边界，实际平台安装仍须验证。[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[CTranslate2 硬件支持](https://opennmt.net/CTranslate2/hardware_support.html)。

选用多语言 small 是本轮资源与效果之间的工程起点，不是已证实的最佳中文模型。发布者提供对应的 CTranslate2 模型，模型卡说明其多语言属性及加载时精度选择。[模型卡](https://huggingface.co/Systran/faster-whisper-small)。

## Alternatives

- `whisper.cpp` 支持 macOS / Windows，并提供 Apple Silicon / Metal 路径，适合后续需要 GPU 加速或原生分发时评估；本轮会额外引入 C/C++ 构建与调用边界，因此不同时实施。若 CPU 实测无法满足目标，基于结果重新比较，不能以“Python 更方便”为由掩盖不达标。[官方说明](https://github.com/ggml-org/whisper.cpp)。
- 云 ASR 需要外发音频及服务费用决策，与当前本地转写方向不符，本轮不接入。
- 仅会后转写实现较少，但不能满足已明确的持续 Transcript 目标。

## Consequences

运行依赖和模型体积会增加，需在真实目标环境记录实际版本、磁盘量、加载时间和资源占用。用户无需自行准备模型路径；当前仍是开发交付，正式运行时与安装包由 [决策 0005](0005-self-contained-desktop-distribution.md) 约束。

本决定不锁死未来 ASR 引擎，但本轮只实现一种。质量与性能不达标时记录具体样本和数据，再调整方案及本 Decision；不得在没有真实推理的情况下标为已完成。

## 实施预检记录

- 当前预检引擎：faster-whisper 1.2.1、CTranslate2 4.8.2，Python 3.12 / macOS ARM64 原生 wheel；最终完整锁定依赖以 requirements.lock 与实施报告为准。
- 模型：`Systran/faster-whisper-small`，revision `536b0662742c02347bc0e980a01041f333bce120`。主权重 483546902 字节，SHA256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`。配置 / 词表完整清单由实现中的受控 manifest 记录。
- 已有短样本预检证据位于 ignored `artifacts/spec003/preflight.json`。Wenet / AISHELL 的 4.281 秒真人样本实际推理约 1.231 秒，有一个字的识别错误；该结果只证明推理链路可用，不能替代长样本和持续录音验收。
- 已准备 Google FLEURS 中文 validation 的固定 11 条真人样本，总组合时长 121.76 秒，来源、CC-BY-4.0 许可、选择索引、参考稿和音频校验值保存在 ignored `artifacts/spec003/reference-audio/`。样本在实际转写结果之前选定，不按识别效果挑选。[数据集来源](https://huggingface.co/datasets/google/fleurs)。
- 本机直接访问模型来源曾超时，使用系统既有代理后成功。Python urllib 已验证能读取该 macOS 系统代理；不修改系统代理、不在产品硬编码开发机代理地址，保留正常 TLS 校验。Windows 网络行为仍需实际验证。

首轮长样本预检（非最终验收）：同一 121.76 秒 FLEURS 组合，CPU / INT8 / 4 线程 / beam 1 的整段推理约 5.611 秒，13 个固定业务窗累计约 14.374 秒。按 NFKC、大小写折叠、仅保留 Unicode 字母与数字计算，276 个参考字符中整段 CER 为 23/276（8.33%），分块为 40/276（14.49%）。没有使用同音、繁简或数词等价来降低错误率。分块确定性漏掉部分句首和整句 WiFi 内容，因此即使平均 CER 小于 20%，首轮边界要求未通过，后续修正见下文。原始和独立计算证据保存在 `artifacts/spec003/benchmark-initial.json` 与 `reference-evaluation-initial.json`。

后续修正将 VAD 检出的语音区间分别解码，目标块长仍为 10 秒，优先选择目标附近静音边界，上下文增加为前后各 4 秒，beam 调整为 5，保持 CPU / INT8 / 4 线程。对同一固定样本重新验证：整段 CER 15/276（5.43%）、分块 CER 18/276（6.52%），均仅有替换，没有字符插入或删除；此前漏掉的内容恢复，繁体差异仍计入错误。16 个业务块累计约 44.659 秒，模型加载约 0.412 秒，峰值 RSS 约 1.0 GiB。证据为 `benchmark.json` 与独立计算的 `reference-evaluation-revised.json`。这说明该样本上的质量和处理速度达到预定目标；桌面实际首批出字延迟、真实麦克风流程和双平台验收仍需单独完成。

## 真实麦克风验收方式

用户于 2026-09-10 明确选择切换到内置麦克风与扬声器，由应用播放公开人声做采集验证。该方式经过物理扬声器与麦克风，区别于文件注入；不是用户现场发言，结果按声学回采说明。测试仅使用固定 FLEURS 公开非敏感语音，在隔离数据目录保存，不调整系统隐私设置。

第二轮声学回采在 18.383 秒出现首批文字，37.035 秒录音与尾部转写完成，CER 14/90=15.56%，重启片段不变，点击定位后实际播放推进。方法、失败留痕和性能测量边界见 [实际运行证据](../../specs/spec-003-local-transcription/verification.md)。
