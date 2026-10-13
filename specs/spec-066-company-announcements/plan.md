# Plan：通知页面与公告管理

## 对应 Spec

[通知页面与公告管理](spec.md)。按本公司全员接收、标题加 Markdown 正文实施，首期无图片／附件。

## 涉及模块

- 公告模块：公司范围查询、创建、版本更新、删除、个人已读及未读统计。
- Web 通知页：全员共用，电脑和手机统一使用顶部“提醒／公告”Tab，承担阅读、已读及业务跳转。
- Web 公告管理页：仅管理员访问，提供管理列表、预览、发布、编辑及删除；与阅读流程复用 Markdown、公告内容和分页组件。
- 侧栏：原底部“汇报通知”改为进入通知页的链接，显示合计未读；主菜单“成员管理”后增加管理员专属“公告管理”。
- 基础装配：类型契约、模型注册、API／页面路由和迁移；HTTP 层聚合两个业务模块的只读摘要。

## 数据流

1. 管理员从公告管理进入新建／编辑页面，填写标题／正文并预览；发布请求通过现有认证、CSRF 及幂等入口。
2. 服务端校验管理员及公司范围，在事务内保存公告并返回真实记录；不经过 worker 或模型。
3. Shell 内挂载一份身份隔离的摘要订阅，侧栏与通知页共用；进入通知页后按当前分类分页加载列表。管理页独立分页查询，不建立第二份摘要轮询。
4. 个人通知详情呈现后或点击列表“标为已读”时提交已读的具体版本，服务端校验该公告仍可见，写入当前用户阅读记录；管理预览／编辑不触发该写入。
5. 编辑及删除使用当前版本执行；删除公告和关联已读记录后保存幂等回执，刷新列表及摘要缓存；列表删除原位更新，详情删除返回管理列表。
6. Tab、分页、详情及编辑使用 React Router，返回位置保留在 URL 和会话状态中；进入页面及选择提醒目标遵循现有录音离页拦截。草稿按身份隔离，注销时清理。

### 页面路由

| 路由 | 作用与权限 |
| --- | --- |
| `/notifications?tab=reminders` | 全员个人提醒页 |
| `/notifications?tab=announcements` | 全员公告阅读列表，只查询已发布记录 |
| `/notifications/announcements/:id` | 公告阅读详情；成功展示后标记个人已读 |
| `/announcement-management` | 管理员可用公告列表，不提供删除记录筛选 |
| `/announcement-management/new` | 管理员撰写／预览／发布 |
| `/announcement-management/:id` | 管理员查看及维护，不标个人已读 |
| `/announcement-management/:id/edit` | 管理员编辑已发布公告 |

列表页码保存在 URL：通知使用 reminderPage 与 announcementPage，管理使用 page；每页 20 条对应服务端 cursor。两类详情提供各自明确的返回入口，不把“返回通知”和“返回公告管理”混用。页面管理路由受角色保护，服务器仍独立校验角色与公司范围。

### 数据模型建议

- `Announcement`：公司 ID、标题、Markdown 正文、内容版本、发布人 ID 与显示名快照、首次发布时间、更新时间及最新操作者。发布人删除时引用置空，快照保留。删除公告使用物理删除；为兼容已迁移环境保留原 `state`／`withdrawn_at` 字段及历史查询，不批量删除已有历史数据，页面只展示已发布记录。
- `AnnouncementRead`：公告 ID、公司 ID、读者 ID、已读版本及阅读时间；公告与读者组合唯一，公告或账号删除时级联清理对应个人记录。
- 公告列表按公司、状态、发布时间及 ID 查询并建立相应索引；未读以个人已读版本小于公告当前版本（或无阅读记录）判断。
- 公告正文不按接收人数复制；发布成功不等待给每人写入通知。禁止借用个人 `ReportNotification` 和待办状态存储公告。

## 接口变化

以下路径均以 `/api/v1` 为前缀；具体响应字段在实施时写入共享契约。

| 接口 | 权限与用途 |
| --- | --- |
| `GET /announcements` | 当前公司可见列表；页面固定读取已发布公告，每页 20 条 |
| `GET /notification-summary` | 本人的 `remindersUnread`、`announcementsUnread` 和 `totalUnread`，不返回正文；管理员提醒数为 0，加入后台请求不续期名单 |
| `GET /announcements/{id}` | 按角色及公司读取详情 |
| `POST /announcements` | 管理员发布，带幂等键 |
| `PATCH /announcements/{id}` | 管理员更新标题／正文，带预期版本；不修改不可用记录 |
| `DELETE /announcements/{id}` | 管理员删除公告及关联已读记录，带预期版本和幂等键；返回 `{ok: true}`，同一次操作重试不产生额外变更 |
| `POST /announcements/{id}/read` | 当前用户标记读到的版本；不能替他人标记 |

