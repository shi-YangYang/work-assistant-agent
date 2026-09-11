# Acceptance — Spec 005

## Result

**FAIL · 2026-09-11**。许可返工已由新的独立验收 Agent `/root/spec005_license_acceptance` 只读复验，I1 关闭，本次复验未发现新的确定工程缺陷。整体仍未完成：Windows 本轮产物／CI、完整播放器交互及安装版物理麦克风缺少通过证据，不能将配置或代码检查作为通过证据。

后续用户实测发现播放器重复创建与返回后残留，证明此前对重复 AX 节点的缓存归因不成立。协调 Agent 已按用户“直接修复”要求纠正重复 key，并以实际 App 的定向渲染／卸载回归验证；详情与修复前后证据统一见 [实施报告](implementation.md#播放器重复渲染修复--2026-09-11)。这次是主 Agent 直接修复与自查，不冒充新的独立验收，也不改变整体待验收状态；已有安装包需后续更新该修复。

首轮 `/root/spec005_acceptance` 判定 FAIL，原因是 Python 许可未随包（I1）及上述验证缺口。以下保留首轮覆盖结论，只补充本次许可修复与安装资源证据；两名验收 Agent 均未修改业务代码。

## Spec Coverage

| 范围 | 结论与依据 |
| --- | --- |
| R1 随包运行环境 | macOS ARM64 已产出并实际安装 DMG；实际 `.app` 资源在空 PATH、无源码 cwd 下完成核心协议、独立 small 离线推理、VAD、CA HTTPS 与合成暂停续录。严格资源路径、冻结入口 worker 分流与退出控制符合实现方案。Python 许可遗漏已修复并验证安装副本；Windows 本轮产物／安装未验证。 |
| R1 数据与密钥衔接 | 日常 schema 3 → 4 迁移保留原 7 张表、3 条 WAV 与模型，并创建备份。开发版、打包版及 `/Applications` 安装版日志均为 `restored`，原密钥在系统授权后可解锁；未调用收费 API。 |
| R2／R3 设置 | 同一折叠组件使用按钮、`aria-expanded`、持久展开偏好和隐藏内容；三个区域独立，名称已统一。协调 Agent 实际验证折叠保留未保存草稿并恢复临时草稿。键盘／视觉完整验收尚缺。 |
| R4 暂停／继续 | 回调门禁、关闭输入流、排空队列、fsync 后确认 paused；继续保留格式、会议 ID、帧偏移及 WAV，旧回调代次被拒绝。活动状态覆盖协议、历史、退出守卫与转写调度；暂停不设置转写结束目标。定向测试和真实麦克风证据支持无静音追加，未发现确定的代码缺陷。 |
| R5 播放器 | 自定义控件、时间／倍速／音量、键盘作用域、会议实例隔离与文字定位接口具备；媒体仍走受限 Range 流。新增交互用例尚未执行，不能仅凭控件存在认定功能通过。 |
| CI／最终交付 | 本轮未推送，没有对应提交的 CI 结果；旧提交 CI 不用于本次结论。 |

## Tests

本次为 S3，复用已经通过且代码未再次受影响的验证，未重复运行整套测试、构建或本机隔离 Electron 窗口。

- 已复核 [实施报告](implementation.md) 所列 28 项 TypeScript、58 项 Python 子系统检查，以及 7 项密钥设置定向检查；其边界和未执行项保留，不伪称为本验收 Agent 重新执行。
- 首轮已读取 `artifacts/spec005/package-darwin-arm64.json` 与冻结日志：冻结 Python 3.12.14、随包路径、真实 small spawn、VAD、HTTPS、合成暂停续录、DMG 校验及应用签名通过。首轮包 `2c48730c…106282` 的清单保留于 `before-license-rework-package.json`；许可返工后的当前产物见下方 I1 复验。
- 已复核 `daily-migration-check.json`、`daily-pause-check.json`、`daily-recording-check.json`、`daily-ui-check.json`：实际暂停观察 39.88 秒，294912 帧不变；同一会议最终 119936 ms 音频对应 357980 ms 真实经过时间，暂停未补静音。自动纪要已恢复原值 true，服务配置 hash 和活动服务未变。
- 实安装证据 `installed-macos.json`：首轮 DMG 只读挂载，复制到原先不存在的 `/Applications/个人工作助手.app` 后卸载卷；从源码外目录启动仍使用日常数据，核心及 ASR 进程路径均来自安装版 Resources。`installed-startup.log` 确认原服务设置恢复。许可返工后已从新 DMG 更新该测试安装副本，核对新许可与签名；未重复未受影响的启动检查。
- 首轮对许可产物的只读检查确认了以下 I1；两轮均未读取或输出明文密钥，未修改用户数据。
- 针对协调 Agent 提出的新构建脚本格式疑点，仅执行已安装 `prettier --check scripts/build-core.mjs`，结果通过；没有扩大格式检查范围。

## Issues

### I1 — Python 运行时许可未进入 macOS 产物（P2，已关闭）

首轮 `scripts/core-licenses.py` 只查找 `sys.base_prefix/LICENSE.txt`，不存在时静默跳过。当前构建解释器的许可实际位于 `sysconfig.get_path('stdlib')/LICENSE.txt`；首轮 `.app/Contents/Resources/paa-core/licenses/Python-LICENSE.txt` 不存在，未完成 Plan 要求的许可收集核验。

2026-09-11 由新的实施 Agent 定向返工，再由 `/root/spec005_license_acceptance` 独立复验：

- 只读核对两处脚本：收集器依次查找 stdlib、base_prefix、base_exec_prefix，找不到非空许可即失败；产物检查在启动核心前要求非空 Python 许可及与仓库一致的运行锁，`--licenses-only` 不触发业务运行。复用 `license-rework.json` 中已通过的缺失／空文件失败和模拟 Windows 布局回退证据；后者不代表 Windows 实际包通过。
- 本复验执行一次只读文件核对：解释器来源、`dist/core`、打包 `.app` 和 `/Applications` 副本的许可逐字节一致，均为 13,936 字节，SHA256 `3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf`；两个应用资源中的 `requirements.lock` 均与仓库一致。
- 独立核对当前 DMG 的实际大小与摘要：198,805,725 字节，SHA256 `aaa3bf11a69f94ed6620e8335a0e5b0d27a002ef75e1946b0c43c3f9a8caa51c`，与 `final-package.json`、`installed-macos.json` 一致。复用新包严格签名／DMG 校验及更新安装副本签名通过的证据；冻结核心未变，不重跑 PyInstaller、ASR、录音或整套检查。

## Regression Risks / 未执行项目

- Windows x64 NSIS 产出、实际安装、内置核心及对应 CI 尚无本轮结果。
- 播放器完整交互、键盘及视觉布局仍缺实际通过证据；重复创建已按上方补充记录确认为代码问题并修复，CUA 窗口错误不再用来解释该缺陷。
- 安装版物理麦克风录制／暂停／继续／保存与回放尚未完成；开发版真实采集和冻结合成测试不能替代该项。
- 本轮测试包按约定不做正式签名／公证，未将此列为缺陷。

## Required Rework

I1 修复与新独立 Agent 的许可复验均已完成，无待处理的已知代码缺陷。协调 Agent 仍须补充上述平台／桌面／当前提交 CI 证据，或明确取得用户对尚未验证边界的接受；不能将缺口改写为通过。
