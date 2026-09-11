# Implementation — Spec 005

## Summary

已实现设置折叠及“模型服务管理”命名、同一会议暂停／继续采集、自定义会议播放器，以及 electron-builder + PyInstaller 的测试安装包流程。macOS 安装版已实际启动随包核心并沿用原服务密钥；实现交付独立验收，Windows 和尚未完成的桌面交互验证不计为通过。

## Files Changed

- `src/python/paa_core/`：暂停状态机、音频同步、schema 4 升级与恢复、活动转写边界、冻结入口及显式运行时诊断。
- `src/desktop/`、`src/shared/contracts.ts`：暂停／继续受控协议、统一活动状态、开发／打包启动路径区分。
- `src/renderer/`：复用折叠组件、保留设置草稿与异步任务、录音按钮和自定义播放器、原文定位。
- `package.json`、`package-lock.json`、`requirements-build.lock`、`electron-builder.json`、`scripts/`、`.github/workflows/ci.yml`：固定构建工具、原生运行资源及许可、DMG／NSIS 构建与安装验证。
- 相关 `tests/`、README 和架构文档同步实际接口与边界。用户已有 pnpm 锁文件保留，现有依赖版本没有被升级。

## Important Decisions

- 冻结核心置于 `resources/paa-core`、ASAR 外；打包模式忽略开发解释器覆盖，只从自身资源启动。Windows 保留 console bootloader 的 stdio，由 Electron 隐藏窗口；冻结入口先分流 multiprocessing worker。
- 新增持久 `paused` 语义，因此将数据库升级为 schema 4，先备份旧版数据库，不改原业务表结构。暂停关流后排空队列并 fsync，再确认暂停；帧序号、偏移、WAV 和采样率保持连续。继续失败保留暂停和已写内容。
- 播放器复用 HTMLAudioElement 解码与已有受限 Range 协议，不加载整文件做波形，不引入新播放器依赖。快捷键只在播放器上下文响应。
- 构建锁定 electron-builder 26.15.3、PyInstaller 6.22.2、hooks 2026.7；使用 npm postinstall 已准备的 Electron dist。运行模型权重不进入安装包，模型下载显式使用随包 certifi CA。正式签名／公证未纳入本轮。
- 保持原 userData 名称与 safeStorage 密文。macOS 从开发版切换到安装版时由系统请求钥匙串访问授权，不迁移或降级加密。解锁错误给出系统授权指引；启动仅记录固定 restored/unconfigured/失败类别，不记录服务信息或密钥。

## Tests

本次为 S3：涉及冻结构建、跨进程状态与持久化语义，验证按这些边界选择，未运行本机隔离 Electron 测试窗口。

| 检查 | 结果与证据 |
| --- | --- |
| 录音／转写／协议／纪要 Python 子系统 | 58 项通过；新增确认暂停帧数稳定、关流、恢复失败、同音频无静音追加、旧回调拒绝、停止覆盖继续、schema 3 备份恢复 |
| 模型下载 CA 调整 | 原有损坏模型／取消／重试定向测试 1 项通过 |
| TypeScript 单元检查 | 28 项通过，含安装资源路径及缺失运行时不回退 |
| 类型、Lint、改动源码格式 | 已通过；新增 CI 安装测试出现一次未使用导入，修复后该文件 Lint 通过 |
| 系统密钥错误提示调整 | summary-settings 定向单元 7 项、两处桌面源码 Lint 通过；按已安装 Prettier 整理 |
| 冻结核心 CLI | macOS ARM64 实际构建；真实 small 离线 spawn 推理、VAD、固定公开 HTTPS 与随包 CA、合成暂停续录及 native imports 通过。`artifacts/spec005/frozen-diagnostic.log`；推理 3.105 秒 |
| 实际 .app 资源、空 PATH 与无源码 cwd | `npm run test:package` 通过；冻结程序从应用 Resources 启动，health/list/shutdown、独立 small spawn 离线推理 2.196 秒、VAD、CA HTTPS、合成暂停续录通过。`artifacts/spec005/package-darwin-arm64.json` / `package-test.log` |
| DMG／NSIS 安装 | macOS DMG 已生成；许可返工复用既有冻结核心和桌面构建，重新签署 .app 并封装 DMG。校验及 SHA256 见 `artifacts/spec005/final-package.json`；ASAR 仅包含 out/node_modules/package.json。Windows 必须在 Windows runner 执行，尚无本轮远端结果 |
| 日常桌面与原数据 | 协调 Agent 在 `npm run dev` 验证 schema 4/备份、原 7 表与 3 条 WAV hash / 模型文件保留；Redmi 真实麦克风暂停后观察 39.88 秒，294912 帧 / 18432 ms 不变且输入音量为 0，同 ID 最终 1918976 帧 @ 16 kHz = 119936 ms，会议经过 357980 ms，暂停未补静音。`artifacts/spec005/daily-migration-check.json`、`daily-pause-check.json`、`daily-recording-check.json` |
| 折叠与服务密钥 | 协调 Agent 用日常环境验证独立展开、折叠隐藏输入、重展开保留未保存草稿并恢复测试草稿；见 `daily-ui-check.json`。真实 `npm run dev` 与安装版日志均出现 restored，确认原密钥解锁并已配置核心；安装版期间出现系统钥匙串授权窗口，随后成功，未重新填写或输出密钥 |

