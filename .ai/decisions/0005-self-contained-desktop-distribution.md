# Decision — 正式桌面分发自带运行环境

日期：2026-09-09

## Context

用户在查看 Spec 001 骨架后询问，为什么需要本地核心、是否可以直接打包，以及是否要用户自行安装 Python。当前代码从开发环境的解释器启动核心，安装包与内置运行时尚未实现；这个事实不能被表述成最终用户必须准备开发环境。

## Decision

- 正式 macOS / Windows 用户安装桌面应用后即可启动，无需自行安装 Python、Node.js、创建虚拟环境或手动运行后台服务。
- Python 核心是内部处理模块，随应用分发并自动管理生命周期。分进程运行与统一安装包可以同时采用。
- 正式启动从应用资源中定位内部程序，不依赖用户系统 Python 或项目源码目录；开发环境仍可使用 `.venv` 和显式解释器路径。
- 普通用户界面不承担 Python 环境配置职责；运行时缺失应作为安装完整性或应用故障处理。
- 当前只澄清交付约束，不表示已生成可分发安装包，也不改变 Spec 001 已完成的开发骨架范围。

## Reason

桌面应用应承担自身运行依赖的分发和生命周期管理。采用 Python 是沿用本地 ASR 的技术方向，与用户是否需要安装 Python 是不同层面的选择；单独实现当前空界面并不需要 Python。

## Alternatives

可封装 Python 程序及依赖，也可内置独立 Python 运行时；具体打包工具尚未选择。PyInstaller 是可行候选之一，不能在尚未制作、测试平台产物前声称集成已经完成。仅为免安装 Python 而重写整个核心不是必要条件。

## Consequences

后续分发工作需完成内部程序构建、资源路径适配、平台安装包与退出管理验证，并在没有预装 Python / Node.js 的目标环境验证启动。当前开发 README 已明确受众；ASR 模型随包或应用内下载方式、签名及最低系统版本另行确定。

## Sources

查阅日期：2026-09-09。

- [Electron 分发说明](https://www.electronjs.org/docs/latest/tutorial/distribution-overview)：应用资源打包与平台交付。
- [PyInstaller 官方说明](https://pyinstaller.org/en/stable/)：Python 程序可以连同依赖打包，使用者无需安装 Python；各目标平台需要相应构建环境。
