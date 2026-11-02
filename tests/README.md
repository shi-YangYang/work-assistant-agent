# 项目测试

普通测试不使用真实模型密钥；模型质量与真实模型浏览器入口在 `eval/`。本地结果与远端 CI 分开，CI 只做静态检查和普通构建。

## 准备与运行

使用 Node 24 / npm 11、Python 3.12。执行 `npm ci`，按根 README 安装 `.venv` 桌面 Python 与 `.venv-server` 服务端依赖；浏览器执行 `npx playwright install chromium firefox webkit`；Web录音需要真实FFmpeg，安装到PATH或通过 `PAA_FFMPEG` 显式提供可执行路径。Electron 软件测试使用自有临时数据目录，不读取日常会议。

```sh
npm run test:project -- --list
npm run test:project -- --suite web-modules,desktop-modules
npm run test:project -- --suite core
npm run test:project -- --suite server-critical
npm run test:project -- --suite web-flow
npm run test:project -- --suite web-ui
npm run test:project -- --suite desktop
npm run test:project -- --suite integration
```

`modules` 包含 Web、桌面、core 与完整 server；不要在小改后默认运行全部。`server-critical` 只选工作、周报、身份模块；真实代理负载测试单列外部集成。原 `npm test` 语义不变。套件以 `tests/suites.json` 为唯一运行组清单，原生报告列出实际用例，配置不复制用例名称。

Web／server 需要显式设置 `DATABASE_TEST_URL`，只允许本机 `paa_company_test`。不要复制日常 `.env.web`；运行器设置 `PYTHON_DOTENV_DISABLED=1`。环境管理器每次创建 `project_<purpose>_<run-id>` schema，迁移、合成账号及数据、独立媒体目录与密钥；校验 schema marker/run ID/凭证权限/账号身份之后才执行。Web 自动分配 loopback 端口，启动本轮 API、worker、Vite，真实登录核对服务端账号 ID，finally 停止自有子进程并验证归属后删除 schema。共享数据库不停止。

Redis 只读取显式 `PAA_REPLY_STREAM_TEST_URL`（例如独占测试实例 `redis://127.0.0.1:62379/0`），必须包含 loopback 主机、端口和数据库编号；未提供时显式禁用。继承的 `PAA_REPLY_STREAM_REDIS_URL`／`PAA_REPLY_STREAM_NAMESPACE` 会被覆盖，namespace 固定为 `project:test:<本轮环境 runId>`，cleanup 只删除此前缀下的键。直接调用 Web／server wrapper 也使用相同校验，不读取日常 namespace。测试 Redis 应由调用者独占准备，运行器不停止基础服务。

统一入口和直接 wrapper 由同一监督进程管理独立 POSIX 进程组：先发 SIGTERM，最多等待 15 秒，再发 SIGKILL 并最多等待 5 秒；直属父进程关闭不能解除后代回收。只有确认整个组消失后才清理环境；回收失败保留环境并报错。当前 Windows 执行明确拒绝，待实现并实际验证对应的进程归属屏障；`--list`／`--report` 仍可用。

Web 固定响应位于供应商 HTTP transport，实际请求序列化、API、worker、权限、保存和刷新读回仍运行。供应商仅接受 `project-provider.invalid`，其他模型目标直接失败。UI 文件中 `page.route` 拦截业务 API 的用例仅证明前端状态，不能作为实际保存证据。布局夹具显式打开默认隐藏的可选宠物；不改变产品默认偏好。普通浏览器没有真实转写/搜索/钉钉能力。

需要更小的修复回归时，可直接使用原生 runner 或环境包装器，不重复已通过部分：

```sh
PROJECT_TEST_OUTPUT="$PWD/artifacts/project-tests/my-fix" PROJECT_TEST_RUN_ID=my-fix \
  .venv-server/bin/python scripts/testing/web-run.py business/work.spec.ts
```

输出目录须是新的目录；必须保留首次失败。Python 环境缺失、浏览器缺失、零发现、必需 skip、超时、信号退出都不会标记 PASS。取消时仍需核对 `environment.json` 的 `cleaned`；操作系统强杀无法执行 finally，可在确认本轮进程停止后显式执行环境管理器 cleanup，归属检查仍生效。

## 功能与证据边界