新增 CI 安装与交互用例尚未远端执行，不把配置存在写成通过。早期 macOS 包构建重复下载 Electron，已改用本地已安装的 dist；安装资源尚未产出时一次 `test:package` 正确拒绝执行。最终产物以 `final-package.json` 为准；未改动的冻结核心不为纯桌面诊断日志修改重复推理测试。

### I1 许可返工 · 2026-09-11

针对首轮独立验收的 Python 许可遗漏，`scripts/core-licenses.py` 现在依次查找 stdlib、base_prefix 和 base_exec_prefix 中的 `LICENSE.txt`；许可缺失或为空时立即阻止构建。`scripts/test-package.mjs` 在运行核心前核对随包许可与运行锁文件，支持 `--licenses-only` 定向检查。未改动业务代码、运行依赖或用户数据。

- 最小脚本检查已验证缺失／空许可失败、真实 stdlib 收集，以及模拟 Windows 安装布局的 base_prefix 回退；后者不代表 Windows 安装包已经验证。
- 旧 .app 被新增许可检查拒绝（退出 1）。更新资源后 `node scripts/test-package.mjs --licenses-only` 通过；随包 `Python-LICENSE.txt` 为 13,936 字节，SHA256 `3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf`，与解释器来源及 dist/core 资源逐字节一致。证据见 `artifacts/spec005/license-rework.json`。
- 仅运行 `electron-builder --config electron-builder.json --mac dmg --arm64 --publish never` 重新复制、签署与封装，复用未变化的冻结程序；`codesign --verify --deep --strict` 与 `hdiutil verify` 均退出 0。未重复 PyInstaller、ASR、录音、类型或整套测试；变动 JS 已按项目 Prettier 配置整理。
- 新 DMG 为 198,805,725 字节，SHA256 `aaa3bf11a69f94ed6620e8335a0e5b0d27a002ef75e1946b0c43c3f9a8caa51c`；旧包 `2c48730c…106282` 的证据保留于 `before-license-rework-package.json`，最新证据更新在 `final-package.json`。交新的独立 Agent 复验，不由实施返工 Agent 判定验收结果。

## Known Limitations

### 播放器重复渲染修复 · 2026-09-11

用户实际发现播放器不断新增并在返回列表后残留；协调 Agent 按“直接修复”要求处理，未创建新 Spec 或子 Agent。根因是同层 AudioPlayer 与 Transcript 都使用会议 ID 作为 key；400 ms 状态轮询反复触发错误的节点匹配。现在分别使用 audio／transcript 前缀，保持各自随会议切换而重建。此前将重复 AX 节点归因于工具缓存的判断撤回。

S1 定向回归在内存 DOM 中运行实际 App／React 组件及模拟桥接响应：旧代码播放器数量为 1→2→3→4→5、返回后残留 4 个；修复后连续刷新始终为 1、返回为 0、重开为 1、再次返回为 0，无重复 key 警告。证据见 `artifacts/spec005/player-key-regression.json`。日常开发窗口也观察到详情停留超过 50 秒仍为一个播放器；没有据此宣布全部交互通过。现有 smoke 用例增加刷新后数量及返回／重入卸载断言，尚未运行该整条 CI 用例；两份改动源码已按 Prettier 整理。本次未重新打包，前述 DMG／安装副本尚未包含这两行 key 修复。

### 剩余验证边界

用户随后反馈倍速菜单弹到左上方；协调 Agent 直接让 `.player-speed select` 复用推理预设已有的 `base-select` 与 picker 锚点样式，从控件下方展开，并加宽控件、允许菜单按内容撑开以避免文字截断。两次均为 S0 局部样式修复，按项目 Prettier 整理并检查 diff；CUA 未能稳定完成菜单交互，不记为实机定位验收通过。

- 未取得 Windows 本机或 runner 的本轮产物与运行证据；未声明 Windows 安装、麦克风或 CI 通过。
- 测试包不具备正式签名／公证；不承诺未经实测的最低系统版本。
- 未调用真实收费模型 API；本次不改变模型服务请求或纪要业务规则。
- CUA 曾返回不同步的截图和窗口错误，但重复播放器已确认为上述代码缺陷并修复。播放器全套交互、键盘及安装版真实麦克风尚未通过验收。DMG 已由协调 Agent 实际安装至 `/Applications`，从源码外启动并沿用原数据及密钥，安装资源证据见 `artifacts/spec005/installed-macos.json`。

## Remaining Questions

无新增产品决策问题。许可返工已独立复验关闭，剩余平台和桌面验证按上述实际边界处理。协调 Agent 已恢复自动纪要原值 true，服务配置 hash 与活动服务未变；证据见 `daily-ui-check.json`。用户已要求提交／推送，远端结果须核对本轮实际提交，不能沿用旧 CI 结论。
