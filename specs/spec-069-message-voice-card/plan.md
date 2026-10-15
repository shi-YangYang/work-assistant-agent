# Plan：已发送语音卡片

## 对应 Spec

[已发送语音卡片](spec.md)。按自定义播放条与消息级文字区方案实施。

## 涉及模块

- `components/media/AudioPlayer`：无业务依赖的自定义播放器，接收来源、标题及可选时长，处理播放状态、定位与生命周期。
- `assistant/components/messages/MessageVoice`：按消息组合音频列表、文字折叠区和修正弹窗，管理本卡片的展开与编辑状态。
- `MessageTranscript`、`TranscriptEditor`：复用现有转写展示及版本校验保存流程，调整内嵌样式，不复制请求逻辑。
- `MessageCard`：将原音频与独立转写区域替换为 `MessageVoice`，图片、文档及助手回复继续按原路径渲染。

## 修改顺序

1. 实现可独立使用的播放器：媒体事件、时长、进度、错误、键盘及跨实例播放协调；资源在卸载时释放。
2. 组合消息级语音卡，移入展开和编辑入口，保留已有修正组件及请求契约。
3. 接入 `MessageCard`，去掉旧音频 controls 和独立转写区域；样式仅影响本次已发送语音。
4. 完成定向用例和桌面／窄屏浏览器检查；由新的独立验收 Agent 核对 Spec，只针对明确问题返工。

## 数据流

```text
WorkMessage.attachments / transcript / transcriptRevision
  → MessageCard
    → MessageVoice
      ├─ AudioPlayer × 音频数量 → HTMLAudioElement
      ├─ MessageTranscript → 本卡片内展开
      └─ TranscriptEditor → 现有 correctTranscript → onChange 刷新
```

- 音频通过 `previewUrl ?? url` 播放，附件时长作为初始显示值；只接受有限、非负的实际媒体时长。
- 播放互斥使用有明确释放边界的轻量实例协调，不添加全站轮询、业务状态仓库或扫描所有 DOM 音频的逻辑。
- 消息刷新使用稳定键，播放器局部更新时间；展开文字、任务进度变化不应重建音频节点。
- 每个附件对应独立播放行；单段的 `MessageTranscriptControls` 与播放器同排，多段时移至共用卡片底部。`MessageTranscript` 正文在文字操作行下方展开，保持消息级转写语义。
- 现有待发送录音组件不接入本次替换，避免扩大到采集和发送路径。

## 接口变化

新增前端组件 props；无公共 API、契约、数据库、部署或模型配置变化。修正文字继续提交 `text` 和 `expectedRevision`。

## 测试计划

文档阶段按 S0，仅检查需求、diff 和引用。实施预计 S2，范围限于媒体播放及消息转写组合，不调用真实模型或使用真实麦克风。

- 新增播放器 DOM 用例：播放／暂停、缓冲、结束重播、定位、未知时长、播放拒绝与错误、互斥及卸载清理。模拟媒体事件验证状态，不能用该结果替代真实文件播放。
- 新增消息组合用例：一条／多条语音共用文字区、无音频但有转写、混合附件、转写更新期间播放稳定、本人／他人入口、弹窗修正成功及失败。
- 沿用已有表单验证用例核对修正清空、版本冲突和错误保留。若未修改录音／发送模块，不重复跑语音发送全套。
- 计划定向命令：

  ```sh
  npx vitest run --config apps/web/vitest.config.ts tests/web/dom/assistant/message-voice.test.tsx tests/web/forms/business-form-validation.test.ts
  ```

- 浏览器使用固定短音频样本，验证实际播放、拖动、结束、切换消息／会话及故障提示；检查 320／390px 与桌面，浅／深色，折叠／展开、多段及长文字。
- 查看网络行为，确认列表展示未因装饰性波形批量读取音频，没有新增转写或模型调用；不为纯前端播放器改造做真实模型速度基准。
- 项目 Prettier 仅整理改动源码；不默认全仓库测试、build、lint 或 typecheck。必要检查通过后停止。
- 真实钉钉、iOS／Android 未执行就注明，不能将桌面视口仿真写成真机验证通过。

## 风险

- 消息级转写被重复分配给每段音频：在卡片中只组合一次转写和编辑入口。
- 原生 controls 移除后丢失基础交互：显式验证暂停、进度、重播、键盘和失败状态；扩展倍速／音量菜单不纳入本次。
- 录音时长暂不可用、不同浏览器媒体事件顺序不同：时长未确定时给稳定占位，播放态以实际事件为准，处理 `play()` 拒绝与快速切换。
- 后台刷新重建播放器：稳定附件键和音频节点，源地址变化才重置。
- 公共附件样式误伤其他页面：替换前核对引用，只移除本组件不再使用的规则；不改全局 `audio` 样式。

## 迁移策略

不需要迁移、数据回填、重启 API 或 worker。历史消息沿用原数据；回滚前端改动即可恢复原播放器。

## 预计涉及文件

新增文件归入已有 media／messages 目录，不移动既有目录，不为单个组件新增业务分组。

```text
apps/web/src/
├── components/media/
│   ├── AudioPlayer.tsx                    [新增] 公共播放器及实例协调
│   └── AudioPlayer.module.css             [新增] 播放条与交互状态
└── features/assistant/
    ├── components/messages/
    │   ├── MessageVoice.tsx               [新增] 消息语音、文字和编辑组合
    │   ├── MessageVoice.module.css        [新增] 卡片及窄屏布局
    │   ├── MessageCard.tsx                [修改] 接入语音卡，移除分散入口
    │   ├── MessageCard.module.css         [修改] 卡片对齐及宽度约束
    │   └── transcript/
    │       ├── MessageTranscript.tsx     [修改] 拆出同行操作与展开正文
    │       └── MessageTranscript.module.css
    │                                     [修改] 同行按钮及内嵌正文样式
    └── styles/attachments.module.css      [修改] 清理失效的音频专用规则
tests/web/dom/assistant/
└── message-voice.test.tsx                 [新增] 播放器与消息组合回归
specs/
├── README.md                             [修改] 规格索引
└── spec-069-message-voice-card/
    ├── spec.md                           [新增] 产品行为与验收要求
    ├── plan.md                           [新增] 实施范围与验证计划
    └── acceptance.md                     [新增] 独立验收与浏览器结果
```

`TranscriptEditor.tsx` 与修正 API 原样复用。
