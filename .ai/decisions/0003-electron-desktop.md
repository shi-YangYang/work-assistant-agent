# 决策 0003 — Electron 桌面应用

2026-09-09 · 已在 Spec 001 落地。

## 决定与取舍

用户明确选择 Electron 桌面应用，面向 macOS／Windows，保留 Python 本地核心；工程边界见 [0004](0004-foundation-stack.md)。

初轮曾建议本地网页＋Python 服务，以较少的窗口／分发工作先验证会议链路；其代价是服务启动、端口、页面连接与生命周期管理，并非免安装。用户选择统一桌面窗口，此后不再把本地网页或其他桌面框架列为首版待选项。两种形态都需独立管理采集生命周期，UI 形态不决定 ASR 位置或数据外发。

历史比较（含当时官方资料及未采纳建议）见 [Git 归档](https://github.com/shi-YangYang/work-assistant-agent/blob/236a9c4e32785e4d35b0673e2165e237cbe16b2c/docs/product-form-comparison.md)。后续公司 Web 是共享业务的新入口，按 [0011](0011-company-agent-direction.md) 与 Electron 并存，不推翻本决定。
