# 项目级测试整理：实施方案

[需求与验收标准](spec.md)

## 实施范围

本方案整理全项目测试，先修复 Web 测试入口和历史耦合，再纳入桌面、服务端、沙盒及部署检查。优先复用已有代码；测试目录不重建，Agent 真实模型质量评测仍在 `eval/`。

项目级测试仅本地手动运行，另精简既有 CI 的默认职责，不将新套件接入 CI。实施时由一个 high 推理强度的实施 Agent 串行处理相互耦合的运行器、夹具与用例，完成后另派新的 high 验收 Agent。Spec 文档按 S0 检查；后续涉及共享测试基础设施、环境保护及运行配置的实施按 S3 选择相关验证，不据此自动运行重型外部集成。

## 修改顺序

### 1. 固定清单与覆盖关系

读取现有 runner 的发现规则及原生用例列表，按模块、UI 状态、完整流程、外部集成分类。盘点不启动模型、不写业务数据；存在收集阶段副作用的入口先静态登记，再在隔离环境收集。

在 `tests/README.md` 维护面向人的功能覆盖表：功能／入口、测试文件、验证层次、关键正常与反向场景、依赖、已有或待补。原生用例列表由工具生成，不手抄。整理中移除或合并的测试，在同一文档保留简短去向说明；不另建多份流水账。

先处理已发现的日报布局数据、工作历史文案、旧 artifacts 依赖和真实模型专属入口。是否过时以现有产品契约及相关 Spec 为依据，不直接采用当前页面行为作为唯一正确答案。

### 2. 解开环境与旧 Spec 的耦合

复用 `scripts/company/web-acceptance/environment.py` 的隔离创建、归属和清理。统一给测试传入环境文件与输出目录，已有旧变量仅在必要兼容期映射到同一校验实现，不再继续添加新的 Spec 分支。

新增项目测试环境标识时同步检查 schema 命名、数据库 marker、凭证权限、账号归属与 UI/API 服务身份。验证 loopback 地址、分配端口和实际服务对应关系，不只相信一个 URL 或文件声明。继续拒绝生产地址、日常数据库及不属于本轮的 schema。

将业务种子从旧产物中提炼为可重建夹具，建立员工、同公司同事、管理员及跨公司账号。日期边界使用固定业务时钟或合法源记录；渲染日期、业务周期和服务端取数保持一致。

测试准备、启动、等待就绪、执行、失败留证和 finally 清理形成闭环。未获得资源归属时不执行清理；不停止共享数据库、Redis 或其他任务进程。

### 3. 整理并补齐测试

- 先复用 `tests/web/` 和 `tests/server/` 的有效断言，补缺口才新增；普通 Agent 契约仍在原位。
- 修正 `tests/e2e/web/` 的历史前置、定位方式与过时规则。优先使用实际可访问名称与角色；仅在必要时给生产组件补稳定语义标识，不新增测试专用成功逻辑。
- UI 故障注入套件保留业务 API 拦截并明确边界；完整流程套件使用真实业务服务，只替代外部供应商响应。复用现有受控响应支持，缺失的流式／失败响应在测试夹具中补齐。
- 按需求表落实登录、会话、卡片／附件、工作、周报、管理、反馈和恢复流程；先修已有用例再按功能归组，避免继续使用 `current-audit` 承载所有无关场景。
- 把两个已确认的真实模型专属浏览器文件移到 `eval/web/browser/`，同步相对导入、Playwright 发现配置及现有调用引用。若它们依赖已退役旅程，则先记录为历史／待修入口，不能迁移后直接声称可用。
- 核对其他混合用途脚本：可重复的产品功能检查归 tests，环境启动运维留 scripts，真实模型评测归 eval。不整目录迁移历史脚本，只有确认职责和引用后才移动。
- 选关键共享组件的小范围视觉基线，分别保留布局断言与实际截图；桌面软件流程沿用现有 Electron 测试，硬件与真实转写另列。

### 4. 加入薄运行入口与汇总

