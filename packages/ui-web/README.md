# Web UI 与品牌资源

两端通过本包共用主题、选择控件和品牌样式。品牌采用用户于 2026-09-15 确认的「相扣的 W」，表示 Work、协作与持续推进；项目及两端侧栏名称见 [README](../../README.md)。

- `src/brand.css` 使用 `assets/mark.png` 的透明轮廓，颜色取主题 `--accent`，适配浅色／深色界面。标志旁有名称时使用 `aria-hidden`。
- `assets/app-icon.png` 是同一轮廓的蓝底白标，用于 Electron 窗口／Dock。`public/` 提供 Web favicon 和触屏图标，由两端 Vite 复制；Electron 的 ICNS／ICO 在 `apps/desktop/resources/icons/`。
- PNG 标志由内置 imagegen 基于用户确认的概念稿生成，图像提示为：提取相扣 W，保持轮廓、比例和负形通道；纯靛蓝、真正透明背景、无文字／光效／阴影。图标按相同透明轮廓和蓝底白标排版生成各平台尺寸；不是矢量文件。

更新品牌时同步界面、浏览器及桌面分发资源，检查透明边缘与小尺寸效果。保留已有应用名／appId／用户数据位置；本包不承诺供原生移动界面直接复用 CSS。
