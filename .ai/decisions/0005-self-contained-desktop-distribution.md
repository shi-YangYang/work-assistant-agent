# 正式安装包自带运行环境

## 决定

正式 macOS / Windows 应用自带 Python 核心及运行依赖，自动管理内部进程。用户无需安装 Python / Node.js、创建虚拟环境或手动启动服务；应用从自身资源定位内部程序，不能依赖系统解释器或源码目录。

开发模式仍可使用 `.venv` / `PAA_PYTHON`。普通用户界面不承担解释器配置职责；正式包缺失运行时属于安装完整性或应用故障。

## 取舍与后续验收

分进程与统一安装包可以并存，无需仅为免装 Python 重写核心。资源打包及多进程边界见 [分发方案](../../specs/spec-005-desktop-distribution-and-controls/plan.md)。

分发须验证平台构建、资源路径、退出清理及无预装 Python / Node.js 的环境。签名、最低系统版本另行确定；ASR 模型现已由 [本地转写](0007-local-transcription-baseline.md) 选择应用内下载。

依据：[Electron 分发](https://www.electronjs.org/docs/latest/tutorial/distribution-overview)、[PyInstaller](https://pyinstaller.org/en/stable/)。