增加 `scripts/testing/project-tests.mjs`，通过 `tests/suites.json` 选择现有测试命令、路径、依赖与必需性。配置以运行组为粒度，不建立一份复制全部用例的第二数据库。

拟提供的命令（实施前尚不可用）：

```sh
npm run test:project -- --list
npm run test:project -- --suite modules
npm run test:project -- --suite web-ui
npm run test:project -- --suite web-flow
npm run test:project -- --suite desktop
npm run test:project -- --suite integration
```

`modules` 汇总当前普通模块检查；`web-ui` 检查浏览器控件和视觉，`web-flow` 检查真实服务闭环；`desktop` 是受控软件流程，`integration` 必须显式选择具体平台／外部能力。保留 `npm test` 等旧命令语义，不静默扩大默认测试范围。

接收各框架原生报告，生成简洁的可读 HTML 与机器可读 JSON。缺少原生报告时先使用适配器明确“仅命令级结果”，不能解析终端中一个 passed 字样来虚构用例通过。记录所有子进程退出状态、取消、超时及未开始的运行组；可继续互相独立的组，但最终不能吞掉前面的失败。

同一个测试在多个套件中引用时，按实际运行维度识别，避免重复计入不同用例数；多浏览器／主题的执行次数与不同测试数分别展示。沿用已有超时边界，不借本次整理无限延长。

### 5. 精简既有 CI

按需求的职责表修改 `.github/workflows/ci.yml`，统一为项目代码检查入口：

1. 日常 PR／标签任务合并到单个 Ubuntu 执行环境，安装 Node／Python 后执行格式、Lint、两端类型检查、Python 语法及两端普通构建。Python 语法可使用标准库，不导入业务、不安装完整运行依赖。
2. 移出 `test:unit`、`test:python`、`test:server`、`test:web` 以及部署／沙盒功能用例，归入本地套件；同步移除只为这些测试服务的 PostgreSQL、Redis、迁移及媒体／Office 重依赖安装。测试本身保留。
3. `desktop`、`asr`、`package` 等平台专项只在手动明确选择时执行；可选择 macOS／Windows。选择某阶段不自动再跑日常静态检查或完整业务矩阵；共用产物和 ASR 固定材料按实际依赖复用。
4. 保留 `CI required` 汇总名称，更新依赖与事件／输入条件。用条件表核对 PR、标签、手动轻量、各平台专项，以及失败、取消、跳过的结果；只接受与选择一致的跳过。
5. 核对依赖安装脚本对普通构建的实际影响，不能假定 `--ignore-scripts` 一定可用。优先以干净临时检出验证新轻量命令一次，不运行整套产品验收。没有 Windows／macOS 发布实测时明确未验证。
6. 只读核对分支保护要求与现有检查名；若必须调整远端配置才能兼容，给出具体迁移项，不关闭保护。本 Spec 不修改部署工作流及发布时的保护检查。

工作流语法与条件检查在本地完成，不因编写 Spec 触发远端执行。后续用户授权推送或试跑时，核对实际 SHA、事件和任务结果，首次失败保留；未运行远端时只报告本地验证。

### 6. 执行与验收

1. 用最小的运行器自身用例检查结果汇总、非零退出、零发现、缺依赖、必需 skip、取消和环境拒绝；这里不调用模型。
2. 运行受到目录／夹具变动影响的发现和模块检查，核对迁移前后归属；通过后不重复跑未受影响的套件。
3. 在隔离环境完成首批 Web UI 与功能闭环，保留浏览器、API／worker、数据库读回和截图证据。先修复测试假设错误；实际产品缺陷列明影响，不能改断言凑通过。
4. 执行本机支持的桌面受控流程，核对现有 CI 平台配置。没有 Windows 实际运行证据就标未执行，不拿 macOS 成功代替。物理录音、真实手机和重型外部集成按需求范围单列。
5. 对 CI 改造执行上一节的配置、条件及干净构建检查；完整测试不为 CI 改造额外重跑。
6. 独立验收阅读差异、覆盖矩阵和原始报告，按缺口补必要检查，不机械重复已通过的全部测试。所选必需功能未通过或未完成时整体不能 PASS。

