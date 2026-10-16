# 浏览器验证

## 环境与证据边界

- 专用 PostgreSQL `spec072_browser` schema、Redis namespace、合成公司和账号；Web `127.0.0.1:5198` → API `127.0.0.1:18072`。
- 真实上传、队列、worker、LibreOffice、Poppler、主模型请求装配、流式发布和数据库持久化；只替换最外层模型传输响应。没有使用线上账号或员工材料。
- 浏览器响应是受控测试内容，不用于评价真实模型的准确性或回答耗时；真实 low/high 对照见 [performance.md](performance.md)。
- 初始页面验证后，已重启专用 API／worker 复验缓存、损坏文件、中断及刷新恢复；界面使用当前源码。测试结束已停止本次拥有的 5198／18072 服务并恢复浏览器视口，未停止用户日常开发服务。

## 已观察到的流程

| 流程 | 结果与证据 |
| --- | --- |
| 桌面 1280×900 上传 Word 混排和扫描 PDF，尚未发送 | 草稿附件可见；数据库均为 `unsent`、revision 0，任务 0、分段 0 |
| 手机 390×844 移除扫描 PDF 后重新添加 | 卡片数量由 2→1→2，未触发 Agent |
| 发送扫描 PDF | 真实解析保留无文字页；卡片显示“可查看页面”，主模型收到 1 个实际图像块 |
| 追问 Word 与扫描 PDF 的第一页及正文 | `read_document` 实际返回文字和页面来源，最终主模型收到 2 个图像块，持久化 2 个页面已提供记录 |
| 打开 Word 页面引用 | 显示“转换后第 1 页”，实际图像 1113×1440，包含正文和嵌入图表 |
| 手机刷新后打开扫描页引用 | 历史引用保留，实际图像 1440×1037，弹窗可关闭；原文件下载入口仍在 |
| 重启后再次追问相同两页 | 两个 `cacheHit=true`，实际主模型图片块 2；原生转换／渲染日志仍为此前 3 条，本次新增 0 |
| 正常 TXT＋损坏 PDF 一起发送 | PDF 显示解析失败，TXT 中 ZQ-482／17／验收后交付均进入答复，来源可见；没有整条失败或伪造页覆盖 |
| 生成期间中断 → 再次问材料 → 刷新 | 中断任务保持 `cancelled`，保留的部分正文来源显示“待核对”；后续任务完成并有正确来源，刷新后两种终态不相互覆盖 |

首次受控响应遗漏工具名称映射，提前结束但未产生业务写入；修复的是本地验证脚本，后续文字／页面来源证据来自第二条追问。第三次追问处于渲染器指纹更新期间，不作为缓存命中证据；缓存结论来自后续任务 `acb184e6-a697-40da-a502-b6d525040504`。取消用例在受控模型中设置一次有限延迟，实际点击时已进入回答生成阶段，不冒充每个解析／转换阶段的浏览器取消验证。

## 本地证据

- [桌面发送前](../../artifacts/spec072/browser/desktop-upload-unsent.png)
- [手机发送前](../../artifacts/spec072/browser/mobile-upload-unsent.png)
- [桌面 Word 页面引用](../../artifacts/spec072/browser/desktop-word-page-source.png)
- [手机 Word 页面引用](../../artifacts/spec072/browser/mobile-word-page-source.png)
- [手机刷新后扫描页引用](../../artifacts/spec072/browser/mobile-refreshed-scan-source.png)
- [手机混合成功／失败材料](../../artifacts/spec072/browser/mobile-mixed-failure.png)
- [手机中断状态](../../artifacts/spec072/browser/mobile-cancelled.png)
- [中断后恢复并刷新](../../artifacts/spec072/browser/mobile-recovered-refreshed.png)
- 主模型图片块、工具调用记录：`artifacts/spec072/browser/provider-events.jsonl`
- 原生转换／渲染记录：`artifacts/spec072/browser/native-events.jsonl`
- 任务页面记录摘要：`artifacts/spec072/browser/job-evidence-final.json`

其余组合与故障测试由后端集成用例验证，本报告不将未执行项目表述为通过。
