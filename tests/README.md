# 项目测试

这里提供模块、界面和完整业务流程测试，不需要真实模型密钥。真实模型质量验证见[本地 Agent 评测](../eval/README.md)。日常 CI 只做静态检查和普通构建；桌面运行、ASR 和打包检查可手动触发，本地结果与远端结果分开记录。

## 选择测试

从仓库根目录运行，按改动选择一组或多组：

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

`modules` 包含 Web、桌面、core 与完整 server；小改动无需运行全部。`server-critical` 只选工作、周报和身份模块。`npm test` 只运行桌面模块与 Python 核心测试。完整运行组和命令见 [suites.json](suites.json)。

## 环境准备

统一测试入口及 Web／server 环境包装脚本目前只支持 POSIX 系统。Windows 可使用 `--list`／`--report`，执行测试会被拒绝；原有 Windows 原生测试命令与 CI 手动平台命令不受此限制，是否通过仍以对应平台的实际结果为准。

- 使用 Node.js 24、npm 11、Python 3.12，执行 `npm ci`。按[安装指南](../docs/setup.md)准备所需的桌面 `.venv` 或服务端 `.venv-server`。
- 浏览器测试先执行 `npx playwright install chromium firefox webkit`。Web 录音测试需要 FFmpeg，加入 PATH 或用 `PAA_FFMPEG` 指定路径。
- Web／server 测试须显式设置 `DATABASE_TEST_URL`，只允许连接本机的 `paa_company_test` 数据库。不要复制日常 `.env.web`；运行器禁用 dotenv 加载。
- Redis 可选，通过 `PAA_REPLY_STREAM_TEST_URL` 指定独占测试实例，例如 `redis://127.0.0.1:62379/0`。地址必须包含本机主机名或 IP、端口和数据库编号；未提供时禁用，不沿用日常 Redis 配置。

每次 Web／server 运行创建独立 schema、合成账号、媒体目录和密钥，并核对归属后执行。Web 自动分配本机端口，启动本轮 API、worker、Vite，登录后核对账号。Redis 使用 `project:test:<环境 runId>` 命名空间，清理只删除此前缀的键。Electron 软件测试使用临时数据，不读取日常会议。

退出时先停止本轮进程组，发送 SIGTERM 后最多等待 15 秒，必要时用 SIGKILL 再等待 5 秒。确认后代进程全部停止、环境归属有效后才删除 schema；回收失败则保留环境并报错。共享 PostgreSQL 和 Redis 不会被停止。

## 定向运行

只验证一个功能时，可使用原生测试命令或环境包装脚本。例如：

```sh
PROJECT_TEST_OUTPUT="$PWD/artifacts/project-tests/my-fix" PROJECT_TEST_RUN_ID=my-fix \
  .venv-server/bin/python scripts/testing/web-run.py business/work.spec.ts
```

`PROJECT_TEST_OUTPUT` 指定新的输出目录，`PROJECT_TEST_RUN_ID` 标识本次运行；包装脚本通过 `PROJECT_TEST_ENVIRONMENT` 把环境文件传给测试。旧 Spec 环境变量仅作兼容，仍经过同一归属校验。

保留首次失败，修复后使用新目录。取消运行后检查 `environment.json` 中的 `cleaned`；若进程被系统强杀，须先确认本轮进程已停止，再调用[环境管理脚本](../scripts/company/web-acceptance/environment.py)的 `cleanup` 命令。

## 功能与证据边界

Web 流程测试使用固定的模型服务响应，但实际运行请求序列化、API、worker、权限检查、保存和刷新读回。测试只允许 `project-provider.invalid` 模型目标，不能据此判断真实模型质量。使用 `page.route` 替换业务 API 的用例只证明前端状态；截图也不代替持久化和权限断言。布局测试主动显示可选宠物，产品默认仍为隐藏。

表中路径相对于 `tests/`：

