# 实施计划

## 状态与模块

恢复原版小熊眨眼。布局与主题保持既定行为，删除建模源码、视频和转头样稿。

- Shell：删除 Topbar，统一挂载宠物和窄屏导航开关；按路由传入闲置动效开关，复用同一实例。
- 外观：提取已有主题选择展示，宠物弹窗与设置页共用。
- 导航：保留搜索、通知及详情返回，移除面包屑专用请求。
- 品牌：原 `mark.png` 配合最初的 `pet/blink.png`，CSS 只切换眼部；头像与标签重叠贴合，悬浮不附加动作，图片失败静态回退。

## 数据流与接口

```text
Shell → 常驻 NoriaPet → NoriaAppearanceDialog → ThemePicker
                                                  ↓
                                        现有 lib/theme.ts
                                                  ↓
                             原本地偏好 + 根节点 data-theme

Sidebar → 搜索／汇报通知（原有行为）
详情页面 → DetailBackLink → 现有 detailReturn 与路由 state
```

无 API、schema 或数据库迁移。主题仍是当前浏览器偏好，不改成公司全局设置，也不新增服务端账号同步。

## 改造目录

`[增]` 新增，`[改]` 原位修改，`[删]` 移除；API 文件只删除确认无调用的面包屑辅助函数。

```text
apps/web/src/
├── app/layout/
│   ├── Shell.tsx、Shell.module.css                   [改] 常驻入口、浮层定位基准与路由动效
│   ├── Sidebar.tsx、Sidebar.module.css               [改] 迁入员工通知入口
│   ├── Topbar.tsx、Topbar.module.css                 [删] 旧整条顶栏
│   ├── Breadcrumbs.tsx、Breadcrumbs.module.css       [删] 旧全局面包屑
│   └── pet/
│       ├── NoriaPet.tsx、NoriaPet.module.css          [增] 形象、动作与点击入口
│       ├── NoriaAppearanceDialog.tsx                [增] 外观模态框
│       ├── NoriaAppearanceDialog.module.css         [增] 模态框私有布局
│       └── PetStage.tsx、PetStage.module.css          [增] 不占行高的悬浮入口与移动导航按钮
├── components/
│   ├── appearance/
│   │   ├── ThemePicker.tsx                          [增] 从现有外观页提取主题选择
│   │   └── ThemePicker.module.css                   [增] 共用主题选择样式
│   ├── feedback/ErrorNoticeScope.module.css        [改] 窄屏错误提示出现时局部避开浮层
│   └── navigation/
│       ├── DetailBackLink.tsx                       [增] 详情页简洁返回，复用返回上下文
│       └── DetailBackLink.module.css                [增] 返回链接就近布局
├── features/
│   ├── settings/components/appearance/
│   │   ├── AppearancePage.tsx                       [改] 复用 ThemePicker
│   │   └── AppearancePage.module.css                [改] 选择器样式提取后，仅保留局部间距
│   ├── assistant/api/requests.ts                    [改] 清理面包屑专用读取
│   ├── assistant/components/conversation/
│   │   ├── Conversations.module.css                 [改] 窄屏标题、操作避开浮层
│   │   └── PersonaPicker.module.css                 [改] 窄屏人设入口就近换行
│   ├── reports/api/requests.ts                      [改] 清理面包屑专用读取
│   ├── team/api/requests.ts                         [改] 清理面包屑专用读取
│   ├── work/api/requests.ts                         [改] 清理面包屑专用读取
│   ├── work/components/detail/WorkDetail.tsx         [改] 返回入口与历史版本去重
│   ├── work/components/overview/
│   │   ├── WorkOverview.tsx                         [改] 紧凑的新建按钮保留可访问名称
│   │   └── WorkOverview.module.css                  [改] 窄屏标题与操作避让
│   ├── reports/components/detail/ReportDetail.tsx    [改] 返回入口
│   └── reports/components/notifications/
│       └── ReportNotifications.tsx                  [改] 侧栏入口的可选标签与样式
├── pages/SourcePage.tsx                             [改] 来源页返回入口
├── styles/layout.module.css                        [改] 保留窄屏标题，局部避开导航与宠物
└── utils/navigation.ts                             [改] 保留返回语义，清理仅面包屑使用逻辑
packages/ui-web/
├── brand/pet/
│   └── blink.png                                  [增] 最初的闭眼素材；取消建模与转头资源
└── package.json                                    [改] 仅导出新增品牌资源
tests/
├── web/dom/noria-pet.test.tsx                       [增] 弹窗、主题与不打断页面
├── web/dom/assistant-requests.test.tsx              [改] 移除面包屑夹具，保留请求去重断言
├── web/request-contracts.test.ts                   [改] 同步移除失效辅助入口
├── web/navigation.test.ts                          [改] 去除面包屑专用断言，保留详情返回
└── e2e/web/navigation/pages.spec.ts                 [改] 新入口、全路由视觉与导航回归
docs/design/README.md                               [改] 新顶部布局、宠物动效约束
```

