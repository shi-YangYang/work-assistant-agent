# 本地转写

- 六款多语言 Whisper 模型，默认 small／中文，支持英文和中英混合；不翻译原文。
- 用户发起下载，固定来源、revision 和 SHA256；校验并加载成功后才就绪，推理不走云端回退。
- 受管 spawn worker 全局一次推理，活动录音优先，积压落到 WAV 和检查点。
- 任务固定模型、语言、设备和解码配置；重转写成功后原子替换，失败保留旧文字和纪要，不自动重跑历史任务。
- CPU 使用 CTranslate2 INT8、beam 5；Windows NVIDIA 使用 CUDA FP16，Apple Silicon 使用 MLX Metal FP16／greedy。默认优先可用 GPU，用户的 CPU 选择持久保留；不支持的硬件明确说明。
- MLX 与 CTranslate2 权重分目录；Windows CPU／CUDA 共用权重。旧任务缺少设备字段时按 CPU 解释。
- 按 VAD 区间解码和识别混合语言，只使用通用提示，不喂参考稿；短上下文可能漏句，长提示可能复读。
- 模型信息展示固定公开真人语料的错误率和内存占用。CPU／GPU、文件推理／麦克风回采分别记录，不能互相冒充。
