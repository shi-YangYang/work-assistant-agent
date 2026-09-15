# 验证记录 — Spec 013

本页只记录模型比较的实际证据；功能与独立验收由本 Spec 的实施／验收记录维护。真实矩阵已经收尾；17 组完成，1 组失败保留，不能把失败组称为通过。

## 固定语料与许可

2026-09-14 在新模型输出前冻结样本，清单为 ignored `artifacts/spec013/dataset-manifest.json`，SHA256 `c29ec827a1a4a159b21fff94c80d3a4ed6e4236406a9487a6476fa1593e85a7a`。每组按验证集行号升序取整条真人录音，累计原语音至少 120 秒且至少 10 条；中文／英文从第 20 行开始，避开 Spec 003 调参所用中文行。混合组仅纳入原参考稿同时含汉字与英文、且数据标签为 mixed 的原始话语，没有把单语拼成混合句。各组录音之间加 0.5 秒静音用于统一业务分块，未裁去错误或困难片段。

| 组别 | 公开来源与固定版本 | 行号 | 原音频／条数／分母 |
| --- | --- | --- | --- |
| 中文 | [Google FLEURS](https://huggingface.co/datasets/google/fleurs/tree/70bb2e84b976b7e960aa89f1c648e09c59f894dd)，cmn_hans_cn validation | 20–29 | 123.84 秒／10 条／368 字 |
| 英文 | 同版本 FLEURS，en_us validation | 20–35 | 124.80 秒／16 条／319 词 |
| 中英混合 | [CAiRE ASCEND](https://huggingface.co/datasets/CAiRE/ASCEND/tree/737e9800ae31be9932ba8464c80366559bd28424)，main validation | 1, 4, 5, 7, 10, 11, 15, 16, 21, 23, 28, 30, 35, 37, 41, 43, 57, 62, 67, 68, 78, 83, 86, 95, 119, 134, 142, 158, 181 | 120.99 秒／29 条／470 混合单位 |

FLEURS 的[固定版本数据卡](https://huggingface.co/datasets/google/fleurs/blob/70bb2e84b976b7e960aa89f1c648e09c59f894dd/README.md)声明 CC-BY-4.0（Conneau 等，2022）。ASCEND 的[固定版本数据卡](https://huggingface.co/datasets/CAiRE/ASCEND/blob/737e9800ae31be9932ba8464c80366559bd28424/README.md)明确数据为 CC-BY-SA-4.0（HKUST CAiRE；Lovenia 等，2022）；没有将 GitHub 训练代码的 MIT 许可当作音频许可。卡片快照保存为 `*-dataset-card.md`，原音频、参考稿及逐行 hash 留在 artifacts，不随应用分发；应用内保留来源及归属。

组合 WAV SHA256：中文 `e3d327541b10d7089b312ad3d139fcbeacd8918e513f932598b59b41ec6c1ee7`；英文 `2efdc58c3aeae1fd0ce93f11b4c244658f556a17b5d38045cd24039fc804d421`；混合 `b29b010e0c6133a285c853af2d7d6ed91da9ece03234d1644eef41fc9ec9b2b0`。PCM16 mono 16 kHz，含间隙的总时长分别 128.34／132.30／134.99 秒。

## 口径与重现

参考机 Apple M5／16 GiB、macOS 26.4 ARM64，Python 3.12、faster-whisper 1.2.1／CTranslate2 4.8.2。每模型／语言使用新的独立进程，CPU INT8、4 线程、beam 5，调用实际 `WhisperProvider`、`config_for_mode`、`choose_boundary`、`owned_segments`，10 秒目标块、前后最多 4 秒上下文，VAD 参数与产品相同。没有将完整音频一次性推理的结果冒充业务分块结果。

错误统计先 NFKC＋casefold，仅保留 Unicode 字母／数字，不做繁简、同音或数字词等价。CER 按字符；WER 按标点／空白分词、移除撇号；MER 按单个汉字＋连续非汉字字母／数字分词，连续数字为一个单位。参考稿保留数据集的数字写法、括号中的外文和 `[UNK]` 标注，不事后更改；它们经同一规则分词计入分母。编辑距离按累计替换／删除／插入除以全组参考单位数，不把错误率转换为通用“准确率”，不直接比较跨语言指标。并列最短路径固定优先匹配、替换、删除、插入。程序版本与参数在结果中保留；输出不参与样本挑选或参考稿修改。

峰值内存为独立基准转写进程在模型加载、导入、样本解码、末尾静音及编辑距离评分阶段的峰值 RSS；脚本在评分完成后读取，包含基准包装与评分开销，没有声称已扣除它们。已完成组保持相同采样阶段，失败组不借用数值；macOS `ru_maxrss` 原值为 bytes。不是模型文件大小、整应用占用或其他机器保证值。每组额外运行 10 秒纯静音，单独记录输出，没有错误率分母。耗时仅在内部 artifacts 中用于 worker 等待预算，不展示在产品效果区域。

重现入口为 [scripts/benchmarks/local-asr.py](../../scripts/benchmarks/local-asr.py)（Spec 015 仅迁移路径）：先 `prepare` 冻结公开语料，再对每个模型和语言串行运行 `run --model <id> --mode <zh|en|mixed> --cache <日常 models 目录>`。模型版本从 `paa_core.model_catalog.CATALOG` 获取，先在应用中下载／校验所选模型即可，不需要私有 manifest。脚本拒绝覆盖已冻结清单或已有结果；数据服务版本变化时拒绝静默换样本。需要既有桌面 Python 依赖与已校验固定模型缓存，不读取用户录音、模型密钥或默认设置，不创建虚假会议。完整清单、原始输出、块时间、替换／删除／插入和静音结果分别在 `dataset-manifest.json`、`result-<模型>-<语言>.json`；UI 只引用 `apps/desktop/src/shared/local-model-benchmarks.json` 中的轻量指标与必要条件。本页结果仍对应原实验版本，不代表目录迁移后重跑了矩阵。

结果中的 `providerSha256` 是组结束时整个 `asr_worker.py` 的 hash，不是启动时 hash。矩阵期间该文件的 worker 生命周期代码有修改，但 `WhisperProvider`、语言配置与业务分块未改变；后启动的 large／medium 进程另外记录 `providerStartSha256`。没有用文件级 hash 的非解码变化要求重复已完成矩阵。

## 实测结果

18 组均已实际尝试：**17 组完成，base／中文 1 组失败**。下表的内存为 GiB（bytes ÷ 2³⁰）；完整编辑次数及原始 bytes 见共享结果与 artifacts。未完成组没有填估计错误率或借用其他语言的内存。

| 模型 | 中文 CER · 峰值内存 | 英文 WER · 峰值内存 | 混合 MER · 峰值内存 |
| --- | --- | --- | --- |
| tiny | 27.17% · 0.45 GiB | 11.91% · 0.43 GiB | 92.77% · 0.45 GiB |
| base | 测试未完成／未取得内存值 | 9.72% · 0.65 GiB | 42.34% · 0.65 GiB |
| small | 14.40% · 0.96 GiB | 5.33% · 0.92 GiB | 32.55% · 0.90 GiB |
| medium | 5.71% · 1.90 GiB | 5.02% · 1.89 GiB | 34.68% · 1.92 GiB |
| large-v3-turbo | 7.34% · 1.83 GiB | 4.39% · 1.98 GiB | 42.77% · 1.98 GiB |
| large-v3 | 8.70% · 2.62 GiB | 5.02% · 3.11 GiB | 29.57% · 2.91 GiB |

这些数字不保证模型参数越大越好。例如本组中文 medium 字错率最低，英文 turbo 最低；混合 large-v3 的累计错误率最低，但仍有明确遗漏。六个模型使用同组音轨与规则，没有为改变排序重新选择样本。

### 运行预算对照（仅开发证据，不进入产品评分）

| 模型 | 已完成组最大加载秒数 | 已完成组最长单块秒数 | 相对当前 180 秒推理预算余量 |
| --- | --- | --- | --- |
| tiny | 0.178 | 3.571 | 176.429 秒 |
| base | 0.421 | 7.144 | 172.856 秒 |
| small | 0.665 | 12.272 | 167.728 秒 |
| medium | 1.599 | 38.281 | 141.719 秒 |
| large-v3-turbo | 1.827 | 55.031 | 124.969 秒 |
| large-v3 | 3.340 | 84.561 | 95.439 秒 |

所有成功组的实测加载均小于当前 90 秒加载预算，单块均小于 180 秒推理预算。最大单块为 large-v3／混合的 84.561 秒：旧 90 秒推理预算仅剩 5.439 秒余量，因此实施将加载／推理预算分别设为 90／180 秒。该调整仅涉及受管 worker 的请求等待边界，未改变 Provider、配置或分块，所以没有重跑矩阵。以上为参考机观测，不保证更慢机器或任意音频都在预算内；base／中文已失败，不列作预算通过。

### 异常保留

- **base／中文未完成**：第 14 个业务块前已处理约 100.51 秒，随后 Provider 触发 500 个输出词的单块保护（`ASR output exceeds a bounded audio window`）。保留 `run-base-zh.log` 与 `result-base-zh.failure.json`。首次失败进程退出前没有采集 RSS，记录为 null；不放宽上限、改参考稿或重跑到成功来补数字。
- **混合误识别／误译**：ASCEND row 5 的“偶尔跟 friends 传传 messages”被 small 写成“Or a French Chanchon message”；large-v3 将其中的英文部分转为中文。原语言保留并不完美，繁简差异、空格／词形和这些误识别均按冻结规则计入 MER。
- **关键内容／近整句遗漏**：large-v3 在 mixed row 119 仅保留中文引子，漏掉关于 Hong Kong／mainland 的主要英文内容；turbo 在 row 142 的公司部门话语位置输出重复“多少钱”，原信息被替换。这些失败没有从分数中剔除，较低平均错误率不代表逐句完整。
- **静音**：17 个成功组末尾的 10 秒全零 PCM 均得到空输出；base／中文因前序失败未执行这项检查。纯静音结果不代表环境噪声或所有静默片段都没有幻觉。

## 适用范围

这是小规模固定公开语料的本应用参考机实测，不是全量 FLEURS／ASCEND 榜单或真实公司会议准确率保证；未覆盖远场多人重叠、专业词表、口音全分布和所有噪声。没有 Windows 模型矩阵／GPU／最低配置实测，不外推 macOS 内存结果。
