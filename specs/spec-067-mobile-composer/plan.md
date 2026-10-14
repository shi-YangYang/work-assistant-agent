# Plan：手机端聊天输入栏与功能面板

## 对应 Spec

[手机端聊天输入栏与功能面板](spec.md)。按确认的输入栏与“＋”面板方案实施。

## 涉及模块

- `MessageComposer`：单个输入状态来源，按视口调整主栏布局、发送按钮可见性和面板入口。
- `MobileComposerPanel`：手机功能面板与带名称的入口，不持有业务请求或副本草稿。
- `useMobileComposerPanel`：面板、文本焦点、录音和附属浮层之间的显示协调。
- 现有 controls 与附件组件：按需增加面板展示形态，复用回调及当前状态，避免创建两套菜单／轮询。
- `ConversationChat`：继续通过原有输入容器测量更新消息底部空间；只有接线或滚动补偿确有需要时调整。

## 修改顺序

1. 确认主要操作布局与隐藏项；先完成单行输入栏和面板的状态切换，保持业务回调不变。
2. 接入图片、文件、工作引用及上下文；明确父面板与附属浮层的开关关系。
3. 接入强度和执行权限行，沿用真实选项、保存状态及自主执行确认。
4. 调整附件／引用区域和录音反馈，保持点击及长按的完整流程，覆盖键盘与滚动行为。
5. 实施 Agent 完成定向验证后，由新独立验收 Agent 按 Spec 验收；仅针对具体失败返工。

## 数据流

- 草稿与发送继续走 `ConversationChat → MessageComposer → useMessageSubmission`。
- 手机“＋”只改变面板状态；选择功能调用现有 `addFiles`、workReference、reasoning、execution 与 context 操作。
- 录音使用现有 `VoiceRecordButton` 与 `useRecording`，不复制录音控制器；键盘失焦不能被误当成长按取消。
- 面板实际高度包含在原输入区测量范围内，不另外给聊天内容添加固定底部占位。

## 接口变化

- 没有服务端 API、数据库或 Agent 契约变化。
- 组件 props 可新增 `variant`／开关回调等展示配置，保留原桌面默认值。实现阶段按职责确定最小接口，不新建全局状态或事件总线。

## 测试计划

文档阶段 S0，只检查 diff、需求一致性与引用。实施预计为 S2：涉及输入区、附件与录音交互，按子系统验证，不默认跑完整仓库检查或调用真实模型。

- 新增手机输入栏 DOM 用例：主操作状态、开合、切换会话、焦点、强度／权限入口及窄屏行为；已有固定输入与模拟媒体设备验证录音，不依赖真实麦克风或密钥。
- 定向用例范围：`mobile-composer.test.tsx`、`composer-attachments.test.tsx`、`voice-recording.test.tsx`、`assistant-context.test.tsx`、`assistant-reasoning.test.tsx`、`assistant-work-reference.test.tsx`。实施时只运行实际受影响部分，发现具体失败再扩大。
- 若修改发送／中断事件接线，补充相应现有请求或交互用例；若只改样式，不为复刻 CSS 另写测试。
- 浏览器验收：320／390／430px 与桌面截图，空白、草稿、多行、面板、附件、录音、运行／停止、错误等状态；模拟视口变化检查重叠与聊天位置。
- 用户日常真机验证 iOS／Android／钉钉的键盘、麦克风权限、长按和系统选择器返回；未执行就标明，不把浏览器仿真称为真机通过。
- 只对改动源码执行项目 Prettier。必要检查通过且无未解决问题后停止。

## 风险

- 简化手机布局时丢失中断或重试入口：按已有任务状态计算主操作，不能只判断文字是否为空。
- 键盘关闭异步导致面板跳动：使用现有可视视口与实际布局，不硬编码键盘高度或依赖固定延时。
- 录音控件重挂载或失焦触发取消：只保留一个实例，单独验证长按与点击流程。
- 面板嵌套浮层离开屏幕／关闭后残留：统一开关边界，引用选择器开启前关闭面板，设置层按实际可视范围定位。
- 全会话执行权限范围不够清楚：设置行显示当前值，范围说明沿用自主执行确认。

## 迁移策略

无数据库迁移、配置迁移或服务重启要求。已有会话与草稿格式保持兼容。

## 预计涉及文件

保留现有目录；新增文件就近归属已有 composer 与 hooks/composer 分组，controls 的具体改动取决于展示复用需要。

```text
apps/web/src/features/assistant/
├── components/composer/
│   ├── MessageComposer.tsx                    [修改] 主栏编排与入口状态
│   ├── MessageComposer.module.css             [修改] 手机紧凑样式
│   ├── ComposerAttachmentMenu.tsx             [新增] 提取现有桌面附件浮层
│   ├── MobileComposerPanel.tsx                [新增] 手机功能面板
│   ├── MobileComposerPanel.module.css         [新增] 面板布局及窄屏适配
│   └── controls/
│       ├── ContextUsage.tsx / .module.css     [按需修改] 面板入口及边界定位
│       ├── ReasoningEffortPicker.tsx / .module.css
│       │                                     [按需修改] 带值设置行
│       ├── ExecutionModePicker.tsx / .module.css
│       │                                     [按需修改] 带值设置行及确认
│       └── VoiceRecordButton.tsx               [修改] 录音启动前收起面板
├── components/conversation/ConversationChat.tsx
│                                             [按需修改] 参数接线／输入区高度协调
└── hooks/composer/useMobileComposerPanel.ts   [新增] 面板与焦点协调
tests/web/dom/assistant/
├── mobile-composer.test.tsx                  [新增] 手机布局及面板交互
└── assistant-reasoning.test.tsx              [修改] 控件唯一性与语义次序
specs/
├── README.md                                [修改] 规格索引
└── spec-067-mobile-composer/
    ├── spec.md                              [新增] 产品行为及验收标准
    ├── plan.md                              [新增] 实施与验证计划
    ├── implementation.md                    [新增] 实施与检查结果
    ├── rework.md                            [新增] 面板入口门禁返工记录
    └── acceptance.md                        [新增] 独立验收结果
```
