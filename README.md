# Personal Agent Assistant

面向 macOS 和 Windows 的个人工作助手，从会议记录起步，逐步连接周报与历史工作信息，帮助个人回顾讨论、跟踪行动与积累长期记忆。

当前已实现 **默认麦克风录音、WAV / SQLite 本地保存、历史列表与回放**。点击开始会议后采集真实声音，结束并保存后可重新启动应用查找和播放。已接入本地 Whisper small 转写、带时间的文字记录和历史补转写；本轮接入可配置的在线模型纪要，验证状态见 [Spec 004](specs/spec-004-meeting-minutes/spec.md)。公司员工消息、工作进展和日报／周报另由 [独立 Web 与服务端](#公司工作助手-webspec-008) 提供；长期 Memory 尚未接入。

## 背景

首个业务目标是 Meeting Agent MVP：持续录音 → 本地转写并保存完整记录 → 结束会议 → 整理结构化纪要。采集必须独立于 ASR / LLM，不能因推理延迟中断。目标与边界见 [产品定义](docs/product-definition.md)、[项目使命](constitution/mission.md) 和 [路线图](constitution/roadmap.md)。

已在 Spec 001 工程基础上完成 [Spec 002](specs/spec-002-meeting-recording-and-storage/spec.md) 的录音与保存闭环，独立验收 [PASS](specs/spec-002-meeting-recording-and-storage/acceptance.md)；[Spec 003](specs/spec-003-local-transcription/spec.md) 接入本地转写，工程与真实样本验证结果见其实施报告，最终验收状态以独立报告为准。[Spec 004](specs/spec-004-meeting-minutes/spec.md) 补充多服务模型管理及自动会议纪要。

## 开发环境安装

以下步骤面向开发者。正式用户版本安装应用后直接使用，由应用自带所需运行时，不要求用户安装 Python、Node.js 或手动启动后台进程。安装测试包的构建方法见下方“制作安装包”；下列源码启动方式需要开发环境。

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

## 制作安装包

在对应系统与架构构建：macOS ARM64 生成 DMG，Windows x64 生成 NSIS 安装程序。安装包自带 Python 3.12、录音和转写运行依赖，模型仍在应用内下载；用户无需安装开发工具。测试包暂不包含正式代码签名或公证，macOS 保留 ad-hoc 签名。

完成上面的开发环境准备后运行：

```bash
node scripts/install-build-python.mjs
npm run package
```

产物位于 `dist/desktop/`。`npm run package:dir` 仅生成未封装的应用目录。构建依赖锁定于 `requirements-build.lock` 与 `package-lock.json`，不用 pip 在线安装运行时到用户机器。应用用户数据路径与开发版相同，安装和卸载不会清除录音、模型和服务设置；请勿同时运行两份应用。

macOS 首次从开发版切换到安装版，系统可能询问是否允许访问“个人工作助手 Safe Storage”钥匙串条目。允许应用访问后即可沿用原服务密钥，无需重新填写 API Key。测试包使用 ad-hoc 签名，重新构建后的应用可能再次请求授权。

`npm run test:package` 验证实际应用资源内的冻结核心、无外部 Python/Node 的启动、离线 small 推理、VAD、证书和合成录音暂停续录；先通过 `npm run test:asr` 准备公开测试素材。CI 另外安装 DMG/NSIS 产物并启动桌面检查。它们与本机真实麦克风验收的范围不同，实际结果见 [Spec 005 实施报告](specs/spec-005-desktop-distribution-and-controls/implementation.md)。

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

侧栏直接进入会议记录、模型服务管理、本地转写模型和外观。外观可选择浅色、深色或跟随系统，并记住选择。点击命令入口或按 `Cmd/Ctrl+K` 可查找这些页面和当前可用操作；它不搜索会议全文。

已结束会议默认打开纪要，录音中默认显示文字记录；两个页签共享播放器，切换保留阅读与播放进度。点击纪要引用可查看上下文、进入对应原文并定位录音。播放器支持拖动定位、前后跳转 10 秒、倍速、音量和快捷键，离开会议时停止回放。

会议列表支持按名称、文字记录和纪要关键词搜索，并按本地日期筛选；搜索覆盖完整历史，点击命中片段进入对应文字或纪要位置，返回保留筛选。列表或详情的“…”菜单可重命名和删除已结束会议。删除确认后永久清理关联音频、转写和纪要；忙碌会议不可删除，清理失败可重试，重启会继续未完成的清理。

详情可复制已有纪要，或通过系统保存对话框导出 Markdown／TXT。导出可选纪要、完整文字或两者，并可保留片段时间戳；导出使用一致快照，未完成资料会明确标注。取消保存不会写入文件，已有导出文件不会随会议删除。验证状态见 [Spec 007](specs/spec-007-meeting-library/spec.md)。

录音可暂停后继续，暂停时关闭麦克风且不补静音，内容追加到同一条音频。切换到其他页面时，紧凑录音条保留状态、有效时长和暂停／继续、结束及返回入口。

在“设置 → 本地转写模型”点击“下载默认模型”。模型来自 Hugging Face 的 SYSTRAN small 多语言仓库，固定版本与文件校验，约 487 MB，需预留 1.1 GB 磁盘空间，支持取消和失败重试。准备成功后离线推理，本地转写不外发音频和文字；在线纪要按下述配置发送文字。首次下载需要网络，下载器沿用系统代理；没有模型也可以先录音。

模型就绪后，新会议自动分批转写。文字按实际时间显示，积压按待处理音频时长计算；录音保存与转写完成分别表示。结束会议后会补齐尾部；历史详情可“生成转写”，失败或重启后可“继续转写”。点击片段定位音频，录音中保持禁播。只有转写活动时可保留进度退出，重新打开后由用户继续。

在“模型服务管理”添加或选择服务，在“连接配置”填写包含版本路径的 API Base URL（例如 `https://example.com/v1`）和密钥，在“模型与推理”选择模型和参数。切换页面、页签或服务会保留未保存草稿，不会自动提交。“获取模型”读取该服务返回的目录，可搜索并选择，也可手动填写模型 ID。目录可见不代表已取得生成权限；“测试连接”会用当前表单发送一次小型生成请求，可能产生 API 费用。

每家服务按模型保存多个推理预设：选择“服务默认”时不额外发送推理参数；简单模式把自定义值作为 `reasoning_effort` 发送，高级模式可填写服务文档支持的 JSON 参数。预设名称与实际请求值独立，应用不猜测新型号的推理档位。新建服务默认勾选“使用流式接口”，不支持流式的服务可关闭。修改参数后需重新测试；参数被接受不代表服务一定按预期执行。

点击“保存服务”，再点击“用于纪要”选择接收方。可保存多家服务，只有当前选中的服务用于纪要。默认在转写完成后自动生成，可关闭；已有完整历史会议不会因为配置或重启而批量发送，详情中可手动“生成纪要”。纪要包括摘要、决策、行动项和原文引用；点击引用可核对完整文字并定位录音。失败或重新生成失败会保留上一份成功纪要，重试由用户发起。退出时未完成的纪要会中断，不自动重新调用服务。

在线纪要只发送当前会议的完整转写，不发送录音文件。首版单次请求处理完整会议，输入或输出超限会明确失败，不截断原文或自动拆成额外请求。密钥以系统加密保护的密文保存于用户数据目录 `model-services.json`，读取设置只显示是否已配置；更换 API 地址需要重新输入密钥。系统暂时无法访问密钥时，先检查系统授权并重新打开应用；原配置保留，录音和转写不受影响。

最小化和切换页面不会停止录音。录音中关闭窗口、退出或重连时，可选择继续录音或停止保存；保存失败会保持窗口可见。休眠、设备失效与异常退出的记录明确标记为中断，下次启动恢复已经落盘的完整音频帧。

开发 UI 只绑定 `127.0.0.1:5173`；Python 控制核心通过标准输入输出通信，不监听业务网络端口。构建预览加载本地资源。`npm run build` 只生成 `out/`；使用 `npm run package` 才会内嵌运行时并生成安装包，暂未实现正式签名、公证或自动更新。

### 配置与故障恢复

源码开发的解释器顺序：`PAA_PYTHON` 可执行文件路径 → 项目 `.venv` → macOS `python3` 或 Windows `py -3.12`。解释器不是 Python 3.12 或缺失时，仍显示窗口与错误提示。安装版只启动随包核心，不回退到系统解释器；资源缺失时提示重新安装。

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

转写任务、已完成块和片段存入同一个 SQLite 数据库，模型位于用户数据目录的 `models/whisper-small-<revision>/`。当前使用 schema 5，旧版本依次增量迁移；迁移前生成 `meetings.schema<旧版本号>.backup.sqlite3`（支持 schema 1～4），失败保留原库并回滚。备份不含独立 WAV，手动备份应关闭应用后复制整个用户数据目录。旧程序不能直接读取 schema 5；若需回退，应关闭应用、保存完整当前目录，再使用升级前的数据库与对应音频副本，不能直接修改版本号或删表。

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
| `npm run test:smoke:quick` | 受控桌面流程，用于手动或发布前检查，不运行真实模型与安装包场景 |
| `npm run test:smoke:asr` | 仅运行真实模型桌面流程，需先准备样本并设置 `PAA_REAL_ASR_SMOKE=1` |

Smoke 使用 Electron 自带 Chromium，无需 `playwright install`；它会打开短暂窗口，需要图形会话。默认自动测试不打开真实麦克风，故障与生命周期由 `tests/python/smoke_core.py` 显式注入合成 PCM，经测试专用可执行文件启动；产品没有假录音回退。POSIX 合成启动器在 Windows 跳过。测试数据为临时隔离目录，截图与实录证据位于忽略的 `artifacts/spec002/`。

### CI 分层

[Desktop CI](.github/workflows/ci.yml) 遵循 [CI 减负规则](AGENTS.md#ci-减负与交付效率)。面向 `main` 的 PR 自动运行一轮基础检查；普通 `dev` / `main` 推送不触发，合并及回同步不重复运行。Node 24、Python 3.12 与锁定依赖保持一致。

| 触发方式 | 平台与检查 |
| --- | --- |
| PR 新建或更新 | macOS 15 ARM64 / Windows 2025 x64：TypeScript / Python 单元及模块测试、普通构建；格式、Lint、类型仅在 macOS 执行一次。不启动 Electron、模型推理或安装包 |
| 手动 `quick`（默认） | 与 PR 相同的双平台基础检查，可指定分支主动运行 |
| 手动 `desktop` | 双平台基础检查及受控桌面流程 |
| 手动 `asr` | 双平台基础检查、真实 small 推理及桌面转写 |
| 手动 `package` | 双平台基础检查、冻结运行时、安装包启动与清理；包含随包推理需要的模型／音频验证 |
| 手动 `full` 或推送 `v*` 标签 | 双平台基础、桌面、真实转写与安装包检查；不自动发布 |

在 Actions 的 **Run workflow** 中选择需要的范围。相关高风险改动可手动提前验证，不按路径自动叠加重测试。汇总检查 **CI required** 只在本轮必需项全部成功时通过；未选择的桌面／集成项允许跳过，选择后失败或跳过均阻止通过。PR 的该汇总检查可用于分支保护。

测试失败保留 Playwright trace、截图和实际异常；不自动重试失败断言。安装包流程与模型桌面流程使用不同的 trace 输出目录，避免后运行的测试覆盖前一份失败证据。模型缓存、公开样本与报告仍在忽略的 `artifacts/`，只上传报告、截图和测试安装包，不上传模型或用户数据。模型识别质量和物理设备采集分别记录，不能用合成数据证明准确率。

本机交互验收在项目目录运行 `npm run dev`，沿用日常录音、模型与服务配置，不另建隔离验收窗口。真实麦克风、蓝牙及首次系统授权由相应实机验收覆盖，远端 CI 不能代替这些结论；历史实机证据见 [Spec 002 实施报告](specs/spec-002-meeting-recording-and-storage/implementation.md)。

新增纪要 Electron 用例使用临时 HTTP 兼容服务及专门编写的 61 段会议样本，在 macOS / Windows 均执行，不访问真实 API 或密钥。真实服务的桌面验收使用用户日常环境，遵循 [桌面验收约定](AGENTS.md#21-测试与验证规则)，证据与模拟故障分别记录于 Spec 004 报告。

开发遵循 [AGENTS.md](AGENTS.md)：Spec 决策由协调 Agent 起草、自查后交用户审查；开 Spec 的业务实施走多 Agent 流程，不开 Spec 时由协调 Agent 直接完成。

## 目录

```text
src/
├── desktop/              # 主进程、preload、Python 客户端、受限媒体
├── renderer/             # React 中文工作区
├── shared/               # 桌面 IPC 与公司 HTTP 契约
├── ui/                   # 跨端共用语义主题
├── web/                  # 公司工作助手 Web
└── python/
    ├── paa_core/         # 桌面录音、SQLite、转写与纪要
    └── paa_server/       # 公司 API、任务、harness 与迁移
deploy/company/          # 公司 Web／API 的独立部署
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

## 公司工作助手 Web（Spec 008）

Electron 继续使用 `npm run dev`。公司账号、员工图文语音、工作进展和汇报看板使用独立 Web＋服务端，不读取或上传 Electron 的会议、模型与密钥。电脑与手机使用同一个网址，布局按宽度自动调整。

### 本地启动

准备 Node 24、Python 3.12、Docker Desktop 和 FFmpeg。服务端使用独立环境，安装过程不下载转写模型：

```sh
npm ci
python3.12 -m venv .venv-server
.venv-server/bin/python -m pip install -r requirements-server.lock
cp .env.company.example .env.company
```

Windows 使用 `py -3.12 -m venv .venv-server`，安装命令改为 `.venv-server\Scripts\python.exe -m pip install -r requirements-server.lock`。其余 npm 命令相同。

编辑 `.env.company`，设置随机 `POSTGRES_PASSWORD` 并同步 `DATABASE_URL`；`PAA_FFMPEG` 可指定 FFmpeg 可执行文件路径。不要提交这个文件，也不要使用 Electron 的配置文件替代。然后：

```sh
docker compose --env-file .env.company -f deploy/company/compose.dev.yml up -d
npm run db:company
node scripts/company.mjs model-key
npm run admin:company
npm run dev:company
```

`admin:company` 通过交互提示创建首家公司和管理员，密码不写入命令历史；公司已初始化时不会覆盖。打开 [本地 Web](http://127.0.0.1:5174)，管理员在“成员管理”创建员工临时账号；员工首次登录需修改密码。`dev:company` 同时启动 Web、API 与处理进程，Ctrl+C 一起停止。也可分别执行 `dev:web`、`dev:server`、`dev:worker`。API 修改后重启，Web 有热更新。

管理员在“设置 → 模型服务管理”添加服务，在“用途分配”指定工作助手、报告与语音模型；保存后新任务即时生效，无需重启。聊天支持兼容 Chat Completions，默认流式；语音选择文件转写或 Qwen-ASR 兼容协议。Base URL 已包含版本路径，不自动补 `/v1`。目录失败可以手填模型 ID，“服务默认”不追加推理参数。获取模型、保存服务、主动小样本检测是独立操作；检测可能计费，不自动调用，目录可见不代表业务能力已通过。

服务器以 AES-GCM 保存 API 密钥，Web 只显示“已设置”。`PAA_MODEL_KEY_FILE` 指定独立的 32 字节主密钥文件，本地默认在忽略的 `data/company/model-master.key`；初始化命令不会覆盖已有文件，数据库已有密文时不会在文件缺失后另造密钥。API 与 worker 必须读取同一私有文件（Unix 权限 600）。不要向聊天发送 Key，不要使用 Electron 的配置文件替代。

升级到 schema `0002_model_services` 前已有公司可继续使用原环境配置，并在管理页明确导入；导入后数据库用途接管，清空用途不会重新落回环境变量。新公司不能继承环境 Key，直接在 Web 配置。原任务固定所用配置修订，普通重试沿用旧配置；失败后也可主动“使用当前配置重新处理”，这可能再次计费。撤销服务使旧任务不能再使用它，历史工作不被删除。

默认只允许公共 HTTPS 模型地址，DNS 解析检查后固定实际连接 IP，不接受重定向和环境代理。部署方确有私有网关时可在 `PAA_MODEL_ALLOWED_ORIGINS` 放行精确源站（逗号分隔），Web 管理员无法放宽此边界。未配置时仍可登录、管理账号、保存消息、手动编辑／提交报告；AI 处理说明缺少的用途并保留输入。

员工发送的原始工作消息、助手回复与附件对公司管理员可见；尚未发送的输入、独立进展编辑草稿和未提交报告仅本人可见。工作进展需员工确认，报告需员工提交。自动日报／周报初始不启用，管理员配置有效日期和时间后生效。

### 服务端和 Web 验证

`npm run typecheck:web`、`npm run test:web`、`npm run build:web` 分别检查新 Web 的类型、快速单元和普通构建。`npm run test:server` 在真实 PostgreSQL 中验证权限、事务、幂等、任务恢复与实际 harness 工具流程，外部模型和 ASR 使用受控响应；不会调用付费服务。

本地测试使用单独的 `paa_company_test` 数据库，在 `.env.company` 配置 `DATABASE_TEST_URL`。先创建该库，再临时将 `DATABASE_URL` 指向测试库执行一次 `npm run db:company`，恢复开发地址后运行测试。测试不清空开发库、录音或本地模型；它只清理自己创建的测试实体。只跑一个文件可用 `npm run test:server -- tests/server/test_boundaries.py`。服务端环境及数据库都独立于桌面 `.venv` 与 SQLite。

CI 原触发方式保持不变；新增的 **Company API and Web** 在单个 Linux＋PostgreSQL 环境跑服务端固定样本、Web 单元／类型／普通构建，纳入 `CI required`。不运行真实 API、实体麦克风、模型下载或发行包。本地执行上述命令不触发远端 CI。

### Linux 单机部署

`deploy/company/compose.yml` 包含 Caddy、API、一个处理进程和 PostgreSQL。部署前设置 `.env.company` 的生产域名、`PAA_WEB_ORIGIN=https://你的域名`、数据库密码与 `PAA_MODEL_KEY_HOST_PATH`；域名需解析到服务器，80／443 可达。生产 cookie 强制 Secure；PostgreSQL 不发布公网端口。

先在宿主机仓库外创建一次 32 字节随机密钥文件，设置所属用户为容器服务账户 UID 10001、权限 600，并在 `.env.company` 的 `PAA_MODEL_KEY_HOST_PATH` 指向该现有绝对路径。API／worker 以只读绑定挂载使用它，Compose 不会自动创建缺失文件，也不能把密钥放进镜像。保留原文件与独立备份，不在升级时重新生成。

```sh
docker compose --env-file .env.company -f deploy/company/compose.yml up --build -d
docker compose --env-file .env.company -f deploy/company/compose.yml exec api python -m paa_server.cli bootstrap-admin
```

迁移任务先成功，API 和处理进程才启动；Web 独立构建后由 Caddy 同源提供。生产镜像固定 Python、数据库和 FFmpeg 版本，服务端依赖使用独立锁文件；日后安全升级需更新固定版本并验证。部署本身不会自动准备模型凭证。手机前台录音需要有效 HTTPS；手机访问开发电脑 IP 不享有 localhost 的安全例外，也不保证锁屏持续采集。

2 核 2 GB 是试点部署起点，尚未通过实际负载验证。默认单处理并发、数据库小连接池，AI／ASR 由外部服务承担。每任务限制调用、工具次数、时间和 token 预算，另有公司每日调用额度；不将请求已发出但结果未知的情况自动重跑。

升级前在维护窗口备份，设置已有的私有 `PAA_BACKUP_DIR` 后运行 `deploy/company/backup.sh`：暂时停止 Web／API／处理进程，保存 PostgreSQL dump、媒体与校验清单，然后恢复服务，保留最近 7 份完成的备份。主密钥必须另存于独立私有位置，`PAA_MODEL_KEY_BACKUP_DIR` 指定该目录；脚本为同一备份时间戳保存密钥副本及其校验值，不与数据库归档混放。两类备份由运维分别复制到受控异机位置。恢复时先验证两个 SHA256SUMS，停止写服务，使用对应镜像将 dump 导入空库、媒体还原到私有卷，并安装同一时间戳的主密钥（UID 10001／600），核对后再启动；不要把新 schema 自动降级到旧版本。主密钥丢失时旧凭证无法恢复；先保存业务数据库备份，由部署管理员撤销不可读服务并在确认所有旧密文已撤销后重新初始化主密钥，再重新输入各服务 Key。不要将损坏密文当成明文或静默恢复环境 Key。本轮未执行云部署、真实付费模型联调、手机实机录音或生产恢复演练。