- 列表稳定排序并返回分页信息，不能先全量拉正文再在前端分页。
- 访问他公司或已删除记录统一按不可用处理；管理写请求显式要求管理员。
- 沿用错误协议；版本冲突返回冲突提示，错误响应不伪装成空列表。
- 现有 `GET /notifications` 和 `POST /notifications/{id}/read` 继续只处理汇报提醒，保持响应兼容；聚合摘要复用同一套有效提醒范围，不混淆公告 ID 与提醒 ID。
- 摘要读取短事务内完成，两类计数失败时不伪造为 0；前端保留上次有效值并允许重试，不新增每个类别独立的后台轮询。
- 通知页与管理页均固定查询已发布公告，不提供撤回记录／回收站入口。前端入口分开，后端业务服务和记录保持同一份，不复制公告。

## 修改顺序

1. 按 Spec 明确的接收范围与内容形式，确定共享契约及迁移接续位置。
2. 一个实施 Agent 串行完成数据库、权限与服务接口，先跑公告领域定向测试。
3. 将现有汇报通知抽为页面中的提醒内容，去掉原入口／弹窗外壳；完成通知阅读页、独立公告管理页和摘要订阅，接入路由、菜单、Markdown、缓存及草稿。
4. 补充相关 API、DOM 和导航回归，检查桌面／窄屏及浅／深色。
5. 新的独立验收 Agent 对照 Spec 验收；有明确缺陷再返工，不重复已通过检查。

## 测试计划

实施涉及数据库、公开 API 和权限，按 S3 做与公告直接相关的检查，不默认跑全部 Agent 测试。实际执行结果见 implementation.md。

- 后端：使用独立测试数据库验证迁移、公司／角色隔离、发布幂等、并发版本冲突、删除、阅读版本、计数及账号删除。禁止使用线上用户数据做破坏性测试。
- 前端：`npm run test:web -- tests/web/dom/announcements/ tests/web/dom/notifications/`，覆盖双 Tab、阅读与管理操作隔离、发布失败保留内容、分页返回、未读同步、删除及账号切换。
- 导航及回归：定向运行 `tests/web/dom/shell/sidebar-navigation.test.tsx` 及受影响的导航／路由测试；确认全员通知入口、管理员专属公告管理、管理深链接防护、刷新／浏览器返回、录音离页拦截及手机抽屉收起正常。
- 后端拟运行 `npm run test:server -- tests/server/modules/announcements/ tests/server/modules/notifications/`；实施时按 runner 实际参数及独立数据库环境执行，同批涵盖事务、权限、分类合计和管理员提醒隔离。
- 对实际变更源码使用已安装 Prettier；共享契约与路由接入后执行 `npm run typecheck:web`，只对涉及源码执行 ESLint。
- 手工 UI：管理员从公告管理发布 → 员工通知未读增加 → 进入通知页切换提醒／公告 → 阅读 → 管理员编辑 → 员工重新未读 → 管理员删除；检查电脑和手机顶部 Tab、整页滚动、空／错误状态、编辑草稿及两类详情返回。
- 不调用真实模型；通过检查公告依赖和请求行为证明没有新增 Agent 阶段，不把模型速度评测作为公告验收门槛。

## 风险

- 未读版本与并发修改：已读接口携带用户看到的版本，不能直接采用请求执行时的最新版本。
- 删除和缓存：详情重新请求校验，轮询摘要只降低提醒延迟，不承诺强制收回已展示内容。
- 常驻请求：只有一个身份作用域内的摘要订阅；隐藏页面暂停，焦点恢复刷新，请求不续期会话。
- 页面状态：两条详情路由复用内容展示但区分是否标记个人已读；返回目标、页码及草稿按来源和身份恢复，避免管理预览清空个人未读。
- Markdown 安全与图片：确认既有渲染能力后按公告要求使用，避免影响聊天和工作内容的现有渲染。

## 迁移策略

- 新增迁移创建公告及已读表、外键和查询索引，迁移编号在实施时接续实际 head。
- 不读取／回填现有汇报通知；既有公司初始没有公告，界面显示正常空状态。
- 应用发布前按现有流程执行迁移；应用回滚保留新表及公告数据。生产迁移／发布需另行授权。

## 预计涉及文件

