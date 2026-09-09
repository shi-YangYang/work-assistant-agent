# Acceptance — Spec 001

日期：2026-09-09。角色：新的独立工程验收 Agent，与实施 Agent 相互独立。

## Result

PASS

验收范围是已实施的 Electron / React / TypeScript 桌面骨架与 Python 标准库控制核心。产品与技术决策只核对交付覆盖及实现一致性，不重新评判用户已经确认的决策。本结论不代表真实录音、ASR、LLM、业务持久化、安装包或 Windows 运行已通过验收。

已读取 AGENTS、有效项目规则、使命与技术约束、当前 Spec/Plan、交接、实施报告、产品定义、架构与决策 0004；检查了包含未跟踪文件在内的全部本次源码、测试、配置、锁文件和相关 diff。没有修改业务代码、测试或工程配置。

## Spec Coverage

| 标准 | 结果与交付证据 |
| --- | --- |
| AC-01 | PASS。产品定义覆盖用户、Electron 形态、目标会议流程、异常体验及阶段非目标；界面如实标识开发预览、后续周报与长期记忆。这里只确认既有决策已落实。 |
| AC-02 | PASS。架构与决策记录覆盖工具链、进程边界、音频并发、ASR 候选、LLM Provider、存储方向与验证方式；模型和分发事项明确延期。安装的版本与锁文件一致，electron-vite 5 的 Vite peer 范围包含实际使用的 Vite 7。 |
| AC-03 | PASS。架构对应 renderer → preload → Electron main → Python stdio 的实际数据流；后续录音、转写、总结及数据契约只保留设计边界，没有生成伪实现。 |
| AC-04 | PASS。实际工程遵循决策 0004，目录、版本、命令和平台限制与技术约束一致。状态处于 ACCEPTANCE 是验收中的正常状态，最终状态由协调 Agent 同步。 |
| AC-05 | PASS。README 命令与 package.json、解释器选择、显式 Electron postinstall 一致；安装结果已有实施报告证据。独立复验现有锁定依赖、构建和真实 Electron 启动成功。未将本次复验描述为另一次干净安装。 |
| AC-06 | PASS。真实窗口不依赖模型、密钥或设备授权；缺失 Python 和系统旧版本 Python 都显示可理解错误，界面可访问；健康数据包含实际 Python 3.12.14 与 PID，会议查询经过真实子进程返回空列表。“开始会议”禁用，三项会议能力均尚未接入。 |
| AC-07 | PASS。实际配置并执行 TypeScript/Python 测试、类型、Lint、格式、构建和真实 Electron smoke，结果见下表。补充运行时探测区分了通过项与浏览器特殊边界。 |
| AC-08 | PASS。macOS ARM64 实机检查完成；Windows 仅检查 CI 定义、无 shell 的进程参数、解释器与路径选择，Windows 实机和 CI 未运行。 |
| AC-09 | PASS。保留 src、tests、docs、固定 Agent 结构及 MIT 许可证；新增内部模块与辅助脚本符合范围，没有实际音频、模型、数据库或外部服务接入。 |
| AC-10 | PASS。实施报告齐备；本报告由新的独立验收 Agent 提交。无需要业务代码返工的阻塞问题，发现的浏览器特殊行为已限定复现条件并交协调 Agent 收敛文档措辞。 |

## Tests

独立复验环境：macOS ARM64、Node 24.20.0、npm 11.19.0、项目 `.venv` Python 3.12.14。使用已安装的 node_modules 与 .venv，不重新安装依赖。

| 独立执行 | 结果 |
| --- | --- |
| `npm test` | PASS：2 个 Vitest 文件、16 项测试；7 项 Python unittest。 |
| `npm run typecheck` | PASS：桌面、共享契约、renderer 和测试类型检查。 |
| `npm run lint` | PASS。 |
| `npm run format:check` | PASS。 |
| `npm run test:smoke` | PASS：其前置 `npm run build` 成功，3 项真实 Electron 场景全部通过，没有跳过。 |
| `npm ls --depth=0` | PASS：依赖树有效；另以脚本核对 package-lock 根清单与 package.json 的 dependencies/devDependencies 相同，lockfileVersion 为 3。 |
| `git diff --check` | PASS。 |
| 补充真实 Electron 探测 | PASS：设置与会议导航的 active/aria-current 双向正确；最小 900×640 外部窗口对应 900×608 内容区，没有横向溢出，设置入口与重连按钮可访问。 |
| 补充运行时隔离检查 | PASS：contextIsolation、sandbox、webSecurity 均为 true，nodeIntegration 为 false；媒体请求返回 NotAllowedError；window.open 被拒绝；非受信页面调用核心 IPC 被拒绝。 |

