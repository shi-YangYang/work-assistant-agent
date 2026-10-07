# Plan

## 对应 Spec

[Web 全页面排版与组件一致性](spec.md)。覆盖 UI-01～UI-11，只修改 Web 展示与必要的交互适配。

## 涉及模块与数据流

- 公共布局：增加轻量页面标题、列表工具栏，显式区分页面与嵌入详情；共享间距和控制尺寸，不接管页面数据。
- 详情导航：工作历史与最新版本复用同一导航模式，团队抽屉使用嵌入布局。
- 列表：工作、报告、团队、成员、声纹保留各自数据和操作，统一视觉层级与工具栏。
- 设置：单列表单限制宽度；模型服务在窄屏通过既有选中 ID 切换，编辑器和草稿状态保持稳定。
- 内容：Markdown 表头使用有效主题变量；模型用量表按真实溢出及滚动位置显示提示。

页面原有状态／URL／请求层 → 业务组件 → 布局组件。布局层不新增请求，不改变数据转换、权限或持久化。

## 改造后目录

下列为实际改造文件；`{tsx,module.css}` 表示同名组件与样式文件。除标注新增外均原位修改，不迁移业务目录。

```text
apps/web/src/
├── components/
│   ├── layout/                                      新增：纯展示布局
│   │   ├── page-header/PageHeader.{tsx,module.css}   新增：标题、元信息、操作及页面／嵌入场景
│   │   └── list-toolbar/ListToolbar.{tsx,module.css} 新增：搜索、筛选与附加操作
│   ├── feedback/ErrorNoticeScope.module.css 修改：有错误时局部避让宠物
│   ├── forms/PeriodFilter.module.css                修改：日期工具栏尺寸
│   ├── navigation/DetailBackLink.{tsx,module.css}   修改：统一返回入口，取消机械限宽
│   └── content/Markdown.module.css                  修改：表头主题配色
├── styles/
│   ├── layout.module.css                            修改：清理宽泛标题避让与外层面板规则
│   ├── controls.module.css                          修改：按钮层级与统一尺寸
│   └── patterns/
│       ├── SearchInput.module.css                   修改：搜索尺寸、底色与聚焦轮廓
│       ├── RecordLayout.module.css                  修改：列表密度与元信息
│       └── RecordDetail.module.css                  修改：页面／嵌入详情边界
├── features/
│   ├── work/components/
│   │   ├── overview/WorkOverview.{tsx,module.css}    修改：平铺页面与统一标题
│   │   ├── overview/WorkFilters.{tsx,module.css}     修改：紧凑搜索筛选
│   │   └── detail/WorkDetail.{tsx,module.css}        修改：历史导航、局部避让与抽屉适配
│   ├── reports/components/
│   │   ├── overview/ReportsOverview.tsx              修改：视图切换、容器和列表
│   │   └── detail/ReportDetail.tsx      修改：详情标题与嵌入场景
│   ├── team/
│   │   ├── components/TeamWorkspace.tsx             修改：标题、视图与抽屉上下文
│   │   ├── components/TeamFilters.tsx               修改：常用／更多条件及生效提示
│   │   ├── components/TeamResults.tsx               修改：结果行层级
│   │   └── styles/team.module.css                  修改：平铺列表与紧凑窄屏
│   ├── members/components/overview/
│   │   ├── MembersPage.{tsx,module.css}             修改：统一标题、按钮和内边距
│   │   └── MembersToolbar.tsx                       修改：搜索与数量
│   ├── model-services/
│   │   ├── hooks/useServiceDraftSession.ts           修改：保存后列表刷新期间保留服务选择
│   │   ├── hooks/useModelServiceController.ts         修改：记录已成功保存的服务回执
│   │   ├── components/ModelServices.tsx             修改：页面标题、空状态动作
│   │   ├── components/Routing.tsx                   修改：用途分配表单宽度与操作
│   │   ├── components/service/ServiceList.tsx       修改：窄屏紧凑选择器
│   │   ├── components/usage/ModelUsagePage.{tsx,module.css} 修改：关键列与横滑提示
│   │   ├── components/usage/UsageTable.tsx           新增：用量表与滚动状态
│   │   ├── components/usage/usage-display.ts         新增：用量文字和数值展示
│   │   └── styles/model-services.module.css        修改：配置面板、按钮与窄屏布局
│   ├── settings/components/
│   │   ├── account/AccountPage.tsx     修改：账户标题与单列表单
│   │   ├── appearance/AppearancePage.tsx 修改：统一标题与分组
│   │   └── rules/RulesPage.tsx         修改：规则表单层级
│   ├── feedback/components/SupportPage.tsx 修改：反馈表单宽度与操作
│   ├── voiceprints/
│   │   ├── components/VoiceprintsPage.tsx           修改：搜索位置、标题与动作
│   │   └── styles/voiceprints.module.css           修改：列表工具栏与行间距
│   └── auth/
│       ├── components/configuration/LoginMethods.tsx 修改：配置页标题
│       ├── components/configuration/LoginConfiguration.tsx 修改：配置表单布局
│       └── styles/login-settings.module.css        修改：字段宽度及分组
docs/design/README.md                                修改：补充统一排版和控件尺寸
tests/
├── web/
│   ├── business-form-validation.test.ts             修改：保留业务断言，遍历公共标题插槽
│   └── dom/report-retry-model-services.test.tsx      修改：服务切换、草稿与重复主操作
└── e2e/web/navigation/ui-layout.spec.ts              新增：真实渲染下的三项缺陷与横滑检查
scripts/company/web-acceptance/
└── ui-layout.mjs                                    新增：双角色页面截图清单与证据输出
artifacts/spec050/                                   生成，不提交：截图、覆盖清单、检查结果
specs/spec-050-web-ui-consistency/
├── spec.md                                          新增：11 项需求及验收条件
├── plan.md                                          新增：本计划
├── acceptance.md                                    新增：独立验收结果、证据及限制
└── rework.md                                        新增：验收发现的三个返工项
specs/README.md                                      修改：登记本 Spec
```

