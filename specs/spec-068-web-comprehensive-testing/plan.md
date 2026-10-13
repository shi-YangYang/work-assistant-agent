# Plan：Web 全量测试与体验审计

## 对应 Spec

[Spec 068](spec.md)；覆盖依据见 [测试矩阵](test-matrix.md)。已按冻结基线执行本轮审计，结果与缺口见 [报告](report.md)；产品问题统一汇总，等待用户审查后再修复。

## 涉及模块

- Web 路由／导航／业务页面：生成角色与截图清单，复用现有页面组件和浏览器夹具。
- `tests/web`、`tests/server`：确定性行为、权限、数据、任务及故障断言。
- `tests/e2e/web`：真实 UI 交互、截图、流式、移动视口及真实 API 读回。
- `scripts/company/web-acceptance`：隔离环境、清单、合成资料、真实 Agent 运行及证据；复用 `agent-audit` 的调用／执行／写入观测。
- Spec 文档与 `artifacts/spec068`：分别承载可审查报告和不入 Git 的详细证据，不复制历史测试框架。

## 修改顺序

1. **冻结基线与预期**：记录当前代码和运行版本，从注册表更新页面／API／工具清单，展开稳定用例 ID、禁止结果及角色矩阵；保留既存失败。
2. **确认隔离环境**：复用现有创建／清理机制，为本次 suite 添加明确归属；如果要停止数据库或 Redis，必须启动本次独占容器，独立 schema 不等于独占进程。日常开发服务继续保留。
3. **适配测试资产**：只处理真实阻止执行的旧路径、旧 suite 和证据位置；不批量重写旧测试。预期过期与产品缺陷分别记录。
4. **确定性检查**：完整 Web 与公司服务相关检查各跑一次，失败按文件／场景定位；真实模型、网络和物理设备依赖不混入普通自动测试。
5. **页面与业务浏览器验收**：两角色、桌面／手机、所有路由及主要子页；每页先操作后截图并记录视觉判断，不仅产出截图目录。
6. **Agent 与性能**：冻结样本，使用真实 API→队列→worker→UI 链路；low／high 代表任务对照，保存第一轮结果和各阶段时间。
7. **故障与并发**：在独占资源内分组注入，验证恢复、数据副作用及资源清理；不在真实模型上进行 50 人压力测试。
8. **汇总和独立验收**：实施 Agent 交付报告及问题清单，再创建新的独立验收 Agent 复核；测试交付问题可以返工，产品问题只汇总报告，等待用户审查后另行修复。

## 数据流与证据

```text
冻结版本、角色与预期
  → 合成数据／隔离资源
  → 浏览器动作或真实 HTTP 请求
  → API／worker／模型／工具
  → UI、响应、数据库、业务回执、文件读回
  → 每例结果与脱敏证据
  → 覆盖映射、问题清单、耗时报告
```

每例关联角色、case ID、job／attempt、工具调用、回执及截图；时长使用单调时钟，跨进程时间线记录时钟来源。证据不得保存密钥、Cookie、原始授权头或员工资料。

## 接口变化

没有产品 API、数据库、前端功能或 Agent 提示词变化。测试脚本按需增加本次 suite／输出目录参数；继续验证既有归属标识，不能为了兼容新编号而接受任意环境。

## 测试计划

文档阶段 S0，仅审查 diff、引用及需求一致性。测试实施阶段按用户要求覆盖 Web 全量，仍执行“同一版本已通过分组不无故重复”的停止规则。

| 层级 | 入口 | 执行约束 |
| --- | --- | --- |
| Web 类型与构建 | `npm run typecheck:web`、`npm run build:web` | 实施时各一次，既存失败单列；不运行 Electron build |
| Web 确定性 | `npm run test:web` | 完整 Web 套件一次，新增覆盖仅用于实际缺口 |
| 公司 API／worker | `npm run test:server` | 使用核验过的测试环境；测试跳过项列出，不默认当作已覆盖 |
| Web 静态检查 | 项目 ESLint／Prettier 针对 Web、相关共享包和本次测试文件 | 使用现有配置，避免连带格式化全仓库 |
| 浏览器 | `npx playwright test --config apps/web/playwright.config.ts` | 接入本次环境及证据参数后运行；禁止直接使用旧默认输出覆盖历史 |
| Agent／故障／性能 | 复用现有验收和 `agent-audit` 入口 | 先核对 CLI 参数与 suite 约束，实际命令写入报告；不虚构现成的一键命令 |
| 设备专项 | 真实 iOS／Android／钉钉清单 | 与 Playwright 仿真分开；无设备或权限时说明阻塞 |

