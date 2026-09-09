# Decision — 首版采用 Electron 桌面应用

日期：2026-09-09

状态：用户已确认，尚未实施。

## Context

Spec 001 首轮比较了桌面应用与本地网页。用户随后明确决定：“用桌面应用，electron做”。

## Decision

- 首版产品采用桌面应用形态，桌面框架确定为 Electron。
- 目标平台继续包括 macOS 和 Windows。
- 既有 Python 开发方向继续保留，Electron 与 Python 的职责边界、进程生命周期及通信方式在后续选型中明确。
- Electron 版本、界面框架、JavaScript / TypeScript 选择、包管理器、构建与分发方式尚未确定。
- 当前更新产品和技术约束，不代表整个 Spec 已具备实施条件，也不代表应用已运行。

## Reason

采用用户明确指定的产品形态和框架。

## Alternatives

- 本地网页 + 独立 Python 服务：首轮评估曾推荐，但用户未采纳为首版产品形态。
- 其他桌面框架：首版按用户选择使用 Electron，不再作为同等待选方向。

## Consequences

- Spec、Plan、产品评估和技术约束同步为 Electron 已确定、其余选型待定。
- 后续设计围绕 Electron 桌面入口与本地核心的边界展开，保留音频采集和 Agent 推理解耦的要求。
- 保留首轮比较作为历史依据，并明确其中旧建议已被本决策取代。
