# 手机端修复返工后独立验收

## Result

PASS。MUI-001 的模型服务页大字重叠已修复，MUI-001～008 的授权修复范围通过。保留[首轮 FAIL 报告](repair-acceptance.md)和失败原图，不改写历史结论；本结论不代表手机端产品全量通过。

## Spec Coverage

- MUI-001：手机 `below` 页头使用两行网格，操作区实际高度决定标题起点。代码确认目前仅模型服务管理使用这一分支；普通页头及返回区的其他修复未被返工改动。
- MUI-002～008：核对当前产品 diff、[修复计划](repair-plan.md)、实施记录及首轮独立验收，未发现返工影响这些已通过项。重新查看长文件名、大字功能面板、材料摘要的前后原图及应用确认框原图，结果与证据一致；触摸命中、原生确认事件及资源清理记录可核对。
- 八项均有[实际前后截图索引](../../artifacts/spec073-fixes/20261017-mui-repair/screenshot-pairs.md)。MUI-008 修改前页面 PNG 不含浏览器原生确认窗口，确认内容由真实 `confirm` 事件记录支持，不能当作原生窗口外观截图。

## Tests

返工限于共享页头中的手机 `below` 分支；因首轮已发现具体重叠，独立执行该失败条件及两个相邻正常字号边界。Chromium、触屏、浅色、宠物隐藏，日常 Vite 5174 仅提供前端资源；所有业务 API 均拦截为合成响应，未知请求返回 501。

| 场景 | 添加按钮纵向范围 | 标题纵向范围 | 几何及视觉结果 |
| --- | --- | --- | --- |
| 320×568，200% 文本 | 16～74px | 82～140.8px | 间距 8px；无标题、导航重叠或整页横向溢出。 |
| 320×568，普通文本 | 16～60px | 68～97.4px | 间距 8px；普通手机布局紧凑，控件可见。 |
| 430×932，普通文本 | 16～60px | 68～97.4px | 间距 8px；宽手机布局正常。 |

200% 指先记录计算字号与数值行高，再同步乘 2，`normal` 行高保持；不等同真机系统字体设置。三张新原图均实际审阅，页面异常与未处理 API 请求均为 0。

- 失败前后严格对照：[原失败图](../../artifacts/spec073-fixes/20261017-mui-repair/acceptance-model-header-320-text200.png) → [同零模型合成服务的修复后图](../../artifacts/spec073-fixes/20261017-mui-repair/model-header-320-text200-matched-after.png)，[几何记录](../../artifacts/spec073-fixes/20261017-mui-repair/model-header-320-text200-matched-after.json)。旧标题 y=60、按钮底部 y=74，重叠 14px；新标题 y=82、按钮底部 y=74，间距 8px。修复后原图已实际查看。
- 相邻证据：[320px 普通文本](../../artifacts/spec073-fixes/20261017-mui-repair/model-header-320-normal-after.png)、[430px 普通文本](../../artifacts/spec073-fixes/20261017-mui-repair/model-header-430-normal-after.png)、[含一个模型的 320px 大字](../../artifacts/spec073-fixes/20261017-mui-repair/model-header-320-text200-after.png)。同名 JSON 保存几何、源码 SHA-256、请求和浏览器关闭记录。
- 同零模型补图首次错误地将服务选择控件定位为按钮，等待超时；该次没有形成通过证据，浏览器仍在 `finally` 中关闭。修正采集定位后仅补这张同数据对照图，未扩大产品验证。
- 复核已有服务端 `material-tests.xml`：35 项通过，0 失败、0 错误、0 跳过。Web 实施记录为 7 个相关测试文件共 62 项通过。此次没有重复执行这些已通过测试，没有修改产品源码。
- 未执行完整测试、build、lint、typecheck、真实模型、生产写入、提交、推送或 CI。所有本次浏览器资源已关闭，日常 Vite 保持运行。

## Issues / Required Rework

无本次修复范围内的未解决问题，无需继续返工。

## Regression Risks

受控浏览器证据和既有模块测试不能替代真实手机软键盘、系统字号、钉钉、实际录音及整条真实业务链路；原审计中明确未验证的项目继续保留。