视觉基线确认与功能断言分开：没有人查看的截图标“待查看”，不凭文件存在宣称样式正确。实际产品问题需要新增业务改动时先说明根因与修复范围；已授权内的局部系统缺陷可修复，涉及业务规则、架构或不可逆变更另行决策。

## 改造后的相关目录

以下为预计触及范围；仅两个已确认的 eval 专属入口计划移动，其他现有目录保留。具体新增用例名在盘点后按功能命名，不预建空目录或占位测试。

```text
specs/
├── README.md                                      [修改] 新规格入口
└── spec-083-project-testing/
    ├── spec.md                                    [新增] 需求、覆盖与边界
    └── plan.md                                    [新增] 方案与目录；结果文档在实施后按需补充

tests/
├── README.md                                      [新增] 运行指南、功能覆盖、迁移去向
├── suites.json                                    [新增] 运行组、命令和必需项
├── tooling/project-tests.test.mjs                 [新增] 运行入口与汇总的边界检查
├── web/                                          [原位修改/补充] 状态和 DOM 交互
├── server/                                       [原位修改/补充] 业务、权限和任务契约
├── desktop/、core/                               [保留/按缺口补充] 桌面模块
├── deploy/、sandbox/                             [保留/分类] 普通与外部集成检查
└── e2e/
    ├── desktop/                                 [原位检查/必要修正] 受控桌面流程
    └── web/
        ├── fixtures/                            [修改] 隔离身份、可重建数据和供应商响应
        ├── auth/、business/、settings/           [修改/补充] 当前业务闭环
        ├── navigation/                          [修改] 过时规则与响应式布局
        ├── assistant/                           [修改] 程序行为；移出两项真实模型专属入口
        └── business/conversation-lifecycle.spec.ts [新增] 真实任务提问、确认与保存；共享组件沿用现有入口

scripts/
├── testing/project-tests.mjs                     [新增] 调用原运行器、收集并展示结果
└── company/web-acceptance/environment.py          [修改] 通用测试环境身份，保留归属保护

apps/
├── web/playwright.config.ts                      [修改] 通用输出、明确套件与失败取证
└── desktop/playwright.config.ts                  [必要修改] 接收统一输出，保留平台行为

eval/web/browser/
├── playwright.config.ts                          [新增] 真实模型专属浏览器入口的独立发现
├── generated-files.spec.ts                       [移入] 来自 tests/e2e/web/assistant/
└── performance-journeys.spec.ts                   [移入] 来自 tests/e2e/web/assistant/

.github/workflows/ci.yml                         [修改] 日常轻量检查与手动平台专项，保留必需汇总
.github/workflows/deploy.yml                     [不修改] 保留实际发布保护
package.json                                     [修改] 增加显式入口，保留旧命令
README.md                                        [修改] 链接测试指南
constitution/tech-stack.md、docs/architecture.md  [修改] 仅同步变化的测试入口与职责
artifacts/project-tests/<run-id>/                 [运行产物，不提交] 汇总、原生报告和截图
```

仅在确有输出采集需要时调整现有 Vitest／Python 运行配置及相关 eval 调用处；新增依赖须说明必要性，不替换现有测试框架。CI 只按上一节调整已有职责，不添加浏览器冒烟或项目级测试任务。汇总读取已有运行产物，不为汇总、交接或验收重复执行已经通过且未受影响的检查。

## 风险、兼容与回退

| 风险                                 | 处理                                                                            |
| ------------------------------------ | ------------------------------------------------------------------------------- |
| 旧测试绑历史数据，迁移后没有真正执行 | 重建夹具，记录发现结果与必需 skip；不能只改文件路径                             |
| 通用环境入口扩大可写范围             | 复用并强化归属校验；专门验证错库、错 marker、错账号／目标与清理拒绝             |
| 测试之间依赖或互相污染               | 每组声明数据与时钟，独立拥有资源；并发只用于经证实互不影响的套件                |
| 固定响应遮盖业务缺陷                 | 在供应商边界替代，保留真实业务接口／保存及独立读回；报告明确证据层次            |
| 截图受环境差异影响                   | 固定环境、缩小对照区域；区分字体／平台差异与真实布局问题，不自动接受新图        |
| 全量检查越来越慢                     | 记录各组实际耗时，模块、UI、外部集成分开；不接入 CI，不在每次小改后重复全量运行 |