目录保持现有职责。以下为预计位置；实施中如职责变化，同步更新，不为满足目录树创建空层。

```text
apps/server/app/
├── modules/announcements/                 [新增] 公告业务
│   ├── __init__.py                        [新增] 包入口
│   ├── models.py                          [新增] 公告及个人已读模型
│   ├── schemas.py                         [新增] 请求与内容校验
│   ├── service.py                         [新增] 公司范围、版本及读写用例
│   └── router.py                          [新增] 公告 API
├── db/registry.py                        [修改] 注册公告模型
├── modules/members/commands.py            [修改] 软删除成员时清理个人阅读记录
├── modules/reports/scheduling/notifications.py
│                                         [新增] 复用有效提醒范围与未读查询
├── modules/reports/scheduling/obligations_router.py
│                                         [修改] 复用提醒查询，保留既有 API 行为
├── http/notifications.py                [新增] 聚合两类只读摘要的 HTTP 入口
├── http/routers.py                       [修改] 注册公告与摘要路由
├── http/session_renewal.py               [修改] 摘要轮询不续期登录
└── migrations/versions/0031_announcements.py
                                         [新增] 两张表与索引
apps/web/src/
├── components/overlays/
│   ├── Modal.tsx                         [修改] 支持关闭禁用、说明关联及初始焦点
│   ├── ConfirmDialog.tsx                 [新增] 通用 React 确认弹窗，无业务请求
│   └── ConfirmDialog.module.css          [新增] 紧凑布局及手机触控尺寸
├── features/announcements/
│   ├── api/requests.ts                    [新增] 公告请求入口
│   ├── hooks/useAnnouncementListScroll.ts [新增] 列表数据就绪后恢复会话内返回位置
│   └── components/
│       ├── AnnouncementsList.tsx          [新增] 可复用的公告列表
│       ├── AnnouncementManagementPage.tsx [新增] 管理列表、筛选及发布入口
│       ├── AnnouncementDetail.tsx         [新增] 区分阅读／管理来源的详情
│       ├── AnnouncementEditor.tsx         [新增] Markdown 撰写与预览
│       └── Announcements.module.css       [新增] 公告私有样式
├── features/notifications/
│   ├── api/requests.ts                    [新增] 统一摘要请求
│   ├── hooks/useNotificationSummary.ts    [新增] 单份订阅、身份隔离及前台刷新
│   └── components/
│       ├── NotificationProvider.tsx       [新增] 向侧栏及页面提供共享摘要
│       ├── NotificationEntry.tsx          [新增] 通知导航链接及未读数量
│       ├── NotificationsView.tsx          [新增] 顶部 Tab 与阅读布局，接收两类内容插槽
│       └── NotificationsPage.module.css   [新增] 跨端页面布局
├── features/reports/components/notifications/
│   ├── ReportNotifications.tsx            [修改] 转为纯提醒面板，移除重复入口及弹窗
│   └── ReportNotifications.module.css     [修改] 提醒内容样式，清理原入口样式
├── pages/NotificationsPage.tsx           [新增] 提醒与公告的跨业务页面组合
└── app/
    ├── AppRoutes.tsx                      [修改] 通知与公告管理路由及权限
    └── layout/
        ├── Sidebar.tsx                    [修改] 原位置接入通知链接
        ├── Sidebar.module.css             [修改] 通知链接高亮
        ├── Shell.tsx                      [修改] 摘要 Provider 与命令搜索入口
        └── navigation-items.ts            [修改] 通知元数据与管理员公告管理入口
packages/api-contracts/src/index.ts        [修改] 公告、阅读与分类摘要契约
tests/
├── server/modules/announcements/          [新增] API、权限、版本及并发测试
├── server/modules/notifications/          [新增] 分类合计与原提醒兼容测试
├── web/dom/announcements/                 [新增] 页面与未读行为测试
├── web/dom/notifications/                 [新增] Tab、计数、已读与阅读路由测试
├── web/dom/shell/sidebar-navigation.test.tsx
│                                         [修改] 两个入口的权限与菜单回归
└── web/navigation/                        [按需修改] 页面路由、权限及导航契约
specs/
├── README.md                             [修改] Spec 索引
└── spec-066-company-announcements/
    ├── spec.md                           [新增] 需求与待确认问题
    ├── plan.md                           [新增] 方案、目录及测试计划
    ├── implementation.md                 [新增] 实施结果与验证限制
    ├── rework.md                         [新增] 返回位置及导航状态的返工证据
    └── acceptance.md                     [新增] 独立验收结论与限制
```
