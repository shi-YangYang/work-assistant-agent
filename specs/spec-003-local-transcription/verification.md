# Verification — Spec 003 实际运行证据

记录日期：2026-09-10。本文由协调 Agent 记录实际运行事实；独立验收结论见 acceptance.md，不将某一项通过等同整个 Spec 完成。模型、数据库、原始录音和完整输出保留于 ignored `artifacts/spec003/`，不提交 Git。

## 环境与默认配置

macOS 26.4 / ARM64，Apple M5 / 16 GiB；Node 24、Python 3.12.14，faster-whisper 1.2.1 / CTranslate2 4.8.2。模型 `Systran/faster-whisper-small`，revision `536b0662742c02347bc0e980a01041f333bce120`，CPU INT8 / 4 线程 / beam 5，中文、temperature 0、word timestamps，短提示仅“简体中文”。约 10 秒目标块、静音切分、上下文前后各最多 4 秒，VAD 区间分别解码。未向模型提供参考稿。

## 固定真人语音质量与计算耗时

来源：[Google FLEURS](https://huggingface.co/datasets/google/fleurs)，CC-BY-4.0，dataset revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`，`cmn_hans_cn` validation，行 1、2、3、5、6、7、8、9、10、11、12。先固定样本，再查看转写结果；使用数据集人工参考稿，含 WiFi 英文术语。转换 PCM16 mono 16 kHz，原音频不裁剪，句间加入 0.5 秒间隔，共 121.76 秒。

组合音频 SHA256：`acbb245530b0a744c3446afa0316debc5eac8378da057d3068a29750525c3ebb`。独立 CER 计算采用 NFKC + casefold，只保留 Unicode 字母和数字；不做繁简、同音或数词等价。

| 项目 | 实测 |
| --- | --- |
| 参考字符 | 276 |
| 最终全段 CER | 15 / 276 = 5.43% |
| 最终业务分块 CER | 18 / 276 = 6.52% |
| 分块插入 / 删除 | 均为 0；原漏句已恢复 |
| 模型加载 | 0.412 秒 |
| 16 块累计推理 | 44.659 秒，低于 121.76 秒音频时长 |
| 第一块计算 | 2.906 秒；这不是实录首字延迟 |
| 进程峰值 RSS | 1071710208 bytes，约 1.0 GiB；含整段及分块基准运行 |

首轮 beam 1 / 较短上下文及 VAD 拼接解码虽然 CER 小于 20%，却漏掉确定性句首和 WiFi 整句，因此没有通过边界要求。修正后在相同样本复测，未选择性删除失败音频或修改参考稿。初轮与最终证据分别为 `benchmark-initial.json` / `reference-evaluation-initial.json` 和 `benchmark.json` / `reference-evaluation-revised.json`。

以上是固定清晰语音样本结果，不代表所有口音、噪声环境或电脑均达到相同质量 / 实时速度。

## 应用内首次模型下载

使用独立 Electron 窗口及全新隔离用户数据目录，在设置中实际点击“下载默认模型”，观察真实字节进度，约 45 秒后下载、校验和加载完成并显示就绪。总下载量 486214370 bytes，录音状态保持 idle。网络采用用户现有系统代理，应用没有硬编码开发机代理、关闭 TLS 或要求输入模型路径。

取消、文件损坏、失败重试另由实施阶段定向测试覆盖；缓存就绪后真实 spawn worker 内禁止 socket 连接仍能加载并转写，证据见 `real-asr.json`。这与首次下载需要联网分别记录。

## 真实物理麦克风与 Electron 闭环

用户明确选择：切换到内置麦克风和扬声器，由应用播放公开人声做采集验证。实际设备为 MacBook Pro 麦克风 / 扬声器，48 kHz；沿用系统输出音量 25%、输入 100%，没有修改系统设置。公开语音由测试助手通过系统音频播放器播放，声波经真实物理麦克风进入产品正常录音链路，未绕过 Recorder 注入 PCM。这不是用户现场发言，不能冒充用户真实会议。

从已固定的 FLEURS 样本中取行 1、2、3、11，共 31.74 秒，含 WiFi。第一轮播放工具晚约 9 秒启动、声压较低，40.064 秒录音虽保存并转写，但不作为质量 / 延迟通过证据，保留 `interactive/session-first-recording.json`。第二轮仅改进测试播放时机和公开参考音频分句增益，未修改 Provider、原始参考或录音。分句增益受峰值 0.95 限制，原始文件保留；归一化播放文件 SHA256 `56b28914768bbc149c46fcaebac871f2aa5fb952e3a8fb1eaf09e23f1c3f0b9c`。

第二轮事实：

- 从点击开始到播放启动 0.154 秒；首批持久文字出现于 18.383 秒（轮询间隔 0.7 秒），满足当前参考设备 20 秒目标。
- 实际录音 37.035 秒，1777664 帧，PCM16 / 单声道 / 48000 Hz；录音终态 completed，先完成保存，此时转写仍为 draining。
- 随后补齐全部 1777664 帧，转写 completed、pending 0，最终 4 个片段；中文参考 90 字符，编辑距离 14，CER 15.56%，保留 WiFi。声学回采质量低于原文件，错误原样保留。
- 重启同一隔离数据目录后，转写状态和片段 ID、文本、时间完全一致。通过历史打开录音，点击第二个文字片段定位 9.266 秒；实际播放推进至 9.9418 秒、readyState 4，随后暂停并关闭测试应用。
- 录音 SHA256 `abc13c334ee13948ac871d8c9bd1d3354a94f845d1f728ce03d4c773e4ed4c42`。证据：`microphone-evaluation.json`、`interactive/session.json`、`microphone-restart.json`、`microphone-playback.json` 及录音中 / 完成 / 重启定位截图。

实录首批延迟采用 31.74 秒公开语音的声学回采，累计推理速度与中文基准采用独立的 121.76 秒原始参考样本；二者不混称同一次测量。Windows 物理麦克风、首次 macOS 权限弹框、最低配置与安装包未因此得到验证。

## 远端 CI

待暂停竞态返工后推送最终候选提交，实际运行 macOS ARM64 / Windows x64 的依赖安装、真实 small 推理和相关 Electron 场景，再补充提交 SHA、run 链接及各平台通过 / 跳过数量。历史 `b9e0e74` 的绿色 CI 不作为本次新增 ASR 的通过证据。
