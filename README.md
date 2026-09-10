# Personal Agent Assistant

面向 macOS 和 Windows 的个人工作助手，从会议记录起步，逐步连接周报与历史工作信息，帮助个人回顾讨论、跟踪行动与积累长期记忆。

当前已实现 **默认麦克风录音、WAV / SQLite 本地保存、历史列表与回放**。点击开始会议后采集真实声音，结束并保存后可重新启动应用查找和播放。已接入本地 Whisper small 转写、带时间的文字记录和历史补转写；LLM 纪要、周报和长期 Memory 尚未接入。

## 背景

首个业务目标是 Meeting Agent MVP：持续录音 → 本地转写并保存完整记录 → 结束会议 → 整理结构化纪要。采集必须独立于 ASR / LLM，不能因推理延迟中断。目标与边界见 [产品定义](docs/product-definition.md)、[项目使命](constitution/mission.md) 和 [路线图](constitution/roadmap.md)。

已在 Spec 001 工程基础上完成 [Spec 002](specs/spec-002-meeting-recording-and-storage/spec.md) 的录音与保存闭环，独立验收 [PASS](specs/spec-002-meeting-recording-and-storage/acceptance.md)；[Spec 003](specs/spec-003-local-transcription/spec.md) 接入本地转写，工程与真实样本验证结果见其实施报告，最终验收状态以独立报告为准。会议纪要留给后续 Spec。

## 开发环境安装

以下步骤面向开发者。正式用户版本安装应用后直接使用，由应用自带所需运行时，不要求用户安装 Python、Node.js 或手动启动后台进程。**当前仓库尚未实现这种安装包**，下列源码启动方式需要开发环境。

准备 Node.js **24**、npm **11** 和 Python **3.12**。录音依赖锁定在 `requirements.lock`：sounddevice 0.5.6、CFFI 2.1.1、pycparser 3.0；macOS / Windows wheel 附带 PortAudio。转写使用 faster-whisper 1.2.1 / CTranslate2 4.8.2 / CPU INT8，相关 NumPy、PyAV 与 VAD 运行依赖也已锁定。启动无需模型或 LLM 密钥；开始会议时需要麦克风权限。

macOS：

```sh
python3.12 -m venv .venv
npm ci
node scripts/install-python.mjs
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
npm ci
node scripts/install-python.mjs
```

如果 Python 3.12 命令名称不同，请用对应解释器创建 `.venv`，不要替换系统 Python。启动自动使用项目 `.venv`，无需激活虚拟环境。安装脚本等价于使用项目 Python 执行 `-m pip install -r requirements.lock`。

