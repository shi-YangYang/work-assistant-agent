# 本地转写

- 提供六款多语言 Whisper 模型，默认 small／中文，支持英文和中英混合。small 是资源与效果的起点，不承诺最佳准确率。
- 模型由用户发起下载，固定来源、revision 和 SHA256；校验及本地加载成功后才就绪。保留 TLS 校验，推理只读本地模型，无云回退。
- 独立受管 spawn worker，全局一次推理、活动录音优先；WAV 与 SQLite 检查点承接积压。录音完成与转写完成分别建模，中断后由用户继续。
- 新任务锁定模型、语言、设备和解码配置。旧会议手动重转写，候选成功后原子发布；失败保留旧文字和纪要，旧纪要由用户手动更新。
- CPU 使用 faster-whisper／CTranslate2 INT8、beam 5／4 线程；约 10 秒业务块，静音边界及前后最多 4 秒上下文，按 VAD 区间分别解码，以时间归属去重。短上下文与拼接解码曾漏句，长提示曾诱发复读，因此只保留通用语言提示，不喂参考稿。

## CPU／GPU

- 默认优先可用 GPU，主动选择 CPU 后持久保留；展示硬件名称，不可用时说明原因，不把 CPU 推理标为 GPU。
- Windows 使用 NVIDIA CUDA FP16，同时检查驱动、FP16 和 CUDA／cuDNN 运行库；AMD／Intel GPU 暂不支持。Apple Silicon 使用 MLX Whisper Metal FP16；Intel Mac 使用 CPU。
- MLX 权重与 CPU 缓存分目录，Windows CPU／CUDA 共用原权重；保留下载、校验、取消和磁盘保护。旧任务没有设备字段时按 CPU 解释，切换不自动重跑或外发音频。
- MLX 使用 greedy，不支持 beam search；中英混合按 VAD 区间识别语言，效果不能与 CPU beam 5 等同。CPU 基准不冒充 GPU 结果。
- 界面只展示错误率与内存占用，使用固定公开真人语料比较；文件推理、扬声器回采和真实麦克风分别记录。结果与平台缺口见 [模型实测](../../specs/spec-013-local-model-library/verification.md) 和 [录音实测](../../specs/spec-003-local-transcription/verification.md)。

参考：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[CTranslate2 硬件支持](https://opennmt.net/CTranslate2/hardware_support.html)、[MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)。具体版本以 [技术栈](../../constitution/tech-stack.md) 为准。
