# Acceptance

## Result

PASS

新的独立验收已核对两项返工的实际代码、回归断言及原始日志，原 P1 阻断已闭合；其他范围沿用首轮已独立核对的业务、视觉与构建证据。本结论限于已声明的本地测试范围，不代表 Windows、外部模型或远端 CI 通过。

## 返工复核

- **进程回收：通过。** 统一 runner 与直接 Web／server wrapper 共用 `reapGroup`，按独立 POSIX 进程组执行 15 秒 TERM／5 秒 KILL；父进程 close 不解除回收。两条监督路径均先等待回收，再调用环境 cleanup；回收失败保留环境并返回非通过。Web wrapper 不再自行删除环境。已核对测试中的真实后代、关闭 stdio、拒绝 TERM、cleanup 哨兵与无关独立服务存活断言。
- **Redis 隔离：通过。** `redis-environment.py` 被 runner、直接 wrapper 和环境 prepare 共用；未提供测试 URL 时显式禁用，提供时必须为带端口及数据库编号的 loopback Redis。继承 URL／namespace 被覆盖，环境使用自身 runId。cleanup 先验证环境与 namespace 归属，只删除本轮前缀；未停止 Redis 基础服务。
- **证据：** `artifacts/project-tests/spec083-rework/runner-final.log` 8 项通过，`descendant-retest.log` 清理顺序 1 项通过，`direct-wrapper.log` 1 项通过，`environment.log` 5 项通过。`runner-initial.log` 的首次分类失败继续保留，不计作通过。
- **真实最小流程：** 独立读取 `login/results.json`，3 项 expected、0 skipped／unexpected／flaky；`redis/result.json` 记录本轮键删除、另一合成 namespace 保留。两份 `environment.json` 均为 cleaned，现场检查对应 privateDirectory 均已不存在。以上复用已有执行证据，本轮未重跑测试或连接数据库／Redis。
- **限制：** 新增 runner／wrapper 在 Windows 执行 fail-closed，list/report 可用；已有 Windows 原生命令与手动 CI 入口不受影响，但 Windows 未验收。其余设备、模型及专项限制沿用首轮记录；没有远端 CI 结果。本轮仅修改验收文档，按 S0 检查文档差异，不追加业务验证。

无本轮必需返工。以下保留首轮 FAIL 及原始问题，作为失败与修复的证据链。

## 首轮 Result

FAIL

独立验收发现两项共享测试基础设施缺陷，需完成下述最小返工后再验收。已有业务与构建证据继续有效，不要求重跑全套。

## Spec Coverage

- 目录与入口：普通测试保留既有组织；两个真实模型专属浏览器入口移入 eval，导入与配置已同步，未复制实现。原命令保留，功能映射与可选集成有明确说明。
- 结果：原生结果、失败首次证据、零发现、缺依赖、必需 skip、预期失败、源码未跟踪文件 hash、报告重建逻辑均已核对；不将命令成功代替用例通过。
- 业务：核对工作至周报提交／团队查看／删除重建、分批附件至提问／确认／保存、并发草稿恢复和 Electron 合成输入流程的代码与实际证据。模型替代位于供应商 HTTP transport，不代表真实模型质量。
- 视觉：独立打开 visual-content-ready 中 question-mobile-dark.png 与 drawer-reports-360-浅色.png，确认实际问题、选项、自填框、提交按钮和报告正文／关闭按钮可见，无明显裁切遮挡。旧加载中截图不作为视觉通过。
- CI：日常仅静态检查与普通构建；平台专项由手动输入选择；required 的条件与依赖一致，失败／取消／缺失／未知输入不接受。deploy.yml、AGENTS.md 无改动；未提交、推送或运行远端 CI。
- 环境与清理：schema/run marker、私密权限、账号和 loopback 检查存在，但进程树回收与 Redis 环境继承两项未满足隔离要求。

## Tests

复用实施报告指向的原生证据：Web 871、桌面模块 98；服务端关键组 248（首次另有两个 opt-in skip，整组 failed，不能写为整体通过）；Agent 契约 550；核心 143；部署／沙盒 Node 19。Electron 首次 7 通过、1 失败及后续该项通过均保留。lifecycle-2、conversation-3、visual-content-ready 分别为 1、1、2 项通过；Firefox/WebKit 关键子集共 6 项通过。普通 UI 初次失败与定向修正结果沿用实施报告，不重新执行。

干净 Linux 安装、普通构建和静态检查沿用 spec083-clean-linux-61e54b06 的源码映射及检查记录；Web 挂载权限失败与原生容器文件系统复查均保留。这是本地容器证据，不是远端 CI。

独立验收仅执行两个无网络、无数据库的临时合成探针，并检查 diff：

1. 同进程组父进程响应 SIGTERM 退出、后代忽略 SIGTERM 且关闭 stdio：runner 返回 failed，但后代仍存活。证据 `artifacts/project-tests/spec083-independent-review/process-tree.json`。验收已主动终止该合成后代并删除临时仓库。
2. 传入合成 `redis://unowned.invalid:6379/0` 与 `daily-namespace`：runner 子进程原样继承，未拒绝或隔离。仅读取环境变量，无连接请求。证据 `artifacts/project-tests/spec083-independent-review/inherited-environment.json`。

## Issues

1. **P1：父进程结束不能证明进程树已退出。** `scripts/testing/project-tests.mjs:225` 在直属子进程 close 后立即清除强杀计时器；同进程组后代仍可能存活。随后直接调用环境 cleanup，可在 API／worker 后代还活着时删除 schema、媒体和密钥。现有“拒绝 SIGTERM”测试只覆盖直属子进程，未覆盖这个分支。报告虽未虚假通过，但违反取消后的自有资源回收与清理顺序。
2. **P1：Redis 目标与命名空间可从日常环境静默继承。** `project-tests.mjs:142` 的黑名单未清除 `PAA_REPLY_STREAM_REDIS_URL`／`PAA_REPLY_STREAM_NAMESPACE`；直接 web/server wrapper 同样继承环境，环境管理器不覆盖或验证这些项。真实 Settings／redis_store 会使用它们，所以独立 PostgreSQL schema 并不能隔离 Redis 读写。本轮主 Agent 实际提供的是独占 loopback Redis，未发现本轮访问日常 Redis；缺陷是通用入口无法拒绝错误继承目标。

## Regression Risks

Windows、真实手机／软键盘、物理录音、真实声纹／ASR、真实模型 eval、Office、代理负载及安装卸载未执行，不宣称全面通过。受控 FFmpeg 实际转换证据沿用，不重跑。未操作主 Agent 的 PostgreSQL／Redis 基础容器。

## Required Rework

- 等待并确认整个自有进程组退出后才清理环境；父进程提前退出不能取消后代强杀兜底。覆盖“父退出、后代忽略 SIGTERM、stdio 关闭”的实际进程回归，并检查清理顺序。回收失败应保留非通过结果和诊断，不提前删除仍被使用的环境。
- 对统一入口及直接 web/server wrapper 采用一致的测试环境约束。Redis 必须显式指向经验证的本机测试资源并使用本轮隔离 namespace，或在不需要时显式禁用；禁止静默继承日常／远端目标。以合成环境验证拒绝和隔离，不连接真实外部服务。
- 仅运行上述变更涉及的工具／环境边界检查及必要最小流程；继续复用未受影响的模块、UI 和构建证据。由新的独立验收 Agent 复核。