首次 Node 安装通过 `postinstall: install-electron` 下载 Electron 二进制，需要网络，不下载 ASR 模型。下载失败可参考 [Electron 安装文档](https://www.electronjs.org/docs/latest/tutorial/installation) 配置网络后重试。

## 使用

开发启动：

```sh
npm run dev
```

构建后启动：

```sh
npm run build
npm start
```

应用默认打开“会议记录”。点击“开始会议”时检查权限并打开系统默认麦克风；成功打开后显示“录音中”、实际设备、采样时长与输入音量。点击“结束会议”后等待保存完成，在详情中播放、暂停或拖动进度。录音期间禁用历史回放。

在“设置 → 本地转写模型”点击“下载默认模型”。模型来自 Hugging Face 的 SYSTRAN small 多语言仓库，固定版本与文件校验，约 487 MB，需预留 1.1 GB 磁盘空间，支持取消和失败重试。准备成功后离线推理，音频和文字不外发。首次下载需要网络，下载器沿用系统代理；没有模型也可以先录音。

模型就绪后，新会议自动分批转写。文字按实际时间显示，积压按待处理音频时长计算；录音保存与转写完成分别表示。结束会议后会补齐尾部；历史详情可“生成转写”，失败或重启后可“继续转写”。点击片段定位音频，录音中保持禁播。只有转写活动时可保留进度退出，重新打开后由用户继续。

最小化和切换页面不会停止录音。录音中关闭窗口、退出或重连时，可选择继续录音或停止保存；保存失败会保持窗口可见。休眠、设备失效与异常退出的记录明确标记为中断，下次启动恢复已经落盘的完整音频帧。

开发 UI 只绑定 `127.0.0.1:5173`；Python 控制核心通过标准输入输出通信，不监听业务网络端口。构建预览加载本地资源。`npm run build` 只生成 `out/`，不生成安装包；尚未内嵌 Python、签名、公证或实现自动更新。

### 配置与故障恢复

解释器顺序：`PAA_PYTHON` 可执行文件路径 → 项目 `.venv` → macOS `python3` 或 Windows `py -3.12`。解释器不是 Python 3.12 或缺失时，仍显示窗口与错误提示。

```sh
PAA_PYTHON="/absolute/path/to/python3.12" npm run dev
```

```powershell
$env:PAA_PYTHON = 'C:\path to Python312\python.exe'
npm run dev
```

`.env.example` 仅说明配置，**应用不自动加载 `.env`**。`PAA_PYTHON` 只能包含可执行文件路径，不能附加命令或参数；路径含空格可用。修复依赖后可“重新连接”；更改终端环境变量后需要重启。

macOS 拒绝麦克风后，在系统设置 → 隐私与安全性 → 麦克风中允许应用，再重启。当前开发 Electron 与最终签名安装包的权限归属需分别验证。Windows 需要在系统麦克风隐私设置中允许桌面应用访问；本轮未做 Windows 实机验证。

数据使用 Electron 用户数据目录，独立于仓库及工作目录：macOS 通常为 `~/Library/Application Support/个人工作助手/`，Windows 为 `%APPDATA%/个人工作助手/`。`meetings.sqlite3` 保存元信息，`meetings/<会议ID>/audio.wav` 保存 PCM16 单声道音频；录制临时文件为 `recording.wav`，异常恢复生成 `recovered.wav` 并保留原文件。

转写任务、已完成块和片段存入同一个 SQLite 数据库，模型位于用户数据目录的 `models/whisper-small-<revision>/`。首次升级由 schema 1 事务迁移到 2，先生成 `meetings.schema1.backup.sqlite3`；失败保留原库并回滚。备份不含独立 WAV，手动备份应关闭应用后复制整个用户数据目录。旧程序不能直接读取 schema 2；若需回退，应关闭应用、保存完整当前目录，再使用升级前的数据库与对应音频副本，不能直接修改版本号或删表。

文件缺失、损坏、磁盘不足或数据库版本不兼容会显示错误，不自动清库。保留数据并修复存储条件后重新连接，系统会恢复遗留录音。录音时长按有效帧计算，采样率使用实际设备能力，WAV 接近 4 GiB 格式上限时停止并明确标记中断。

`PAA_TEST_DATA_DIR` 仅指定隔离测试数据根；不要指向真实会议或用测试清理用户数据。同一数据根只允许一个桌面实例运行。

## 开发与验证

| 命令 | 检查内容 |
| --- | --- |
| `npm run typecheck` | 桌面、共享契约、界面与测试类型 |
| `npm run lint` | ESLint 与 React Hooks |
| `npm run format:check` | 工程格式 |
| `npm run format` | 格式化代码，不批量重排治理文档 |
| `npm test` | Vitest 与 Python unittest |
| `npm run build` | main / preload / renderer 构建 |
| `npm run test:asr` | 隔离目录下载/校验默认模型，真实 spawn 工作进程离线转写固定公开人声 |
| `npm run test:smoke` | 构建并启动真实 Electron，验证界面、权限和生命周期 |

Smoke 使用 Electron 自带 Chromium，无需 `playwright install`；它会打开短暂窗口，需要图形会话。默认自动测试不打开真实麦克风，故障与生命周期由 `tests/python/smoke_core.py` 显式注入合成 PCM，经测试专用可执行文件启动；产品没有假录音回退。POSIX 合成启动器在 Windows 跳过。测试数据为临时隔离目录，截图与实录证据位于忽略的 `artifacts/spec002/`。

当前实机为 macOS ARM64；此前录音基线的 macOS / Windows CI 已通过。Spec 003 的 [CI](.github/workflows/ci.yml) 增加真实模型推理和 Electron 转写/重启/回放场景，Windows 不跳过新增场景；结果以对应提交的实际运行记录为准，不能据此声称 Windows 物理麦克风已验证。本轮真实采集、保存、重启播放及合成故障验证见 [实施报告](specs/spec-002-meeting-recording-and-storage/implementation.md)。本机已获麦克风授权，首次授权弹窗尚未实测。

本机执行带模型的 Electron 检查：先运行 `npm run test:asr`，再设置 `PAA_REAL_ASR_SMOKE=1` 执行 `npm run test:smoke`（PowerShell 使用 `$env:PAA_REAL_ASR_SMOKE = '1'`）。CI 明确执行这两步；普通 smoke 不会自行下载大模型，新增真实模型场景只有在该标记开启时运行。模型缓存、公开测试录音和报告位于忽略的 `artifacts/spec003/`；CI 仅上传测试报告和截图，不上传模型。两分钟中文样本的速度、字错误率和真实麦克风流程分别记录，不把模拟 Provider 作为准确率证据。

开发遵循 [AGENTS.md](AGENTS.md)：Spec 决策由协调 Agent 处理，业务代码实施后仍进行新的独立工程验收。

## 目录

```text
src/
├── desktop/              # 主进程、preload、Python 客户端、受限媒体
├── renderer/             # React 中文工作区
├── shared/               # 有限 IPC API 与状态契约
└── python/paa_core/      # 录音、WAV / SQLite、模型、转写与控制核心
tests/                   # 桌面、Python 与真实 Electron 场景
scripts/                 # 安装与验证辅助脚本
docs/                    # 产品定义与架构
constitution/            # 使命、路线与技术约束
specs/                   # Spec、实施与验收报告
.ai/                     # 决策、工作流、交接和规则
AGENTS.md                # 开发规范
```

renderer 启用沙箱与上下文隔离，关闭 Node integration。preload 仅公开有限会议、录音、模型准备与转写 API，播放入口只接受合法会议 ID，并经受限 `paa-audio://meeting/<会议ID>` 访问音频，不能读取任意本地路径。原生采集在用户开始会议时检查麦克风权限；renderer 的麦克风、摄像头等设备权限继续拒绝。不加载远程脚本，阻止外部导航与新窗口。

本地音频、数据库、转写、模型与密钥不得进入版本库。详细约束见 [架构](docs/architecture.md) 和 [技术栈](constitution/tech-stack.md)。

## 许可证

[MIT](LICENSE)。
