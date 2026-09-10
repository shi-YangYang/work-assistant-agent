# 决策 0007 — 本地转写

2026-09-10 · 已在 Spec 003 落地。

## 决定

- 用户选择中文为主、兼顾中英混合，应用内提示并下载默认模型。
- 一个 faster-whisper Provider，使用多语言 Whisper small、CPU INT8；不要求 CUDA，不声明 Apple GPU 加速。固定模型来源、revision、清单与 SHA256，校验及本地加载成功后才就绪。
- 下载由用户发起，继承系统网络设置并保持 TLS 校验；就绪后只读本地模型，音频与文字不外发，无云回退。
- 独立受管 spawn worker 推理，全局一次，活动录音优先；WAV 与 SQLite 检查点承接积压。录音完成与转写完成分别建模，中断后由用户继续。
- 默认约 10 秒业务块、静音边界、前后各最多 4 秒上下文，beam 5 / 4 线程；VAD 区间分别解码，以时间归属避免重叠重复。只使用“简体中文”通用提示，不喂参考稿。

## 取舍与实施调整

Python 核心已有稳定边界，faster-whisper 易于隔离并返回时间信息。small 是资源与中文效果的起点，不是最佳模型承诺。whisper.cpp / Metal 留待确有 GPU 或原生分发需求时评估；云 ASR 涉及外发与费用，不在本轮范围。

首轮 beam 1、较短上下文和 VAD 拼接解码漏掉句首及 WiFi 整句，因此改用上述参数；长通用提示曾在噪声窗诱发复读，缩为语言提示。采用同一固定样本复测，没有换参考稿降低错误率。用户指定的公开人声经扬声器→物理麦克风回采，与文件推理分别记录。

模型锁定值、质量 / 性能、真实麦克风及双平台 CI 集中见 [验证记录](../../specs/spec-003-local-transcription/verification.md)；行为标准见 [Spec 003](../../specs/spec-003-local-transcription/spec.md)，安装包仍受 [决策 0005](0005-self-contained-desktop-distribution.md) 约束。

## 依据

2026-09-10：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[CTranslate2 硬件支持](https://opennmt.net/CTranslate2/hardware_support.html)、[small 模型卡](https://huggingface.co/Systran/faster-whisper-small)、[whisper.cpp](https://github.com/ggml-org/whisper.cpp)。性能结论以项目实测为准。
