# 手机端 UI 修复结果

修复范围为原审计的 MUI-001～008。原始审计报告和问题截图保留；下表记录修复结果，不将原始发现改写为通过。代码尚未提交或推送。

## 修改与截图

每组为相同视口、主题和合成数据的实际 React 页面，已逐张查看。001／002 使用 320×568，其余使用 390×844；Chromium 触屏、浅色、宠物隐藏。

| 问题 | 修改结果 | 修改前 | 修改后 |
| --- | --- | --- | --- |
| MUI-001 页头留白 | 收紧标题与返回栏；保留导航避让，操作区根据内容高度排版 | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-001-before.png) | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-001-after.png) |
| MUI-002 团队筛选 | 窄屏搜索与筛选共行，视图切换紧随，首屏能展示完整工作项 | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-002-before.png) | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-002-after.png) |
| MUI-003 长文件名 | 中文及连续英文在自身区域换行，大小与移除按钮位置稳定 | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-003-before.png) | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-003-after.png) |
| MUI-004 小按钮 | 手机附件删除、音频播放、强度标签删除扩大为独立 44px 命中区域 | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-004-before.png) | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-004-after.png) |
| MUI-005 大字面板 | 普通字号保持四列，大字下自适应为两列，标签允许换行 | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-005-before.png) | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-005-after.png) |
| MUI-006 通知入口 | 宠物隐藏时侧栏顶部显示铃铛及未读数，手机导航按钮附未读点 | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-006-before.png) | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-006-after.png) |
| MUI-007 材料说明 | 完整提供的文字汇总一句；部分、失败、未提供及图文缺口仍逐项说明 | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-007-before.png) | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-007-after.png) |
| MUI-008 删除确认 | 清空记忆、删除声纹统一使用公共 React 确认框 | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-008-before.png) | [截图](../../artifacts/spec073-fixes/20261017-mui-repair/MUI-008-after.png) |

[并排浏览全部截图](../../artifacts/spec073-fixes/20261017-mui-repair/comparison.md)；[截图条件、命中测量与清理记录](../../artifacts/spec073-fixes/20261017-mui-repair/screenshot-pairs.md)。

MUI-008 修改前是操作前页面：浏览器原生确认窗口不在页面截图中，另存实际 `confirm` 事件，未合成窗口。MUI-007 使用相同输入调用旧／新服务端真实整理函数的结果；没有调用真实模型。

## 定向验证

按 S2 验证相关子系统，没有重跑全量审计或全仓测试。

- Web：7 个相关文件共 **62 项通过**，覆盖通知显隐／计数／导航、记忆与声纹确认取消／提交／错误恢复，以及输入面板、附件、思考强度和宠物。首轮新增记忆错误测试预期与统一错误层不符，修正后只重跑对应文件。
- 服务端：材料覆盖、原件执行来源、旧说明去重、文字预载、页面实际提供及图片拒绝降级等 **35 项通过**。完整摘要要求有明确的模型提供记录，不能用预加载记录代替。
- 视觉：8 组前后图；补充 320px 深色混合附件、普通字号面板及模型标签。附件与标签控件实际命中至少 44px，采样无相邻按钮重叠；图片预览可打开、关闭。
- 独立验收首次发现模型服务页在 320px、200% 文字下按钮与标题重叠 14px，已把操作区移回正常网格排版；最终验收另见下方记录。
- 修改的前端源码与测试已用项目 Prettier 整理；新增修复截图脚本通过定向 ESLint。Python 不在当前项目格式化器覆盖范围。

Web 详细结果见 [实施记录](../../artifacts/spec073-fixes/20261017-mui-repair/web-implementation.md)；服务端见 [测试日志](../../artifacts/spec073-fixes/20261017-mui-repair/material-tests.log)与 [JUnit](../../artifacts/spec073-fixes/20261017-mui-repair/material-tests.xml)。

## 性能与范围

未增加模型调用、提示词、文件读取、网络校验或 Agent 处理阶段。通知复用已有状态；材料说明只在本地根据现有记录整理。未做真实模型耗时对照，因此不声明回答耗时的具体变化。

浏览器采用受控 API 响应，未知业务请求直接失败；没有生产写入。服务端检查使用隔离测试 schema，完成后已清理。截图浏览器均关闭，日常 Vite 服务保留。

这些证据不等同真实手机系统字号、软键盘、钉钉和桌面全量验收；原审计中未验证范围继续保留。

## 独立验收

最终 **PASS**，无本次修复范围内待返工问题。见 [最终独立验收](repair-acceptance-final.md)；保留 [首次验收与返工依据](repair-acceptance.md)。

模型服务页补充对照：[原重叠截图](../../artifacts/spec073-fixes/20261017-mui-repair/acceptance-model-header-320-text200.png) → [同数据修复后截图](../../artifacts/spec073-fixes/20261017-mui-repair/model-header-320-text200-matched-after.png)。320px、200% 文字下从重叠 14px 改为间隔 8px；320／430px 普通字号也通过。