| 功能 | 入口 | 场景与层次 |
| --- | --- | --- |
| 登录、租户与角色 | `server/modules/auth`、`server/modules/members`、`e2e/web/auth` | 无效账号、登录、退出、账号切换；服务端跨公司与CSRF |
| 会话、流式与恢复 | `web` 的 assistant/conversation/streaming 测试、`server/agent`、`e2e/web/assistant` | 草稿、切换、排队、流式、断线与失败；业务 API 注入用例单独解释 |
| 提问、确认与任务 | `web` 的 question/confirmation/task 测试、`server/agent` | 题数、选择、自填、返回、续接、拒绝副作用；供应商质量不在范围 |
| 附件与来源 | `web` 的 attachment/material/resource 测试、`server/modules/work`、`e2e/web/assistant/composer.spec.ts` | 上传、预览、删除、来源与命中区域 |
| 工作 | `server/modules/work`、`e2e/web/business/work.spec.ts` | 正文、清单、材料、历史、并发草稿恢复；真实保存刷新 |
| 周报、团队 | `server/modules/reports`、`e2e/web/business/reports.spec.ts`、`lifecycle.spec.ts` | 周期、空源、幂等、退役日报、编辑提交、团队只读、删除重建 |
| 会话闭环 | `e2e/web/business/conversation-lifecycle.spec.ts` | 分批上传、真实worker提问、刷新续接、早批文件下载、确认前0条/后1条工作与正文读回 |
| 跨入口闭环 | `e2e/web/business/lifecycle.spec.ts` | 页面创建工作/正文/材料 → 真实worker周报 → 提交 → 管理员查看删除 → 重建不同ID |
| 管理设置 | `e2e/web/settings`、相应 `web` / `server/modules` | 记忆、成员、模型用途、声纹入口、保存及校验 |
| 外观、键盘与响应式 | `e2e/web/navigation` | 360/390/768/1440、短屏、浅深色、Escape、焦点；截图必须另行查看 |
| Electron会议 | `desktop`、`core`、`e2e/desktop` | 边界、合成捕获、播放、固定纪要、导出及重启；真实麦克风与ASR另测 |
| 基础设施 | `server`、`sandbox`、`deploy` | 迁移、权限、事务、租约、文档、媒体、协议、部署与归属 |

原生入口：`npm run test:web`、`test:unit`、`test:python`、`test:server`；`node --test tests/deploy/*.test.mjs tests/sandbox/*.test.mjs`；Python部署专项 `python -m unittest discover -s tests/deploy`。沙盒协议保持独立 Python 模块命名空间：`npm run test:server -- --sandbox-protocol`。真实代理负载、Redis传输、Office、ASR、安装包等依赖型入口必须按文件说明显式准备，不把 skip 写成通过。Windows、真实手机、物理录音和模型推理没有实际证据时均为未执行。

## 结果

`npm run test:project -- --report artifacts/project-tests/<run-id>` 仅重建已有汇总HTML，不执行任何测试。

`artifacts/project-tests/<run-id>/index.html` 与 `summary.json` 包含源码提交及工作区状态、选择、命令、平台、耗时、各组退出值、原生用例、证据链接。每组保留 `output.log` 和 `results.json`；pytest/Node保留原生JUnit XML。Playwright包含失败trace与截图。汇总只消费该次原生输出，不再次运行测试。相同用例ID的浏览器维度分别记录执行次数与不同用例数。只有所有所选必需用例执行并成功才能整体通过；没有报告时明确命令级证据不足。

截图文件存在不等于视觉通过；截图需按设计基准目视审查。HTML不声称截图已自动获批。初次失败、修复与定向复查的运行目录同时保留。

## 整理去向

- `generated-files.spec.ts`、`performance-journeys.spec.ts` 移到 `eval/web/browser/`，共享环境夹具保留单一实现。用该目录的 `playwright.config.ts` 发现；这些仍依赖真实模型历史采样，是待独立准备的 eval 入口，不是本次通过证据。
- 工作历史和并发恢复文案按当前生产组件更新；有效反向断言保留。
- 布局日报种子改为周报；退役日报反向测试仍在 `server/modules/reports/test_daily_report_retirement.py`。
- `PROJECT_TEST_ENVIRONMENT` / `PROJECT_TEST_OUTPUT` / `PROJECT_TEST_RUN_ID` 是新入口；旧 Spec 变量仅映射到同一环境校验，不复制实现。
- 没有删除既有模块/业务测试。CI退出的测试仍从以上本地入口运行，部署发布保护未变。

可选集成的精确入口、前置和未选择理由也列在 `tests/suites.json` 的 `manualIntegrations`。普通UI显式排除真实Redis发布器与声纹推理；服务端关键组仅排除真实代理负载的两个参数化用例，保留同文件其他保护断言。

运行器与环境自身边界检查：`node --test tests/tooling/*.test.mjs`；`PYTHON_DOTENV_DISABLED=1 .venv-server/bin/python tests/tooling/test_project_environment.py`。前者包括真实子进程缺依赖、SIGINT、超时、拒绝SIGTERM后的有界强杀及新增源码hash；后者检查专用库/本机目标、私密权限及run身份拒绝。新增父进程先退出、后代关闭 stdio 且拒绝 SIGTERM、清理顺序、直接 wrapper 归属以及 Redis 继承覆盖／远端拒绝检查。

首批模块覆盖中的具体入口包括 `web/dom/assistant/assistant-interactions.test.tsx`、`business-action-card.test.tsx`、`composer-attachments.test.tsx`、`attachment-send-errors.test.tsx`、`assistant-task.test.tsx`、`server/agent/execution/test_assistant_interactions.py` 与 `test_authorization_clarification.py`；浏览器截图不替代这些权限/副作用断言。

Windows 限制只适用于新增项目统一 runner 及其 Web／server wrapper；原有 Windows 原生测试命令与 CI 手动平台命令不受影响，未声明 Windows 验收通过。
