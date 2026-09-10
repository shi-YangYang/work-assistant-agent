# Implementation Report — Spec 003

## Summary

已实现受控默认模型准备、本地持续转写、Transcript 持久化和定位、历史补转写与暂停继续。实施 Agent 未做最终独立验收，未 commit / push。真实平台与用户麦克风验证由协调 Agent 继续补充，远端 CI 尚待对应提交运行，不能将下列本机结果表述为双平台已通过。

## Files Changed

- `src/python/paa_core/model_manager.py`：固定官方文件清单、字节进度、取消、校验、加载和 staging 发布；下载继承操作系统代理、保留正常 TLS。
- `asr_worker.py`、`transcription.py`：受管 spawn worker、离线 Provider、VAD 区间独立推理、有限音频窗口、活动会议优先、静音边界和时间归属、失败与退出清理。
- `transcript_store.py`、`repository.py`：schema 1→2 增量事务、迁移前 staging 备份与有界忙等待、稳定块/片段 ID、事务检查点、每页最多 50 段。
- `recorder.py`：只增加读取与最终重命名的互斥协调；沿用原录音缓冲、格式和终态。
- `protocol.py`、`src/shared/contracts.ts`、`src/desktop/`：受限模型和转写操作、响应校验、超时后查状态、转写活动关闭确认与暂停退出。
- `src/renderer/Transcription.tsx`、`App.tsx`、`styles.css`：模型准备卡、录音前提示、已保存文字与进度、继续按钮、滚动跟随与片段定位。
- `requirements.lock`、`pyproject.toml`、`README.md`：固定推理依赖和实际操作/备份说明。
- Python 定向测试、真实模型集成脚本、Electron 转写场景和 CI 模型缓存/推理步骤；不上传大模型或录音。

## Important Decisions

### 模型及依赖

- 引擎 faster-whisper **1.2.1**，CTranslate2 **4.8.2**，Python **3.12.14**。
- 模型 `Systran/faster-whisper-small`，MIT，revision **536b0662742c02347bc0e980a01041f333bce120**。
- 下载总量 **486214370 bytes**（以代码 `DOWNLOAD_BYTES` 为准），磁盘检查要求两份文件空间及额外 50 MB，界面提示预留 1.1 GB。
- `model.bin` 483546902 bytes，SHA256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`；其余 config/tokenizer/vocabulary/模型卡的文件大小和 SHA256 固定于 `model_manager.FILES`。
- macOS ARM64 实际安装了原生 wheels。PyPI 元信息已确认 CTranslate2 / PyAV / ONNX Runtime 的 Windows x64 Python 3.12 兼容 wheels；Windows 实际安装和运行仍由 CI 验证。
- 下载必须由用户显式发起；推理只加载固定本地目录，并设置离线开关。真实集成测试进一步在工作进程禁用 socket 连接后完成加载和推理。

### 语音边界与资源

最终默认配置：CPU INT8、4 个线程、beam size 5、中文转写、word timestamps、temperature 0、关闭跨窗口文本条件，通用 prompt 仅“简体中文”（没有参考稿内容）。目标块约 10 秒，配置范围 5～15 秒；在目标前最多 5 秒内优先选择静音边界，前后各最多 4 秒上下文。

首轮真实样本发现，直接把多个 VAD 语音段拼成一次解码会在换说话人时丢掉后句。实施改为每个 VAD 区间独立解码，并通过静音切分和词时间中点归属避免重叠重复。较长通用 prompt 曾在短噪声窗诱发复读，已缩为上述短语言提示。最终样本没有原先的确定性漏句或重复；模型同音词和个别繁体识别误差原样保留。

调度器只持有当前窗口描述和 PCM，完整积压保存在原始 WAV 及 SQLite 处理位置。录音写入已接受帧后才发布帧水位；短读关闭 WAV 句柄后再推理，收尾重命名与读取互斥。原始帧区间连续，静音块也提交进度，最终尾块到达目标帧数才完成。

### 持久化

迁移前备份先写 `meetings.schema1.backup.staging`，成功关闭后发布到 `meetings.schema1.backup.sqlite3`；失败移除未完成 staging，原库保留。备份忙等待有 2 秒上限。新增任务、块和文字表不改旧会议 ID / 元信息 / 音频。每个块的片段与处理位置同事务提交，唯一约束防止重复；重启先恢复录音，再把未完成转写标为 paused，由用户继续。

## Tests

本次涉及持久化迁移、IPC、安全边界、下载和进程基础设施，按 S3 进行对应检查；通过的无关检查没有为后续文档改动反复执行。

### 已通过的本机工程检查

- `npm run test:unit`：**19 项通过**。
- `npm run typecheck`、`npm run lint`、`npm run format:check`：通过；新增 smoke 生命周期等待修正后的最终类型、lint 和格式检查也已通过。
- `.venv/bin/python -m unittest discover -s tests/python -v`：**31 项通过**（20 项原有协议/录音、11 项新增转写）。
- 模型取消/worker 退出调整后，`... -p test_transcription.py -v`：**11 项通过**，覆盖备份失败和数据库占用、DDL 回滚、块事务和重放、页大小、尾块、恢复、缺失音频、慢 worker 期间帧增长及控制响应、崩溃/超时清理、下载取消/重试和损坏文件。
- `npm run test:asr`：实际 spawn 工作进程和 small 推理通过，4.281 秒公开真人中文用约 **1.230 秒**完成；文字和时间保存、重复开始幂等，网络连接在 ASR worker 内禁止。
- `npm run test:smoke`：实际 Electron 构建通过，**6 项原有 smoke 通过**；新增场景首轮因本机已有一次失败运行保留的公开 fixture 而误断言仅两条历史，已改为使用具体会议 ID 定位，未删除测试数据或放宽业务断言。
- `PAA_REAL_ASR_SMOKE=1 npx playwright test tests/smoke/transcription.spec.ts`：新增实际模型 Electron 场景通过（最新约 **14.2 秒**），覆盖就绪、保存文字恢复、片段定位、非法游标、历史生成、重启一致、继续处理关闭保护、保留进度退出、重启 paused 和继续完成。新增场景在 CI 明确开启，不依赖 POSIX shim 或真实麦克风。
- CI YAML 定向检查确认缓存路径为 `artifacts/spec003/real-asr/models`，真实 ASR smoke 标记必开；上传范围为报告和截图。
- `git diff --check`：通过。

### 真实模型质量与性能

固定样本来自 **Google FLEURS** 的 11 条真人中文 validation 录音（含 WiFi 术语），在看到任何 ASR 结果之前选定；CC-BY-4.0，dataset revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`。转 PCM16 mono 16kHz，仅拼接 0.5 秒间隔，共 **121.76 秒**。样本、数据集人工参考文字、每条 hash/边界和组合 hash 留在 `artifacts/spec003/reference-audio/`。