单元测试实际覆盖并发乱序 ID 关联、中文 UTF-8 跨 chunk、超时清理与晚到回复、非法/超长输出、错误与成功互斥、未知方法/无效结构、异常退出拒绝 pending、并发上限、幂等停止、真实 Python 重连与旧 PID 清理、启动中停止和缺失解释器。代码检查确认所有主进程 IPC 限定为无参数方法，并验证窗口、主 frame、完整来源 URL 与参数数量；preload 不暴露任意 IPC、文件或进程能力。

Smoke 独立确认真实 Python ready、空会议列表、未接入操作禁用、renderer 无 Node globals、实际 OS sandbox、生产 CSP、终止 Python 后错误反馈及重连、最小窗口滚动访问、关闭最后窗口后 Python 退出、缺失 Python 可重试及旧版 Python 版本提示。补充探测结束后也验证所启动 Python PID 已不存在。

复验生成的截图位于受忽略的 `artifacts/meeting-workspace.png`、`settings-ready.png`、`meeting-minimum.png`、`core-unavailable.png`。设置截图的背景可能处于 150ms CSS 颜色过渡中；实际 active 与 aria-current 状态正确，不能依据单帧淡出背景认定导航选择错误。

以下项目没有在验收阶段重复执行：`npm ci`、`npm run dev`、`npm start`。安装及这两个入口的运行证据采用实施报告，并核对 `artifacts/development-verification.json` 中开发 URL、真实 ready、Python 版本、空列表与退出记录；独立复验已再次执行构建和直接启动该构建的 Electron 测试。Windows 实机/CI、签名安装包、录音和模型运行均未执行。

## Issues

无阻塞问题。

补充探测首次对“任何导航都保持原页面”做了过宽断言，随后在空白页查找会议按钮而超时；该失败没有被计为通过。进一步复现确认：在 Electron 44.3.0 中通过 `page.evaluate(() => { window.location.href = 'about:blank' })` 注入页面脚本，会触发 did-start-navigation/did-navigate，却不触发 will-navigate/will-frame-navigate，因此 `src/desktop/main.ts:54` 的事件处理不能阻止这个特殊空白页跳转。相同方式发起 HTTPS 外部导航时会触发 will 事件并被阻止，data URL 也被拒绝。

跳转后的空白页面尝试 `window.paa.getStatus()`，得到 `Error invoking remote method 'paa:status': Error: Request is not allowed`，证实 `src/desktop/main.ts:16` 的来源约束仍有效。当前产品没有触发该跳转的按钮、链接或非受信内容；复现需要注入脚本，与脚本清空 DOM 的能力相当，没有越过核心 IPC 边界。因此作为实际浏览器边界记录，不要求扩大本次骨架实现。协调 Agent 已接收此结论，将文档中“任意导航”等绝对措辞收敛到已验证的外部导航与新窗口限制。

## Regression Risks

- Windows 路径和 CI 仅静态检查，尚不能证明 Windows 的 GUI、进程信号或退出清理与 macOS 完全一致。
- 干净安装首次需要下载 Electron；实施环境曾因网络限制使用镜像完成安装，验收阶段没有重复下载。
- 当前正常协议仅包含健康、空列表和退出；后续增加长任务、真实会议数据或音频时，必须重新验证并发、积压、持久化和关闭收尾，不能沿用骨架 PASS 宣称这些能力通过。
- 将来加入外部内容或新页面时，应重新检查导航事件覆盖、CSP 与来源验证；上述 about:blank 边界不应被描述为所有导航均被阻止。
- 本次 `out/` 为仓库内构建预览产物，需要本地 Python；不包含内嵌运行时、签名、公证或安装包。

## Required Rework

无业务代码返工要求。协调 Agent 完成验收状态和相应文档表述同步后可交付本次骨架。