复用 `lib/theme.ts`、`components/overlays/Modal.tsx`、`useNavigationDrawer.ts` 及 `ReportNotifications` 的既有行为；通知组件仅增加可选展示参数，不改变请求与通知合同。

## 实施顺序

1. 制作并查看宠物动作素材，确保白底圆形小熊保持一致。
2. 提取 ThemePicker，接入宠物与外观模态框，保留旧主题存储。
3. 用 PetStage 替换 Shell 中 Topbar，处理导航开关、覆盖定位、点击穿透、右侧居中和错误出口位置。
4. 将通知挂到侧栏；补齐详情返回；清理无调用的面包屑辅助代码及相关测试夹具。
5. 检查所有登录后路由的首屏、长内容、加载、错误和手机布局；按实际冲突就近调整，不顺带重做业务页。
6. 更新设计规范，由新的独立验收 Agent 对照 Spec、diff 与验证证据验收。

## 风险与处理

- 宠物必须在路由切换外常驻，不以整页覆盖层拦截内容点击；固定布局尺寸，不因帧切换而抖动。
- 不同时保留旧顶栏与同高度装饰空条。宠物与必要移动按钮均为覆盖层，不预留整行空间；仅对窄屏中实际相撞的业务操作就近避让。
- 移除面包屑会影响详情返回与请求测试。保留实际导航链路和身份隔离断言，不仅删除失败测试。
- 侧栏通知仅挂载一份；不因移动位置产生重复请求或改变已读状态。
- CSS Modules 隔离宠物动作，主题继续由原根节点控制，不覆盖危险／成功等语义色。
- 无数据迁移；回退为代码与资源回退，主题原存储键保持兼容。

## 验证计划

规格文档按 S0 检查 diff、需求与路径，不为文档运行测试或构建。

业务实施按 S2：涉及全局布局、导航与共享主题组件。运行受影响模块检查，不默认跑公司后端、Electron、真实模型或整个项目套件。

- 新增有行为价值的定向测试：弹窗开关／键盘／焦点、主题跨入口同步和持久化、切页保持形象、导航返回、草稿保留。
- 一次运行受影响的 Web 测试及 `npm run typecheck:web`；修改过的源码使用安装好的 Prettier，并做定向 ESLint。
- 更新并运行 `tests/e2e/web/navigation/pages.spec.ts`：管理员所有可访问页面、员工报告／通知、详情／历史版本、来源回退与手机导航。
- 实际浏览器查看宠物动作；截图覆盖登录后全部路由的桌面浅／深色与手机布局，至少 390px 和 360px 窄屏；包含长内容与错误状态。
- 验证工作助手与其他页面切换只改变闲置动效开关，位置、尺寸和实例保持稳定；通过减少动态效果偏好与资源加载失败场景验证静态回退；网络记录确认宠物／主题操作不新增业务请求。
- 截图与日志放 `artifacts/spec048/`，验收如实区分通过、失败和未执行；检查通过后不无理由重复。

## 视觉返工验证

以实际浏览器对照 Muse 的浮层、名称胶囊和形象动作。重点检查桌面助手有消息／空会话、工作列表／详情、设置及 360px／390px 窄屏：首屏内容没有被整体下推，滚动内容经过宠物下方，浮层外点击有效，页面标题和业务动作不被遮挡。相关行为未改变的已通过检查不重复运行；新增布局风险用定向浏览器验证，样式与源码按原配置格式化。

恢复眨眼按 S1 局部组件修改验证：仅运行宠物组件测试，浏览器检查 52px 入口、96px 弹窗中的睁眼／闭眼、主体稳定及主题入口；不重跑已通过的其他业务检查。删除建模源码、模型、下载包、视频和转头预览，保留布局验收证据。
