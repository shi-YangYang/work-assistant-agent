# Noria 品牌实施计划

## 输入与范围

正式素材为用户提供的小熊 PNG：

`/var/folders/36/c4plv9vs1bl3ck8hmc7jstjh0000gn/T/codex-clipboard-58f7bdfa-f3ed-4c0a-817f-a48f18e22e11.png`

基于该形象生成白底圆形头像，归入 `packages/ui-web/brand/logo.png`；同源导出紧凑头像与各端图标。

## 改造目录

沿用原目录，不迁移业务模块。“按需”表示只有现有引用或校验受品牌更换影响时才改动。

```text
README.md                                          [修改] Noria 介绍、Logo 与功能定位
package.json                                       [修改] 产品描述；保留内部包名
constitution/
├── mission.md                                     [修改] 产品定位与品牌
└── roadmap.md                                     [修改] 当前能力和后续方向的表述
docs/
├── setup.md                                       [按需修改] 桌面显示名；保留旧数据路径说明
└── design/
    ├── README.md                                  [修改] 新品牌资源、配色与兼容规则
    └── prototype/
        ├── index.html                             [修改] 原型页面标题
        └── src/
            ├── App.tsx                            [修改] 归档原型的品牌及引用
            ├── components.tsx                     [修改] 弹窗品牌文案
            └── styles.css                         [修改] 彩色图片显示，取消反色
packages/ui-web/
├── package.json                                   [修改] PNG 品牌资源导出
└── brand/
    ├── logo.png                                   [新增] 基于小熊形象生成的白底圆形头像
    ├── mark.png                                   [新增] 同源缩略头像，供紧凑展示
    ├── logo.svg                                   [删除] 消除引用后的旧单色标志
    ├── web/
    │   ├── favicon-16.png                         [替换] 标签页小图标
    │   ├── favicon-32.png                         [替换] 标签页图标
    │   └── apple-touch-icon.png                   [替换] 手机网页图标
    └── desktop/
        ├── app-icon.png                           [替换] 窗口与 Dock 图标
        ├── app.icns                               [替换] macOS 应用图标
        └── app.ico                                [替换] Windows 应用图标
apps/web/
├── package.json                                   [按需修改] 产品描述；保留内部包名
└── src/
    ├── index.html                                 [修改] 标题与图标缓存版本
    ├── app/Sidebar.{tsx,module.css}                [修改] Noria 品牌与彩色图片
    ├── components/PageLoading.{tsx,module.css}     [修改] 彩色加载标志
    └── features/
        ├── auth/components/
        │   ├── Login.tsx                          [修改] 登录标题
        │   ├── LoginBook.tsx                      [修改] 书页品牌与欢迎文案
        │   └── DesktopConnect.tsx                 [修改] 桌面授权文案
        ├── assistant/components/MessageCard.tsx   [修改] 助手发送者名称
        └── voiceprints/components/VoiceprintsPage.tsx
                                                   [修改] 桌面端说明
apps/desktop/
├── package.json                                   [修改] 桌面端产品描述
├── electron-builder.json                          [修改] 显示名与产物名；保留 appId
└── src/
    ├── main/main.ts                               [修改] 窗口标题；保留内部数据身份
    └── renderer/
        ├── App.tsx                                [修改] 桌面品牌
        ├── styles/brand.css                       [修改] 彩色标志展示
        └── index.html                             [修改] 标题与图标缓存版本
scripts/desktop/
├── launch.mjs                                     [按需修改] 开发包名称与图标缓存
└── test-package.mjs                               [修改] 从打包配置读取应用路径
tests/
├── e2e/desktop/package.spec.ts                     [修改] 新安装名称与产物路径
└── web/                                           [按需修改] 受品牌文案影响的既有断言
specs/
├── README.md                                      [修改] 规格索引
└── spec-040-company-cloud-assistant-brand/
    ├── spec.md                                    [新增] Noria 定义与全端品牌范围
    └── plan.md                                    [新增] 改造目录与实施验证
```

实施发现其他在用品牌入口时，仅补齐同类引用，并同步目录树；不改写历史文档或扩大功能范围。

## 修改顺序

1. 保存正式源图，导出头部标志、浏览器和桌面图标；在实际显示尺寸检查构图。
2. 更新品牌资源导出，替换 Web、Electron、加载页与原型的旧 mask 和图片引用。
3. 更新品牌名称与介绍，保留功能名称；同步 README、使命、路线及品牌规范。
4. 更新桌面显示和产物名称，校正启动器及包检查路径；保留内部身份和签名策略。
5. 清理无引用的旧 Logo，按范围验证，由独立验收 Agent 检查实现及兼容性。

## 数据流与接口

原图 → 紧凑标志／平台图标 → 既有界面和应用包。品牌资产随构建分发，不依赖远程图片服务。业务 API、任务执行、权限和持久化均不变，无数据库迁移。

## 验证

- 文档改动为 S0：只核对 diff、目录引用与需求，不为文档运行测试或构建。
- 实施时格式化本次涉及的源码；Web 重点截图检查侧栏、加载页、登录封面／展开／错误状态、手机与深色显示，并运行受影响的最小检查。
- 桌面打包元信息属于 **S3 范围**：检查开发启动及实际生成的包名、图标和窗口标题；按项目规则用 `npm run dev:electron` 在日常环境只读核对原有会议与配置，自动化测试沿用隔离数据。
- 核对内部包名、appId、协议、用户目录与密钥身份未变；不得为验证覆盖用户真实资料或清除登录配置。
- macOS 与 Windows 分别记录实际验证范围。未运行某平台的安装、升级或任务栏检查时明确写“未实测”；不为此品牌改动默认运行真实模型推理、全量后端或完整双平台业务测试。

## 风险与回退

- 头像使用纯白圆形底、圆形外透明，紧凑位置采用同源缩略图；深色模式也保留白底，不套单色遮罩或改变整体 UI 配色。
- 浏览器与操作系统可能缓存旧图标，更新资源版本并区分缓存残留与产物错误。
- 桌面显示名变化可能影响启动器和包测试的硬编码路径，优先从构建配置读取名称。内部身份稳定，避免密钥和数据失联。
- 回退只恢复品牌资源、显示名、引用与文案，不迁移或回滚业务数据。
