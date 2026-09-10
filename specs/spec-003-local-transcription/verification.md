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

## 最终 Provider 纯静音

第二轮独立验收发现早期 beam 1 静音检查不足以代表最终参数，因此仅补此具体缺口：候选 `d7013c94f87c85f081f158012a8e23613e01fdca` 的真实 Provider 加载 small，加载前禁止 socket 连接，输入 PCM16 mono16kHz 的 10 秒全零样本。结果 `words=[]`，加载0.558721秒、推理0.110693秒；不把纯静音结果外推为所有噪声都不会产生错误文字。

证据 `artifacts/spec003/final-provider-silence.json`，`asr_worker.py` SHA256 `14a8662c4e129578a5567b0ec7e37aad6af369fefc0cc1d0b458628bbfc35ac2`；详情见 [第二轮验收](acceptance-round-2.md)。

## 远端 CI

首个候选 `d7013c94f87c85f081f158012a8e23613e01fdca` 的 [实际 run 34448151461](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34448151461) 失败：macOS 35项Python中的慢worker场景等running超时，其他34项和19TS通过；Windows npm test通过，真实small推理及断言完成，但报告打印中文遇到cp1252编码错误，导致步骤失败、后续smoke跳过。

完整失败来自GitHub实际任务/API与已登录Chrome日志页面，保存在 `artifacts/spec003/ci/failure-evidence.json`；两项定向修复见 [CI 返工报告](implementation-ci-rework.md)。不能将先前本机结果或历史 `b9e0e74` 的绿色 CI 当作本轮通过。

第二个候选 `9a8dc781b1fe5e1e7c07d2115975201965de6314` 的 [run 34449407056](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34449407056)：

- Windows 整个任务通过，包含 19 项 TS、35 项 Python、真实 small 推理和新增跨平台转写 smoke；既有 4 项平台受限 smoke 仍跳过。
- macOS 类型、lint、格式、19 项 TS、35 项 Python、真实推理及 6 项旧 smoke 通过；新增转写 smoke 超过 90 秒，worker teardown 又超过 30 秒。原始 error-context 没有具体栈或 DOM，不能据此断言业务根因。
- 两平台的实际 ASR JSON 均为同一锁定样本和参数，CER 2/12=16.67%；macOS 26.6.2 ARM64 推理 9.707 秒，Windows Server 2025 x64 推理 4.765 秒，Python 均为 3.12.10。云 runner 耗时不用于替代 M5 开发机的性能基准。
- 实际下载的附件已核对 GitHub 展示的 SHA256：macOS `605e968cd5c9ce7d490087b66b976f85cf9abf8f70133bb3dcd6c0f0ee514cb2`，Windows `50cc091db73431c787ef0bd640c3647b7ed2824d8ad7aff1a02d3def4bb2c0fd`。解压证据位于 `artifacts/spec003/ci/34449407056-macos/` 和 `34449407056-windows/`。

第三个候选 `9aa788b1cd921564cd510c3b8660bb8f3947ab11` 补齐有界关闭与阶段诊断，见 [smoke 返工报告](implementation-ci-smoke-rework.md)。[run 34450871426](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34450871426) 的 Windows 全部通过，macOS 仍有同一新增场景失败，但这次保留了真实失败点：

- 恢复已有文字及定位于 6.614 秒完成，历史生成于 16.658 秒完成，第一次关闭重启于 19.985 秒完成；取消关闭、保留进度退出均通过，24.397 秒确认重启后的任务为 paused。
- 继续转写后，处理位置从 0 推进至 8460 ms，目标 17124 ms，尚余 8664 ms、error=null。30 秒完成等待在总耗时 56.769 秒处失败，实际状态为 draining。
- 失败清理在 57.627 秒完成，正常回收，无额外 teardown 卡住。由此区分了真实恢复完成等待不足与原本掩盖错误的关闭清理问题。
- 附件通过公开 Actions 附件转发下载，并核对 GitHub API 的 SHA256 `10045628f24286033024bdeb5f340fbcedd15010d809d4bb0c790922f38f3a23` 完全一致；原始证据位于 `artifacts/spec003/ci/34450871426-macos/`。

针对明确的云 runner 推理耗时，调整该集成测试的有界等待预算，保持模型、样本、进度和 completed 断言；开发机性能目标仍使用上文独立实测，不变成云 runner 的 30 秒完成保证。调整依据见 [预算修正报告](implementation-ci-time-budget.md)。

### 最终候选：双平台通过

代码候选 `0b84fe1c6349aa7c413da2d24bc700e43849d97e` 的 [run 34451673078](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34451673078) 已完成，工作流及 macOS、Windows 两个任务均为 **success**。实际验证后才记录通过；随后只有验收和状态文档收尾，不改变被测代码。

| 检查 | macOS ARM64 | Windows x64 |
| --- | --- | --- |
| 依赖、typecheck、lint、format、build | 通过 | 通过 |
| TypeScript / Python | 19 / 35 项通过 | 19 / 35 项通过 |
| 真实 small 推理 | 通过；短样本 8.956 秒 | 通过；短样本 3.500 秒 |
| Electron smoke | 7 项通过 | 3 项通过，4 项既有平台限制跳过 |
| 新增转写 smoke | 所有阶段成功，总计 70.598 秒 | 所有阶段成功，总计 37.004 秒 |
| 重启后的继续处理阶段 | 44.445 秒，最终 completed | 23.239 秒，最终 completed |

两平台新增场景均实际恢复为 paused，再继续处理全部 17124 ms，最终 processedMs=17124、pendingMs=0、error=null；清理正常完成。短样本 CER 均为 2/12=16.67%。macOS 的恢复阶段实际超过旧 30 秒等待，验证了预算修正的必要性，而非通过放宽终态断言取得成功。

官方 API 的最终提交、工作流和步骤证据保存在 `artifacts/spec003/ci/0b84fe1c6349aa7c413da2d24bc700e43849d97e.json`。两个最终附件均已核对官方 SHA256：macOS `c05950572ab3f868163045c05ab85eac574162b00bce6ae5f06ee5c665d3ef30`，Windows `6c356aaebb11829e0501f81212e8c2a9f3b4fdd005a409e8a471a74852f13b04`；解压原始阶段与 ASR JSON 位于 `artifacts/spec003/ci/34451673078-{macos,windows}/`。未重复两分钟基准、声学回采或已通过检查。

Windows 的 4 个既有跳过为 macOS 原生拒绝权限适配和 3 个 POSIX 合成录音 shim 场景。新增真实模型转写场景没有跳过；仍不将 CI 等同 Windows 物理麦克风验证。独立工程验收的最终结论见 [acceptance.md](acceptance.md)。
