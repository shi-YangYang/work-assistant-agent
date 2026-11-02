# Implementation Report

## Summary

已实现薄本地入口、原生报告汇总/重建、独立schema合成环境、当前浏览器用例修正、两个真实API/worker业务闭环及既有CI精简。业务实现只修复浏览器实际发现的窄屏宠物与返回入口遮挡；未修改权限规则、模型提示、预算或线上环境。未commit/push/触发远端工作流，等待新的独立验收。

## Files Changed

实际文件树见 plan.md；面向开发者的入口与覆盖在 tests/README.md / suites.json。保留原测试目录；两个真实模型专属浏览器文件移入 eval/web/browser，发现为3条用例（只发现，不运行模型）。新增 tooling 自身边界检查、业务生命周期2文件、testing运行/环境包装器。AGENTS.md、deploy.yml与实际发布保护未改。

## Important Decisions

- 普通测试禁用 dotenv、去除继承的模型密钥，受控供应商在HTTP transport替代；API/worker/权限/保存/刷新仍真实执行。独立授权判断也经真实供应商协议返回合成JSON，未绕过校验。
- 未创建重复components目录；共享卡片/问题/反馈保留原assistant/navigation入口，并由真实会话闭环补截图及确认副作用。
- 宠物默认为隐藏；布局夹具显式开启。实际窄屏头像与气泡压住搜索控件，缩小头像且保留文字；可见宠物时返回链接另行避让，保留命中断言。
- 普通UI不默认运行真实声纹推理/旧Redis发布器，精确入口与前置在 manualIntegrations；服务端关键组仅排除需Docker服务镜像的两个真实代理负载参数用例，不移除同文件普通保护。

## Tests

所有路径相对于 `artifacts/project-tests/`。以下是按修改范围沿用的实际证据，不是一次未执行的“全项目全绿”。首次失败和修复后目录均保留。

| 范围 | 实际结果 | 原始证据 |
| --- | --- | --- |
| Web模块 / 桌面模块 | 871 / 98通过 | `2026-11-02T03-40-20-933Z-3e6dc41c/` 原生JSON及HTML |
| 工作/周报/身份服务端 | 248通过，2真实代理负载未opt-in跳过；该首次运行整体failed | `2026-11-02T03-44-01-553Z-1a22b419/server-critical/results.xml` |
| Agent执行/授权/提问/续接契约 | 550通过，0跳过 | `agent-contracts/results.xml` |
| Python核心 / 部署沙盒Node | 143 / 19通过 | `2026-11-02T03-44-01-553Z-1a22b419/{core,integration}/` |
| macOS Electron | 首次7通过1旧状态文案失败；仅失败项修正“录音完成”后1通过 | 同轮`desktop/`；`desktop-capture-retest/results.json` |
| 登录、账号切换、报告提交团队读回 | 3通过 | `2026-11-02T03-41-22-968Z-c4467776/web-flow/results.json`（同轮2工作旧文案失败） |
| 工作正文/材料/历史、真实并发恢复 | 修复文案后2通过 | `work-retest-1/results.json` |
| 工作→报告→提交→团队删除重建 | 1通过；首轮报告默认待办页测试前置错误保留 | `lifecycle-1/`、`lifecycle-2/results.json` |
| 会话分批材料→提问→确认→保存 | 真实链路1通过，补内容就绪视觉证据后仍通过 | `conversation-1/`、`conversation-2/`失败；`conversation-3/`、`visual-content-ready/results.json` |
| 普通UI | 首个错误路径批次中止并保留日志；修正范围后47项中38通过8失败1真实声纹skip | `2026-11-02T03-43-32-268Z-63d6e8f9/`、`2026-11-02T03-49-02-784Z-d1d617a7/` |
| UI定向修正 | 旧历史/通知/记忆4项通过；遮挡/历史3项通过；drawer与录音最终通过 | `ui-fixes-1/`、`ui-fixes-2/`、`drawer-fix-1/`、`final-browser-boundaries/`、`visual-content-ready/`；普通46项均有最终通过证据 |
| Firefox / WebKit | 登录、附件草稿、记忆恢复各3项，共6通过 | `cross-browser-1/results.json` |
| runner纯结果 / 真实进程 / 环境保护 / CI聚合 | 3 / 3 / 3 / 2通过 | `node --test tests/tooling/*.test.mjs`；`.venv-server/bin/python tests/tooling/test_project_environment.py`，工具实际执行结果 |
| eval迁移发现 | 2文件3用例，未调用真实模型 | `playwright test --config eval/web/browser/playwright.config.ts --list` |
| Python语法、涉及源码格式与针对性ESLint | 通过 | 已安装Prettier、`.venv-server/bin/python scripts/testing/python-syntax.py`；变更文件定向ESLint |

CI干净Linux检查由主Agent执行，证据 `spec083-clean-linux-61e54b06/`：保留install scripts、跳过Electron下载的npm ci成功；桌面三段普通构建通过；Web首次macOS绑定挂载拷贝pdfjs发生EACCES，核对1770个源码hash后只在容器原生文件系统复查Web构建通过。格式、Lint、两端类型检查均通过；后续变化只对对应文件格式/ESLint/语法检查。不是远端Ubuntu CI实跑。

### 四条跨入口闭环