公共布局组件按职责建子目录，避免新文件继续堆在一个 components 目录。实施发现额外直接受影响的导入者时同步更新本树，不借机整理无关模块。

## 修改顺序

1. 保留审查问题编号，复现 UI-01～03；确定共享布局的页面／嵌入场景和尺寸。
2. 修复表头、历史导航、抽屉标题；接入公共标题与工具栏，移除被替代的冲突规则。
3. 按工作 → 报告 → 团队 → 成员／声纹的顺序统一列表、按钮和搜索；同步手机筛选布局。
4. 整理账户／反馈／规则／登录配置与模型服务表单；完成服务选择器、用量表横滑提示。
5. 运行 Web 相关检查，按页面清单截图并检查全部图片。问题按 UI 编号修正，不按截图数量宣称通过。
6. 新的独立验收 Agent 核对 11 项需求、双角色截图和流程回归，记录实际结果。

多个页面共享样式，交给一个实施 Agent 串行修改，避免并行改同一套布局规则。

## 接口变化与迁移

无 API、路由、数据结构、数据库或配置迁移。仅布局组件的内部 props 新增明确场景；业务回调和状态仍由原组件持有。无新依赖，不改请求频率或 CI 触发方式。

## 验证计划

写 Spec 为 S0，仅检查文档 diff、需求覆盖和路径。后续实施跨多个 Web 模块及共享样式，为 S2；验证整个 Web 子系统，不运行服务器、Electron、沙盒或真实模型套件。

### 自动检查

