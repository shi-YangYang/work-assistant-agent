# 实施报告

## 实现

- 删除登录后全局 Topbar／Breadcrumbs，保留业务标题、详情返回、侧栏搜索、通知和窄屏导航。
- Shell 常驻宠物浮层，不占行高；原版白底小熊与名称胶囊贴合，点击打开共享主题弹窗。
- 使用原 `mark.png` 和最初的 `pet/blink.png`，仅眼部约每 8 秒短眨眼 160ms；其他页面静止，隐藏时暂停，减少动态效果时禁用。
- 闭眼素材失败保留原头像，原头像失败显示 N；保持主题同步、草稿及焦点恢复。
- 已删除建模源码、视频、海报、转头素材、临时模型／样稿／预览和下载包。保留原布局验收证据。

## 验证

恢复眨眼按 S1，源码使用项目 Prettier。`npm run test:web -- tests/web/dom/noria-pet.test.tsx`：5/5 通过；随后仅恢复原 8 秒 CSS 周期，由浏览器核对，不重复行为测试。

浏览器查看真实组件的睁眼、闭眼与外观弹窗：没有 video，图片没有 transform，只有眼部 8 秒动画。截图 `artifacts/spec048/blink-preview/restored.jpg`。新的独立验收 Agent 已检查源码和截图，恢复实现通过。

原布局的 152 项相关模块检查、16 项导航流程、窄屏避让检查与类型检查属于先前验证；相关日志和截图保留在 `artifacts/spec048/browser/`、`rework/`，此次未重复执行。未运行后端／Electron／完整构建，未 commit／push，未触发或查询 CI。
