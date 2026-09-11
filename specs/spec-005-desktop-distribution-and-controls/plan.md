# Plan — 桌面打包与会议操作体验

## 对应 Spec

[Spec 005](spec.md) 为 ACCEPTANCE；实施结果见 [实施报告](implementation.md)，本计划中的技术依据不代替产物验证。业务实施与独立验收按 [Spec 工作规则](../../.ai/rules/spec-decision-workflow.md) 分工。

## 涉及模块与修改顺序

| 顺序 | 模块与预计文件 | 工作 |
| --- | --- | --- |
| 1 | `package.json`、构建锁文件、`scripts/`、新增打包配置、`.github/workflows/` | 固定构建工具，按确认平台打包并验证内置核心 |
| 2 | `src/desktop/python-command.ts`、`core-manager.ts`、`src/python/paa_core/__main__.py`、`asr_worker.py` | 区分开发与打包启动，支持冻结后的 ASR 子进程及退出 |
| 3 | `src/python/paa_core/recorder.py`、`repository.py`、`transcription.py`、`protocol.py` | 采集状态机、暂停边界、恢复与转写衔接 |
| 4 | `src/shared/contracts.ts`、`src/desktop/main.ts`、`preload.ts`、`core-manager.ts` | 受控暂停／继续方法、状态校验、生命周期守卫 |
| 5 | `src/renderer/App.tsx`、`ModelSettings.tsx`、`Transcription.tsx`、`MeetingMinutes.tsx`、`styles.css`，新增折叠及播放器组件 | 设置整理、改名、录音按钮、自定义播放及引用定位 |
| 6 | 相关 `tests/`、README、技术栈及本 Spec 报告 | 按影响范围验证、独立验收、整理交付说明 |

相关模块耦合较强，实施阶段由一个实施 Agent 串行推进；新的验收 Agent 只读检查并报告，协调 Agent 统一处理问题及用户沟通。

## 打包与启动候选

候选采用 **electron-builder + PyInstaller onedir**。保留 Electron 外壳和 stdio Python 核心；各目标系统／架构构建自身原生依赖，将冻结核心的整个目录作为 `extraResources` 放在 ASAR 外。不把开发虚拟环境直接复制进安装包，也不在启动时执行 pip。

开发模式沿用 `.venv`／`PAA_PYTHON`；打包模式使用 `process.resourcesPath` 下受控路径，不带源码脚本参数、不依赖项目工作目录、不受开发解释器覆盖变量影响。保持 UTF-8 stdio 以及原有错误处理和退出管理。Windows 冻结核心保留 console bootloader 的标准输入输出，由 Electron 的 `windowsHide: true` 隐藏窗口；不能使用会使 stdio 不可用的 PyInstaller `--windowed / --noconsole`。

冻结入口在参数解析及重模块导入前处理 `multiprocessing.freeze_support()`，验证 ASR 的 `spawn` 工作进程不会递归启动应用。收集 sounddevice／PortAudio、CFFI、NumPy、PyAV、CTranslate2、ONNX Runtime、tokenizers，以及实际依赖中的 `silero_vad_v6.onnx`、certifi `cacert.pem` 等非代码资源；核对 hooks 的产物而非仅看 import 是否成功。验证符号链接、可执行权限、动态库及第三方许可。仅添加必需的构建依赖，不升级现有运行库。

按 Q1／Q2，制作 macOS ARM64 DMG 与 Windows x64 NSIS 测试包，本轮不接入正式代码签名／公证。macOS ARM 所需的 ad-hoc 签名仍保留，它不等同于正式 Developer ID 签名／公证。保留现有应用名称和用户数据路径，资源目录保持只读，检查安装包的麦克风权限说明与已有加密设置可用性。

## 录音状态与数据流

建议将 `pausing / paused / resuming` 纳入活动录音状态，与 `starting / recording / stopping` 一起禁止开启第二场会议及绕过退出保护；状态变化由核心确定，界面不自行模拟成功。

暂停请求 → 阻止新的采集回调进入 → 停止并关闭输入流 → 处理已接受的队列并同步文件 → 确认 paused。继续请求 → 核对设备与原音频格式 → 打开一个输入流 → 确认 recording。结束请求可以覆盖暂停／继续意图，最终只执行一次保存。序列号、帧偏移和写入位置持续单调，过渡中的旧回调不得写入恢复后的新片段。

