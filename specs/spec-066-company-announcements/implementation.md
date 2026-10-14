# Implementation Report

## Summary

实现统一通知页面与管理员公告管理：侧栏底部全员“通知”，顶部提醒／公告 Tab；管理入口位于成员管理之后。支持标题与 Markdown 正文的发布、预览、编辑和撤回，沿用安全 Markdown、会话草稿、分页与返回控件。

## Files Changed

- `modules/announcements/`、`0031_announcements.py`：公司范围公告、版本阅读记录、幂等发布／撤回、并发版本保护、纯文本列表摘要。旧汇报提醒查询复用到轻量摘要；后台摘要不续期登录。
- `modules/members/commands.py`：成员软删除时删除个人已读记录，公司公告及作者显示名快照保留；物理删除的外键策略也已验证。
- `features/announcements/`：管理列表、详情、编辑；读取详情后标记实际展示版本，管理预览不标个人已读。失败保留草稿和发布幂等键，冲突需显式读取最新内容。
- `features/notifications/`、`pages/NotificationsPage.tsx`、Shell／Sidebar／AppRoutes：独立通知页面、共享身份作用域摘要、URL 分类／分页与返回、管理员路由保护；手机关闭抽屉与录音拦截沿用现有导航。
- 共享 API 契约及公告／通知／导航回归测试；目录明细见 plan.md。

## Important Decisions

- 公告正文只有一份，按用户及内容版本记录阅读；无实质修改不会推进版本，旧版本已读不会标记新版本。
- 只有 Shell 持有摘要刷新计时器；分类页和侧栏共用资源，后台标签页暂停定时查询。身份代次变化释放旧缓存，迟到响应不得写入新账号。
- 提醒和公告组合留在 pages，避免业务 feature 之间引入反向装配；安全 Markdown 不渲染 HTML、嵌入图片或危险协议链接。
- 应用回滚保留新增表；迁移 downgrade 显式拒绝删除公告数据。无 Agent、worker、模型及真实模型调用改动。

## Tests

所有后端测试只使用 root 创建的独立 PostgreSQL `paa_company_test`，迁移测试使用该库中的随机独占 schema，未使用日常数据做测试。

- `pytest -q tests/server/modules/announcements tests/server/modules/notifications`：初始 API 9 项通过，覆盖幂等重放、公司／角色／CSRF、版本、撤回、阅读、分页、成员删除与摘要兼容。后续摘要改动仅重跑分页／删除用例及新增纯文本摘要用例：2 项通过。
- `pytest -q tests/server/modules/announcements/test_migration.py tests/server/test_architecture.py`：迁移 2 项通过（空库及已有数据）；架构 12 项通过、1 项既存失败，详情见下。
- `npm run test:web -- tests/web/dom/announcements tests/web/dom/notifications tests/web/dom/shell/sidebar-navigation.test.tsx tests/web/navigation/routes.test.ts tests/web/architecture.test.ts`：29 项通过。
- 后续修改定向验证：公告详情 DOM 5 项通过；摘要生命周期 DOM 2 项通过；补充账号切换和迟到响应 DOM 1 项通过。验证包含 React StrictMode 的已读及单份摘要请求、后台暂停、URL／历史、失败幂等重试、草稿、Markdown 和冲突处理。
- `npm run typecheck:web` 通过。实际改动 TS／TSX 文件 ESLint 通过；已安装 Prettier 整理所有本次覆盖源码，`git diff --check` 通过。
- 主 Agent 在隔离 API／Web 和 Chromium 验证发布→读取→编辑重新未读→撤回、普通用户管理深链接拦截、移动抽屉、草稿恢复、深色与移动详情／编辑避让。证据在 `artifacts/spec066/ui-flow.json`、`mobile-check.json` 与截图。

## Known Limitations

- 既存架构测试 `test_dependencies_are_acyclic_and_do_not_import_entrypoints` 失败，路径是 `app.modules.work.content.document → checklist → document`。`git show HEAD:apps/server/app/modules/work/content/document.py` 第 108 行已导入 checklist；`git show HEAD:apps/server/app/modules/work/content/checklist.py` 第 142 行已导入 document。两文件本次未修改；不将该结果表述为通过。
- 实际手机、钉钉 WebView 未实测；移动尺寸使用 Chromium 验证。没有运行全量服务器／Agent 测试或正式构建。
- 根 Agent 已执行本地日常数据库迁移；实施 Agent 只使用隔离库测试，没有线上发布、生产迁移、commit 或 push。

## Remaining Questions

无实施阻塞，等待独立验收。
