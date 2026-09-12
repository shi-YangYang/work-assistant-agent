# Implementation — Spec 010

2026-09-13 · `dev`，基线 `9912de4`，实现提交 `236a9c4`。业务实施及两次独立验收返工完成，用户审查后另有主 Agent 宽度修复；结论与覆盖统一见 [验收](acceptance.md)。

## 实现

- `App.tsx`／`Records.tsx`／`Settings.tsx`／`ModelServices.tsx`／`styles.css`：统一列表、工具栏、设置表单和用途布局，增加紧凑侧栏与容器响应式；最终内容区填满右侧空间。
- `Assistant.tsx`／`ui.tsx`：消息密度、自动增长输入、吸底操作、弹窗滚动和未保存服务的丢弃语义。
- 新增 `Markdown.tsx`／`navigation.ts`：安全基础 Markdown、携带来源与查询的逐层返回，以及对应行为测试。L01～L09 的用户行为不在此重复，见 [Spec](spec.md)。

没有新增依赖或修改共享 Electron 主题、服务端、API、数据库、CI、模型请求及已保存内容。

## 检查

| 检查 | 结果 |
| --- | --- |
| Web 类型、变更文件 ESLint、项目 Prettier、diff | 通过；仅在相关源码再次修改后复查 |
| `tests/web/navigation.test.ts` | 2 项通过：多层来源／查询、直接入口和非法返回路径 |
| `tests/web/markdown.test.ts` | 3 项通过：结构、HTML／远程图片／危险与合法链接；初次 classic JSX runtime 缺 React 导入，补入后通过 |
| `npm run build:web` | 新展示模块接入后通过 |
| 日常 Web | 主 Agent 采集逐页截图、来源返回与草稿观察，范围和数值只在验收报告记录 |

未运行全项目测试、服务端、录音、ASR、安装包或 CI；没有为视觉检查发送消息、保存配置或调用模型。

## 返工

| 来源 | 修复与定向检查 |
| --- | --- |
| 首轮独立 FAIL：原生 Esc 绕过 busy，隐藏失败弹窗 | `Modal.onCancel` 先 `preventDefault()` 再调 React `onClose`；S1 单文件 `npx eslint src/web/ui.tsx` 通过，未删除真实服务制造故障 |
| 第二轮独立 FAIL：320px 团队行宽至 333px、箭头掉行 | 手机行改头像／可收缩姓名／状态／箭头四列 Grid，时间使用第二行网格，移除 100% 宽再加左边距；S0 格式／diff，320／390px 观察后交独立复验 |
| 用户审查：右侧内容留白过大 | 按要求由主 Agent 独立移除页面动态居中边距及聊天／设置／密码／规则／来源／用途固定限宽；桌面 24px，手机保留既有边距。S0 Prettier／diff 与定向宽度观察，未重跑工程检查 |

前两项由新的独立最终验收确认 PASS；后一项是用户指定的主 Agent 自查，两者不混称。基础 Markdown 不承诺完整 CommonMark／表格；实体手机、Windows、Safari、软键盘等未验项见验收。
