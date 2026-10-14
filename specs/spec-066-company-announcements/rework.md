# Required Rework

## 长时间阅读后返回公告列表丢失滚动位置

独立验收在管理列表的 20 条公告中滚动到 `scrollTop=2058`，进入详情停留 31 秒后返回，列表位置变成 `0`。公告缓存 30 秒后释放，Shell 在列表数据加载完成前同步写回滚动位置，被尚未撑开的容器截断；数据返回后没有再次恢复。通知公告列表共用同一机制。

- 修复应限于本次公告阅读／管理列表的返回行为，不改造无关页面的全局滚动机制。
- 返回后保留原 Tab、筛选、页码和列表位置；缓存已失效、数据需要重新加载时也有效。
- 避免刷新或用户主动滚动时反复跳回旧位置；身份切换不得继承旧账号位置。
- 补充最小加载延迟回归和真实浏览器的长停留复验；不重复已通过的发布、权限、迁移及 Agent 测试。

证据：`artifacts/spec066/acceptance-scroll-return.png`；验收过程记录 `/tmp/spec066-scroll-result.txt`。

## 修复与验证

- 公告列表使用局部 `useAnnouncementListScroll`，按列表 URL 区分 Tab、筛选及页码；返回后等待列表数据呈现，再恢复一次。用户在等待期间主动滚动会取消恢复，后续刷新不会重复跳回。存储现已从草稿迁出，见下方导航状态修复；未修改 Shell 或查询缓存的全局行为。
- `npm run test:web -- tests/web/dom/announcements/scroll-return.test.tsx`：4 项通过，覆盖阅读／管理列表缓存失效后的延迟恢复、刷新不跳回、用户操作优先及身份清理。
- Chromium 复验两种列表：均进入详情停留 31 秒，再返回并重新请求列表（延迟 100ms）；管理列表 `2058 → 2058`，通知列表 `2000 → 2000`，原 Tab／筛选／页码 URL 保留。只拦截公告 GET，未写业务数据。
- 浏览器脚本与结果：`artifacts/spec066/rework-scroll-check.cjs`、`rework-scroll-return.json`；截图 `rework-scroll-management.png`、`rework-scroll-notifications.png`。
- 改动源码已使用项目 Prettier 整理；以上为实施验证；最终独立验收已通过，见 acceptance.md。

## 导航位置不应作为未保存草稿

滚动恢复已通过，但新的独立验收确认：`useAnnouncementListScroll` 将滚动位置通过 `setDraft` 写入用户草稿，Shell 的刷新／退出保护因此把纯阅读也判为有未保存内容。Chromium 在未编辑、上传或录音的情况下，进入管理列表再进入通知后，`beforeunload.defaultPrevented` 从 `false` 变成 `true`。

- 将公告列表导航位置从用户草稿中分离，保持身份会话隔离、异步返回恢复与用户主动滚动优先。
- 不修改 Shell 对真正未保存内容的保护规则；纯阅读不会触发警告，真实编辑草稿仍受到保护。
- 定向检查纯阅读和真实草稿两种退出行为；原滚动恢复用例因相关 Hook 变化需要复验，其余主流程不重跑。

证据：`artifacts/spec066/acceptance-scroll-draft-regression.json`。

## 导航状态修复与验证

- `useAnnouncementListScroll` 改为独立的页面内存缓存，按身份与 API 登录代次隔离；不再读写用户草稿。旧代次离页清理不能写回，账号切换及同账号重新登录均从新位置开始。没有修改 Shell 的真实未保存内容保护。
- `npm run test:web -- tests/web/dom/announcements/scroll-return.test.tsx`：6 项通过，覆盖两类列表延迟返回、主动滚动取消恢复、账号及登录代次隔离、纯阅读不产生草稿、真实草稿继续保留。
- Chromium 实测：纯阅读前后 `beforeunload.defaultPrevented` 都为 `false`；填写真实公告草稿后为 `true`，离页再进入草稿仍保留。管理列表 `2058 → 2058`，通知列表 `2000 → 2000`，均经详情停留 31 秒及列表请求延迟 100ms，URL 保留。
- 证据：`artifacts/spec066/rework-navigation-state.json`、`rework-navigation-check.cjs`、`rework-navigation-management.png`、`rework-navigation-notifications.png`。没有写入业务数据；两个改动源码已使用项目 Prettier 整理，最终独立验收已通过，见 acceptance.md。