- 编辑时用项目 Prettier 格式化实际修改的源码；ESLint 只检查改动的 TS／TSX／脚本。
- `npm run test:web`：Web 模块回归运行一次；新增行为断言只覆盖本次改变的返回、服务选择和筛选交互，不为每项 CSS 写实现镜像测试。
- `npm run typecheck:web` 与 `npm run build:web`：确认共享组件接入、类型和页面构建。
- `npx playwright test --config apps/web/playwright.config.ts tests/e2e/web/navigation/ui-layout.spec.ts`：验证表头实际颜色、历史返回／抽屉标题几何边界、模型用量横滑与固定列；沿用现有 E2E 夹具，不依赖截图像素全相等。
- 检查通过后不重复运行；仅对新修改或明确失败扩大检查。

### 逐页截图

- 以 Spec 页面覆盖表和实际路由建立清单。基准视口为桌面 1440×1000、手机 390×844，浅色／深色，员工与管理员分开；标题相关再补 360px、768px、1024px 边界检查。
- 顶层页面全部截图。长页面补正文下部及操作区；抽屉、历史版本、筛选展开、表单错误和聚焦状态单独截图，不能只截页面首屏。
- 有数据、空数据、无结果、加载、失败按对应页面组件覆盖；通用状态可记录复用关系，不机械展开所有组合。
- `ui-layout.mjs` 复用既有隔离环境和测试身份，输出 `manifest.json`、截图及测量结果至 `artifacts/spec050/`。每项记录角色、页面、主题、视口、状态；每个 UI 编号关联至少一组对应的修复前／后证据。
- 人工逐张检查对齐、间距、颜色、层级、遮挡、可读性和点击区域。截图生成成功不等于验收通过。

### 流程回归

使用隔离数据库／测试账号和合成资料，不改真实公司数据，不需要调用收费模型。

| 流程 | 检查重点 |
| --- | --- |
| 工作列表 → 详情 → 编辑 → 历史版本 → 返回 | 条件／页码恢复，材料与修改记录仍可访问，返回入口可点击，未保存提示不丢失 |
| 员工报告待办／全部 → 筛选 → 详情 → 提交 | 常用与折叠条件生效，视图与周期切换不清空有效状态，提交结果正确 |
| 团队工作／报告 → 筛选 → 抽屉 → 上一条／下一条 | 标题与日期正常，抽屉独立滚动，选择与返回条件保持 |
| 成员搜索 → 翻页 → 详情操作 | 中文输入法、防抖、清空，少于一页也显示分页；新增、编辑、重置、删除弹窗正常 |
| 模型服务 → 切换 → 编辑／取消／保存 → 用途分配 | 草稿和密钥不丢、不重复提交；空状态只强调一个新增入口；窄屏列表切换不重置编辑器 |
| 用量表 → 横滑 → 键盘操作 → 切换主题 | 全部列可达，固定列与提示正确，无页面级横向溢出 |
| 账户／反馈／规则／声纹／登录配置 | 原字段校验、错误和保存区域可见，搜索和操作功能不变 |
| 助手及公共入口 | Markdown 表格可读；输入区按钮、附件和临时回答无布局回归；登录、外部认证结果及授权页无共享样式污染 |

沿用已有 DOM／E2E 用例覆盖现有流程，只对受影响的流程补测。外部钉钉、真实麦克风、真实模型及物理手机未实际使用时明确标注，不把模拟浏览器视口写成真机测试。

## 风险与控制

- 页面选择器影响抽屉：用显式场景隔离，并同时检查工作／报告独立页与嵌入页。
- 统一尺寸误伤助手或登录：限定样式作用域，保留输入框和书页的专用布局，不全局覆盖所有 button／input。
- 响应式切换丢草稿：保留状态所有者与组件身份，只替换服务导航的展示形式。
- 精简列表掩盖重要信息：状态、阻碍和关键操作仍可见，截断摘要可通过详情查看全文。
- 横滑关键列占满手机：限制时间列宽度，使用简短展示及完整可访问文本，并在 360px 检查其他列可读空间。
- 回滚为 Web 代码回滚；无数据迁移或不可逆操作。
