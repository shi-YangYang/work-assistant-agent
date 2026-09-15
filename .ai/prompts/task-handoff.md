# Task Handoff — 当前状态

2026-09-15 · Electron CPU／GPU 选择及 medium GPU 实测已完成。用户暂停共用后端方向，本轮未开 Spec，由主 Agent 独立实施与验证；用户现已要求 commit／push，实际结果以 Git 记录和本轮交付为准。

- 实现：Apple Silicon 使用 MLX Metal，Windows 使用可用 NVIDIA CUDA，否则 CPU；六款 MLX 权重独立缓存，旧 CPU 权重和历史任务保留。依据见 [决策 0007](../decisions/0007-local-transcription-baseline.md)，使用方式见 [使用指南](../../docs/setup.md)。
- 已通过：38 项相关 Python 测试、8 项 core-manager 测试、桌面类型／改动文件 Lint 和格式整理。接口测试发现新错误码未透传，已修复并定向复测。
- 真实验证：日常目录 `npm run dev`，M5 显示 CPU／GPU 名称，切换及重启保留选择；medium GPU 下载／校验就绪，中文、英文、中英混合公开语音与 CPU 中文转写通过。脚本与原始结果在忽略的 `artifacts/desktop-inference-device/`，未创建测试会议或触碰服务凭证。
- 打包核心已包含并成功启用 Metal；从项目外目录运行，离线 GPU 转写、VAD 与进程回收通过。首次诊断因沿用旧中文配置输出繁体而断言失败，改用应用的中文配置后通过，原日志保留。未运行双平台安装包验收、Windows GPU 实机或远端 CI。
- 日常环境当前为 GPU／medium／中英混合，原六款 CPU 模型保留；开发窗口来自 `npm run dev`。工作区留在 `dev`；推送后由用户通过 PR 决定合并到 `main`。

后续增补：medium GPU 已使用原冻结语料完成三语言定量评测，错误率、进程 RSS 和 GPU 分配峰值写入“识别效果与模型信息”，按后端／模型版本选择。结果与口径见 [Spec 013 实测增补](../../specs/spec-013-local-model-library/verification.md#2026-09-15medium-gpu-增补)。已检查日常 GPU 页面显示与 renderer 类型，本次增补未重跑其他模型、打包或 CI。