CI 精简后不再提供远端业务回归结论；本地结果须关联实际源码。保留原工作流的 Git 历史，若发现干净环境或平台能力缺口，按具体缺口修复，不默认恢复全套自动回归。

本次不涉及产品数据迁移。旧测试命令保持可用；文件移动与引用同时提交，必要回退针对完整测试整理变更，不能只回退保护检查或删除失败用例。历史 eval 证据保持原样。

## 实施后的补充文件

```text
scripts/testing/
├── project-tests.mjs       [新增] 本地选择、原生汇总与报告重建
├── read-junit.py           [新增] 标准库XML归一化，不重跑
├── python-syntax.py        [新增] CI内存语法编译，不导入模块
├── server-run.py           [新增] 自有schema服务端契约包装
├── web-run.py              [新增] 端口、服务、浏览器、finally清理
├── web-runtime.py          [新增] 仅供应商HTTP边界受控响应
└── web-serve.mjs           [新增] 已验证环境的Vite服务
tests/tooling/
├── project-tests.test.mjs  [新增] 原生结果与假绿边界
├── project-process.test.mjs [新增] 真实子进程退出/取消/强杀与源码hash
├── ci-required.test.mjs    [新增] CI选择/失败/取消/缺失条件表
└── test_project_environment.py [新增] 库、权限和身份拒绝
tests/e2e/web/business/
├── lifecycle.spec.ts      [新增] 工作到周报删除重建
└── conversation-lifecycle.spec.ts [新增] 分批材料到提问确认保存
apps/web/src/
├── app/layout/Shell.tsx   [修改] 向布局显式传递宠物可见状态
├── app/layout/pet/PetStage.module.css [修改] 窄屏头像不压搜索控件
└── components/navigation/DetailBackLink.module.css [修改] 开启宠物时窄屏返回入口避让
```

未创建独立components测试目录；共享组件继续用原有assistant/navigation测试及新增真实会话闭环检查。窄屏宠物与返回入口重叠是实际浏览器命中检查发现的局部布局缺陷，保留原断言并修复。


## 进程与 Redis 隔离返工边界

统一 runner 与直接 Web／server wrapper 共用自有 POSIX 进程组监督，直属父进程退出不代表回收完成；有界 TERM／KILL 屏障成功后才能删除 schema、媒体、凭证及本轮 Redis namespace。回收失败保留环境并明确报错。Redis 使用共享校验，只接受显式 loopback 测试 URL，未提供则禁用，禁止继承日常 namespace。

```text
scripts/testing/
├── project-tests.mjs          [修改] 共用进程组回收、直接 wrapper 监督与 Redis 校验调用
├── redis-environment.py       [新增] 显式测试 Redis 目标与运行级 namespace
├── web-run.py                 [修改] 直接入口进入监督，环境清理由监督进程负责
└── server-run.py              [修改] 同上
scripts/company/web-acceptance/environment.py [修改] 建立隔离 Redis 配置及归属清理
tests/tooling/
├── project-process.test.mjs   [修改] 父退出后代存活、清理顺序、直接包装器归属
└── test_project_environment.py [修改] Redis 继承覆盖与直接入口拒绝
README.md、tests/README.md、本 Spec implementation.md [修改] 实际限制与证据
```

新增 runner／wrapper 当前在 Windows fail-closed，保留只读 list/report；既有 Windows 原生测试入口与 CI 手动平台命令不变。不宣称 Windows 进程回收验收通过。验收仅复核本轮进程与环境边界，其他通过证据沿用，不重复运行已通过业务全集。
