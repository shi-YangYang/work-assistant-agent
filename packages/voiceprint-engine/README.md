# 公司声纹引擎

桌面与公司后台共用固定 WeSpeaker 特征模型及 16 kHz 单声道 PCM 预处理。模板为最多 12 个归一化的 256 维向量；`MODEL_ID` 同时标记权重与预处理版本。匹配分数是相似度，不是识别准确率。

安装 Python 3.12 本地包及推理依赖：`pip install './packages/voiceprint-engine[runtime]'`。Linux CPU 部署先从 PyTorch CPU wheel 源安装锁定的 torch／torchaudio，具体安装入口见 `scripts/company/install-voiceprints.py`。

提取入口：

```bash
python -m paa_voiceprints enrollment.wav --model apps/desktop/resources/models/speaker-community-1/embedding/pytorch_model.bin
```

只读取本地权重并校验 SHA256，不联网下载；可以用 `PAA_VOICEPRINT_MODEL` 指向部署后的权重。成功输出 JSON，失败返回 exit 2 和 `{error:{code,message}}`。调用者负责上传校验、单人授权和受限子进程；提取要求 6 秒至 3 分钟规范 WAV，声音不足时拒绝生成模板。

部署时携带原有 `embedding/README.md` 署名及许可。公司录音、员工关联及提取结果是私有业务数据，不能放进这个包或 Git。自动单元测试不用真实录音；公开真人语音的手动验证入口是 `scripts/benchmarks/company-voiceprints.py`。