设备 macOS 26.4 / ARM64（Apple M5 / 16 GiB）；最终小模型加载 **0.412 秒**，16 个业务块累计 **44.659 秒**，峰值 RSS **1071710208 bytes**（包含测试脚本全段与分块的进程峰值）。首块推理 **2.906 秒**，实际录音首批文字延迟另由 Electron 实录计时，不能仅将音频窗口等待加推理时间当作实测。

协调 Agent 独立计算 CER：NFKC + casefold，保留 Unicode 字母与数字，仅去空白/标点；不做繁简、同音或数词等价。参考 **276 字符**，全段 **15/276 = 5.43%**，业务分块 **18/276 = 6.52%**，均只有替换，没有插入或删除。个别繁体字也按错误计入。此前漏掉的亚马逊河、WiFi、非洲、最终均恢复。具体基准与 SHA 绑定证据在 `benchmark.json`、`reference-evaluation-revised.json`，首轮失败证据保留为 `benchmark-initial.json` 和 `reference-evaluation-initial.json`。

短真人样本来自固定 Wenet commit `d17059667d6afe0680d19b3a4948ab825ef25105` 的 AISHELL 测试音频，用于跨平台实际 ASR 集成，SHA256 `2f9fc9c912bb71c85fb286cb88b599c81efb8f727c727a5ea8f6d1c89c55ac13`。输出“廣州市法地产中介协会分析”，人工参考“广州市房地产中介协会分析”，CER 2/12 = 16.67%，识别错误没有被产品修正或写成无误。完整证据 `artifacts/spec003/real-asr.json`。

### 应用下载与真实麦克风

协调 Agent 已在独立 Electron 窗口通过设置页实际发起受控下载，约 45 秒完成下载、校验并就绪，期间录音保持 idle；证据 `artifacts/spec003/interactive/session.json`、`model-state.png`。下载沿用用户系统代理，未硬编码开发机代理。

协调 Agent 首轮物理链路使用内置麦克风完成40.064秒录音及相同目标帧转写，但公开音频播放起始延迟和较低声压影响质量，尚不能作为质量通过证据；正在改进独立测试输入条件后复测，不改 Provider 参数。真实麦克风流程由协调 Agent 单独执行和补记。本报告不把合成输入、文件推理或公开录音文件直接注入当作物理麦克风讲话证据。

## Known Limitations

- 本报告写作时 Windows CI、真实麦克风流程及最终独立验收尚待协调 Agent 回填；不得标记为双平台全部通过或最终 PASS。
- 目标是分批文字，逐字即时字幕不在范围内。真实中文样本的时间和错误率不能外推所有硬件、口音与会议噪声。
- 识别可能有同音和繁简混用；本轮不做人工编辑、热词训练、自动文本纠正或纪要。
- 启动就绪需要本地完整文件校验和 worker 加载；实际录音仍不依赖模型可用性。
- 默认 smoke 保留原有 Windows 4 项平台受限跳过；CI 新增的真实转写场景通过显式标记必跑。Windows 物理麦克风未因 CI 自动获得验证。
- 下载仅固定官方模型，不支持任意镜像/URL、断点续传、模型商店、GPU设置或云回退。当前依然是开发预览，无安装包/自带运行时交付。

## Remaining Questions

无待确认的产品决策。待协调 Agent 完成真实麦克风证据、运行对应提交的 macOS / Windows CI，并安排新的独立验收；业务实现不得自行给最终 PASS。

## 协调 Agent 后续证据

第二轮物理声学回采、重启和实际定位播放已完成：37.035 秒、首字 18.383 秒、CER 15.56%。具体方法、原失败与测量边界见 [实际运行证据](verification.md)。首轮独立验收发现暂停竞态，正在按 [返工目标](rework.md) 修复；本段不将工程标为最终通过。