检查失败后，只运行定位所需最小子集；只修测试工具或夹具的错误。若产品问题使一组无法继续，记录阻塞和依赖关系，继续不受影响的分组。不会为了最终报告“全绿”删除断言或重复跑到成功。

## 风险

- **旧方案污染结论**：旧基线、页面标题、已移除按钮和工具流程仅作参考；当前实际实现与确认的产品规则共同确定预期。
- **环境操作误伤日常服务**：故障前校验独占资源标识；在共享进程上禁止 kill／断库／清理。
- **耗时误归因**：确认 API 与 worker 均运行冻结版本；记录模型、强度、网络和输入上下文，不把纯模型慢或测试看门狗误判为前端阻塞。
- **外部依赖不足**：真实模型、钉钉、ASR、沙盒及真机失败或不可用分开标记；模拟通过不替代真实链路。
- **数量多但缺少断言**：清单必须落实到行为证据，录屏和截图必须有人工审查结论。
- **测试本身无限扩张**：达到冻结覆盖且结论明确后停止，只有具体缺口、失败或新修改才追加。

## 迁移策略

没有产品迁移与发布。测试库按当前迁移初始化；新库／旧版本升级及备份恢复只在可销毁的合成数据副本中验证。资源清理以本次 manifest 为准，禁止按宽泛前缀清理用户资源。

## 实际涉及文件与目录

保留原目录，产品代码未改。测试脚手架与报告变更如下；原始证据保存在被忽略的 artifacts 中，Git 提交不包含完整截图和运行日志。

```text
specs/
├── README.md                                      [修改] Spec 索引
└── spec-068-web-comprehensive-testing/
    ├── spec.md / plan.md / test-matrix.md          [新增] 范围、实施、冻结矩阵
    ├── report.md / issues.md                      [新增] 结果、缺口、问题汇总
    └── acceptance.md                             [新增] 独立交付验收
apps/web/playwright.config.ts                      [修改] 测试环境、证据输出参数
scripts/company/web-acceptance/
├── agent-audit/
│   ├── faults.py                                 [修改] 精确拥有的本轮故障环境
│   └── fixed.py                                  [修改] 本轮受控调用观测
└── web-audit/                                    [新增] 复用现有审计框架
    ├── suite.json / cases.json / browser-cases.json  冻结身份约束和任务预期
    ├── server.py / http_load.py                   API、worker 和有界 HTTP 负载
    ├── serve.mjs / browser.mjs                    浏览器运行时与真实旅程
    └── screenshots.mjs / inspect.mjs / image-states.mjs  截图、检查、受控图片状态
tests/
├── server/audit/test_web_audit_load.py            [新增] 受控独立用户任务负载
└── e2e/web/
    ├── fixtures/environment.mjs / seed-layout.py [修改] 本轮环境及数据
    ├── assistant/streaming.spec.ts              [修改] 当前输入栏选择器
    ├── navigation/current-audit.spec.ts         [新增] 当前公告、清单、手机流程
    ├── navigation/{motion-layout,pages,ui-layout}.spec.ts [修改] 当前菜单与异步前提
    └── settings/{configuration,management}.spec.ts       [修改] 当前 Tab／保存行为
artifacts/spec068/20261013-0fd76fe/                 [生成，不入 Git]
├── baseline.json / coverage-draft.json           原始基线与执行前矩阵，保留不覆盖
├── coverage.json / results.json                 最终覆盖及各分组结果入口
├── screenshot-index.json / cleanup.json          截图与资源清理入口
├── checks/                                      Web 确定性原始日志及失败
├── backend/                                     API、Agent、故障、并发、语义与断言映射
├── browser/                                     E2E 历史、308 张审阅截图、真实 UI 轨迹
└── deployment/                                  部署、迁移、备份恢复与代理证据
```

没有修改 `tests/web` 的旧失败断言、产品源码、提示词、迁移、生产部署或 CI。报告中的失败留待用户决定修复；测试代码只适配确实阻止执行的当前 UI／隔离环境。
