# 品牌资源

品牌资源统一放在 `brand/`，沿用「相扣的 W」轮廓，使用中性黑色。

```text
brand/
├── logo.svg                 # 唯一标志源文件：黑色、透明底
├── web/
│   ├── favicon-16.png
│   ├── favicon-32.png
│   └── apple-touch-icon.png
└── desktop/
    ├── app-icon.png          # 窗口／Dock 与 README：浅底黑标
    ├── app.icns              # macOS 安装图标
    └── app.ico               # Windows 安装图标
```

界面从 `@paa/ui-web/logo.svg` 获取轮廓，浅色显示黑色，深色通过各端自己的 CSS 显示浅色。Web 的尺寸与样式在 `Sidebar.module.css`，Electron 在 `styles/brand.css`；本包不导出 CSS。标志旁有名称时使用 `aria-hidden`。

更新标志只改 `logo.svg`，再导出 `web/` 和 `desktop/` 所需尺寸，不另存应用私有副本。窗口图标保留浅色底，避免黑标在深色桌面上消失。资源更新不改变应用名、appId 或用户数据位置。
