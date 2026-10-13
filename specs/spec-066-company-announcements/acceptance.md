# Acceptance

## Result

PASS

公告发布／阅读／维护及权限主链路满足要求。前两轮独立验收分别因列表返回丢失滚动位置、纯阅读产生未保存内容警告判定 FAIL；两项均已返工。最终独立验收核对导航 Hook、身份代次、草稿保护及对应执行证据，未发现本次范围内待返工问题。

## Spec Coverage

- 已独立审查公司／角色隔离、CSRF、发布幂等、并发版本、旧版本已读、撤回、软删除读者及作者快照。服务端范围检查与实施测试覆盖一致，未发现本次范围内的权限阻塞。
- 已审查单份摘要订阅、隐藏页暂停、身份代次及迟到响应隔离、不续期登录、原汇报提醒兼容；通知阅读和管理预览相互隔离。
- 已审查安全 Markdown、长度限制、失败保留草稿与发布幂等键、冲突后显式重新读取、路由及菜单权限。未增加模型调用或容器。
- 已核对主 Agent 的浏览器证据：发布→阅读→编辑重新未读→撤回、普通用户管理深链接保护、Tab 历史、移动抽屉与草稿恢复。查看最终移动编辑截图，版式遵守既有设计。
- 最终导航复核：列表位置使用独立内存缓存，按公司／成员／角色与 API 登录代次隔离；旧代次清理回调不能写回新缓存。待列表数据就绪后恢复一次，主动滚动优先，后续刷新不跳回；不再读写用户草稿，Shell 的退出／刷新保护规则未改变。

## Tests

- 复用实施报告中已通过的定向 API、迁移、DOM、类型及格式检查；未重复执行已通过检查。详细命令和数量见 [implementation.md](implementation.md)。
- 复用 `artifacts/spec066/ui-flow.json`、`mobile-check.json` 和最终截图的主 Agent 实测结果。
- 首次验收独立执行一项针对列表位置恢复的 Chromium 复现：使用隔离 Web 5199、测试管理员身份，拦截公告 GET 返回固定 20 条记录，列表读取延迟 100ms；未改业务数据。滚至底部后进入详情，停留 31 秒，再点“返回公告管理”。恢复前 `scrollTop=2058`，返回并加载完成后 `scrollTop=0`，页面高度前后均为 2758。证据：`artifacts/spec066/acceptance-scroll-return.json`、`acceptance-scroll-return.png`；复现脚本 `acceptance-scroll-check.cjs`。
- 最终返工验证复用 6 项已通过的定向 DOM 用例，覆盖两类列表的延迟恢复、主动滚动、刷新、账号切换及同账号重新登录、迟到清理回调与真实草稿保留。最终独立验收阅读代码及断言，没有重复运行。
- 核对 `artifacts/spec066/rework-navigation-state.json` 与 `rework-navigation-check.cjs`：两类列表均经过详情停留 31 秒和列表请求延迟 100ms，管理列表 `2058 → 2058`、通知列表 `2000 → 2000`，返回 URL 保留。纯阅读前后 `beforeunload.defaultPrevented=false`，真实编辑后为 `true`，离页再进入仍保留输入。对应截图为 `rework-navigation-management.png`、`rework-navigation-notifications.png`。
- 没有执行全量套件、正式构建、真实模型或物理手机／钉钉 WebView 测试。

## Issues

### 已修复：详情停留超过缓存保留期后，返回公告列表丢失阅读位置

`apps/web/src/features/announcements/components/AnnouncementsList.tsx:23` 使用的资源在无订阅 30 秒后释放（`apps/web/src/lib/query-resource.ts:42`）。链接仅传递列表 URL（`AnnouncementsList.tsx:53`），返工前依赖 Shell 路由切换时同步设置 scrollTop（`apps/web/src/app/layout/Shell.tsx:77`）。当返回需要重新加载列表，恢复发生在内容到达前，可滚动高度不足使位置被截为 0，数据到达后没有再次恢复。

首次独立复现在管理列表确认，个人通知列表共用同一机制。局部 hook 现已等待列表数据后恢复一次，并在用户主动操作后放弃恢复；两条实际浏览器复验保留原 URL、分类、筛选及页码。管理列表 `2058 → 2058`，通知列表 `2000 → 2000`，均经历详情停留 31 秒及列表延迟 100ms。证据：`artifacts/spec066/rework-scroll-return.json`、`rework-scroll-check.cjs` 和两张 `rework-scroll-*.png`。4 项定向 DOM 回归通过；第二轮独立验收复核代码和既有执行证据，未重复这些检查。

### 已修复：只阅读公告也产生未保存内容警告

上一版 `apps/web/src/features/announcements/hooks/useAnnouncementListScroll.ts:55` 在列表离页时通过 `setDraft` 保存滚动位置。`apps/web/src/app/layout/Shell.tsx:111` 和 `:120` 将所有草稿键视为未保存用户内容，因此即使仅阅读列表，也会启用刷新／关闭页面警告及退出登录确认。

第二轮独立 Chromium 最小复现：新建身份浏览器上下文，打开聊天页时派发可取消 `beforeunload` 事件，`defaultPrevented=false`；仅依次点击“公告管理”和“通知”，没有编辑、上传或录音，再派发同事件，`defaultPrevented=true`。证据：`artifacts/spec066/acceptance-scroll-draft-regression.json`。据此判定 FAIL，要求导航状态与草稿分离。

最终实现已迁至独立导航缓存，代码不再调用 `setDraft`；清理仅在缓存实例和 API 代次均未变化时保存位置。6 项 DOM 及上述 Chromium 返工证据验证纯阅读不再触发警告，真实编辑保护和输入恢复仍有效。最终独立复核通过。

## Regression Risks

- 服务端架构检查的既存失败 `document → checklist → document` 已核对 HEAD 中双向导入及本次未改两文件，不归因于本次公告实现，也不将它表述为通过。
- 实际钉钉 WebView 与物理手机未测试；已有移动证据来自 390px Chromium。

## Required Rework

无。本次范围内两项返工均已完成；历史失败与修复证据保留在上文及 [rework.md](rework.md)。