音频位置和录音时长只取累计采集帧，不写暂停静音；继续后沿用原帧偏移追加，转写／纪要引用继续使用音频毫秒。会议起止日期仍记录真实时间，不用起止日期之差代替音频时长。暂停期间 ASR 可消化已有音频，但会议仍未结束；调度器不得据此完成整场转写或触发纪要。

新增 `pauseRecording(meetingId)`、`resumeRecording(meetingId)` 及对应受限 IPC／stdio 方法，沿用 ID、来源、参数和响应校验。错误时保留已写数据；继续失败返回暂停状态，能再次继续或结束。恢复查询和退出／重连／休眠流程必须统一识别新增活动状态。

## 折叠与播放器

折叠组件统一管理标题、摘要、展开状态和可访问性；内容保持挂载，隐藏时移出焦点顺序，避免折叠清空草稿或终止异步任务。界面偏好单独命名并校验，不混入模型凭证；异常摘要即使折叠也可读。

基础播放器优先自建 React 控件，复用浏览器音频解码和现有 `paa-audio://meeting/<id>` 范围请求，去掉原生 `controls`。播放器对外提供统一定位操作，由转写及纪要引用调用，避免多个音频实例竞争。进度来自媒体事件；异步加载、播放失败和会议切换有对应状态。快捷键仅在播放器上下文且没有编辑输入时生效。

## 迁移策略与风险

- 保留所有业务与 Agent 目录；构建产物、开发工具和资源清单不得混入用户数据。
- 新持久录音状态即使没有新增表，也需评估数据库版本兼容；有存储语义变化时先备份再事务升级，失败保持旧数据，不自动降级。
- 冻结环境的动态导入、原生库和多进程与源码启动不同；须测试安装产物本身。
- 暂停操作的关键是采集与写入边界，不能仅暂停计时器或继续打开麦克风并丢弃声音。
- 测试包不具备正式签名／公证的分发条件；不能把 ad-hoc 签名或打包成功表述为正式分发已就绪。

## 测试计划

决策文档已按 S0 自查。当前实施涉及构建系统、跨进程状态与持久化，按 S3 选择必要检查：

- 录音定向测试：重复暂停／继续、暂停确认后的帧数和录音时长稳定、恢复后无静音填充且偏移连续、排空队列、设备变化、继续失败、暂停后结束与异常恢复；保留原有时序／无重复写入断言。
- 相关协议及生命周期检查：新状态贯穿请求、历史呈现、退出／重连／休眠与转写完成条件。
- 设置／播放器：折叠不丢草稿或中止任务、统一命名、键盘与焦点、时间与倍速、边界跳转、引用定位、会议切换及长录音范围读取。
- 本机桌面验收直接在项目目录 `npm run dev`，使用用户现有配置、录音及模型；不再另开隔离验收窗口。优先复用已授权的录音验收方式和已有素材。
- 安装包在同平台／架构验证：从安装产物启动，源码／虚拟环境不可用且没有可用系统 Python／Node 的依赖路径；检查实际核心可执行文件来源、ASR spawn 推理、资源缺失提示及进程退出。CI 使用临时测试数据，不能将清理脚本指向用户数据。
- 安装产物实际覆盖录音／播放、small 离线转写及 VAD；通过无需凭证的 HTTPS 固定资源验证证书包。`npm run dev` 不能替代安装产物验收，不为验证卸载用户现有 Python。
- 真实麦克风与旧数据衔接在本机日常环境验收；按测试包范围验证实际安装和打开，不能用 CI 合成输入代替物理麦克风或操作系统安装验证。
- 修改过的格式化覆盖文件先按项目配置整理；类型、相关测试、必要打包及对应提交 CI 均以实际结果记录，不重复已通过且未受影响的检查。

## 技术依据

- [PyInstaller 多进程与符号链接约束](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)：冻结入口需要处理 worker 分流，目录分发需保留符号链接。
- [PyInstaller macOS 架构与签名](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support) 与 [Electron ASAR 限制](https://www.electronjs.org/docs/latest/tutorial/asar-archives)：原生核心须采用匹配架构与真实资源路径。
- [electron-builder 资源配置](https://www.electron.build/v26/docs/mac/) 与 [Windows 目标](https://www.electron.build/docs/win/)：用于评估核心资源随包和安装格式，实施时锁定实际版本及对应配置。