| 功能 | 入口 | 场景与层次 |
| --- | --- | --- |
| 登录、租户与角色 | `server/modules/auth`、`server/modules/members`、`e2e/web/auth` | 无效账号、登录、退出、账号切换；跨公司隔离与 CSRF |
| 会话、流式与恢复 | `web` 的 assistant/conversation/streaming 测试、`server/agent`、`e2e/web/assistant` | 草稿、切换、排队、流式、断线与失败；业务 API 注入用例单独解释 |
| 提问、确认与任务 | `web` 的 question/confirmation/task 测试、`server/agent` | 题数、选择、自填、返回、续接、拒绝副作用；供应商质量不在范围 |
| 附件与来源 | `web` 的 attachment/material/resource 测试、`server/modules/work`、`e2e/web/assistant/composer.spec.ts` | 上传、预览、删除、来源与命中区域 |
| 工作 | `server/modules/work`、`e2e/web/business/work.spec.ts` | 正文、清单、材料、历史、并发草稿恢复；真实保存刷新 |
| 周报、团队 | `server/modules/reports`、`e2e/web/business/reports.spec.ts`、`lifecycle.spec.ts` | 周期、空源、幂等、退役日报、编辑提交、团队只读、删除重建 |
| 会话闭环 | `e2e/web/business/conversation-lifecycle.spec.ts` | 分批上传、worker 提问、刷新续接、早批文件下载；确认前不写入，确认后仅创建一次并读回正文 |
| 跨入口闭环 | `e2e/web/business/lifecycle.spec.ts` | 页面创建工作与材料 → worker 生成周报 → 提交 → 管理员查看、删除 → 重建不同 ID 的报告 |
| 管理设置 | `e2e/web/settings`、相应 `web` / `server/modules` | 记忆、成员、模型用途、声纹入口、保存及校验 |
| 外观、键盘与响应式 | `e2e/web/navigation` | 360/390/768/1440、短屏、浅深色、Escape、焦点；截图必须另行查看 |
| Electron 会议 | `desktop`、`core`、`e2e/desktop` | 边界、合成捕获、播放、固定纪要、导出及重启；真实麦克风与 ASR 另测 |
| 基础设施 | `server`、`sandbox`、`deploy` | 迁移、权限、事务、租约、文档、媒体、协议、部署与归属 |

原生入口包括 `npm run test:web`、`npm run test:unit`、`npm run test:python`、`npm run test:server`。部署及沙盒检查可用 `node --test tests/deploy/*.test.mjs tests/sandbox/*.test.mjs`；Python 部署检查用 `python -m unittest discover -s tests/deploy`，沙盒协议用 `npm run test:server -- --sandbox-protocol`。

真实代理负载、Redis 传输、声纹、Office、ASR 和安装包检查需单独准备依赖，入口及前置条件见 [suites.json](suites.json) 的 `manualIntegrations`。`web-ui` 不包含真实 Redis 发布器和声纹推理；`server-critical` 排除真实代理负载测试，保留同文件其他断言。普通浏览器测试不验证真实转写、搜索或钉钉服务。

## 查看结果

打开 `artifacts/project-tests/<run-id>/index.html` 查看结果。`summary.json` 保存源码提交、工作区状态、运行命令、平台、耗时、退出值和实际用例；每组保留 `output.log`、`results.json`，pytest／Node 另保留 JUnit XML，Playwright 保留失败轨迹和截图。

需要重建汇总页时运行，将 `<run-id>` 替换为实际运行目录名：

```sh
npm run test:project -- --report "artifacts/project-tests/<run-id>"
```

此命令只读取已有结果，不再执行测试。报告区分执行次数与不同用例数；同一用例在不同浏览器下的结果分别保留。

只有所选必需用例全部执行并成功，整体结果才为 PASS。缺依赖、未发现用例、必需用例跳过、超时、信号退出或缺少原生报告均不能算通过。未选择的平台、真实手机、物理录音和模型推理也不算已验证。

截图需按[设计基准](../docs/design/README.md)目视检查，文件存在不代表视觉通过。首次失败与修复后的结果分别保留；日志、截图、下载和报告放在被 Git 忽略的 `artifacts/`，测试源码与固定样本仍提交。

## 维护测试工具

修改运行器或环境管理逻辑时，使用 `node --test tests/tooling/*.test.mjs` 和 `PYTHON_DOTENV_DISABLED=1 .venv-server/bin/python tests/tooling/test_project_environment.py`。这些检查覆盖缺依赖、取消、超时、后代进程回收、清理顺序、源码指纹、环境归属和 Redis 隔离。

依赖真实模型的文件生成与速度流程位于 `eval/web/browser/`，使用该目录的 `playwright.config.ts`，需另行准备模型与采样环境。日报退役保护仍保留在 `server/modules/reports/test_daily_report_retirement.py`，不代表产品支持生成日报。