1. `lifecycle-2`：UI创建工作、正文/清单/材料→保存刷新→真实worker受控供应商生成周报→编辑提交→管理员查看删除→员工重建不同ID。
2. `conversation-3`及`visual-content-ready`：两次选文件累计2附件→真实任务提问→刷新仍可答→下载早批文件比对内容→提交答案→确认卡刷新→确认前0条、确认后1条工作→正文刷新读回。问题/确认供应商请求保留在provider.jsonl。
3. `work-retest-1`真实并发冲突保留草稿并显式恢复；网络失败与模块副作用/权限/幂等断言沿用首批通过证据。
4. Electron原生软件7项及捕获定向复查覆盖会议、合成录音、播放、固定纪要、导出、重启；不代表真实麦克风/真实ASR。

### 视觉证据

已实际打开：`lifecycle-2` 的已提交周报；`ui-fixes-2` 的390工作列表、360历史返回；`visual-content-ready` 的390深色问题面板与360浅色报告抽屉。标题/正文/选项/输入/提交与关闭按钮可见，未见重叠或裁切；相应布局与命中断言通过。`final-browser-boundaries` 的问题/抽屉截图捕捉到加载中，已明确不作为视觉通过；增加目标内容可见等待后仅重拍2项，未更新任何视觉baseline。

## Environment / Known Limitations

自有API/worker/Vite及schema均已收尾；中止早期UI批次后人工通过同一归属校验cleanup，未停止共享基础设施。主Agent拥有Postgres/Redis容器并保留供独立验收。凭证文件及私有媒体/密钥随schema清理。

浏览器合成麦克风需要FFmpeg；本机无该可执行文件，初次上传503属依赖缺失。最后仅录音专项用主Agent临时wrapper调用本地Linux FFmpeg 5.1.9容器真实转换、network none，通过；未改系统PATH。运行指南要求其他机器提供真实FFmpeg或PAA_FFMPEG。

未执行Windows、真实手机/软键盘、物理麦克风、真实声纹/ASR、真实模型eval、真实代理负载、Office与安装卸载专项；manualIntegrations记录实际入口。旧Redis浏览器发布器仍是显式历史专项；不把纯前端流式注入算成真实Redis链路。没有声明全部359入口都执行，没有远端CI结论。


## 独立验收返工实施

首轮 `acceptance.md` 的 FAIL 与 `spec083-independent-review/` 原始探针保留，等待新的独立验收，不覆盖原结论。

- 根因一：直属进程 close 取消强杀计时器，wrapper finally 也可能提前清理环境。统一入口与直接 Web／server wrapper 现在共用独立 POSIX 进程组监督；15 秒 TERM、5 秒 KILL 后确认组消失才 cleanup，回收失败保留环境并报错。wrapper 不再自行删除环境。Windows 尚无实际回收证据，执行明确拒绝，保留只读 list/report。
- 根因二：进程环境黑名单未覆盖 Redis，环境 prepare 也未覆盖。新增 `scripts/testing/redis-environment.py` 共享校验，显式测试 URL 必须为 loopback 且含端口／数据库编号；未提供则禁用。日常 URL／namespace 始终覆盖，环境按自身 runId 建 namespace，cleanup 验证 namespace 归属后只删该前缀键。
- 修改文件：`scripts/testing/project-tests.mjs`、`web-run.py`、`server-run.py`、新增 `redis-environment.py`；`scripts/company/web-acceptance/environment.py`；两项 tooling 测试；根 README、测试指南与本报告。未改业务功能、AGENTS、CI，未提交推送。
- 验证按共享测试基础设施 S3 的定向范围执行，未重跑业务全集。证据位于 `artifacts/project-tests/spec083-rework/`：`runner-initial.log` 保留新回归首次失败（回收已完成，但超时且原生结果缺失被标 incomplete），修正结果分类后 `runner-final.log` 8 项通过；`descendant-retest.log` 证明后代死亡后 cleanup 哨兵才运行。`environment.log` 5 项通过，包含直接 Web／server wrapper 在远端 Redis 输入下于 prepare 前拒绝。
- 最小真实直接 Web wrapper 验证 `login/`：选择 W01 实际命中登录、工作材料历史、钉钉空配置共 3 项，全部通过，schema 已 cleaned。`redis/result.json` 证明本轮 namespace 的实际键删除、另一合成 namespace 保留；探针随后删除自己的哨兵键，schema、凭证与临时目录已清理。两次环境均只连接指定 62378／62379 独占基础设施，没有停止容器。
- 其他模块、UI、跨浏览器、Electron 与构建证据沿用上文。Windows、物理设备及外部模型仍未执行；没有远端 CI 结论。

Windows 限制只适用于新增项目统一 runner 及其 Web／server wrapper；原有 Windows 原生测试命令与 CI 手动平台命令不受影响，未声明 Windows 验收通过。

`direct-wrapper.log` 额外 1 项通过：父进程自然退出后回收拒绝 SIGTERM 的后代，并证明另一独立进程组的合成服务仍存活；测试最后仅清理自己创建的服务。涉及 MJS 使用已安装 Prettier 整理，定向 ESLint 与 diff 空白检查通过。

新的独立验收已通过，首轮 FAIL 保留于 acceptance.md。验收结束后，主 Agent 按容器 ID 与归属标签移除了本轮 PostgreSQL／Redis 及干净构建容器，删除临时源码副本、凭证目录和 FFmpeg wrapper；证据目录保留。没有修改日常环境，未提交、推送或运行远端 CI。
