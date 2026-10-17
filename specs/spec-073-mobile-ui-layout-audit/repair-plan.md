# 手机端审计问题修复

## 范围与目标

修复 [问题清单](issues.md) 的 MUI-001～008。审计原始报告和证据保留，不把发现记录改写为已经通过。每项交付一张修改前和一张修改后的实际浏览器截图，采用相同视口、主题和合成数据；不使用设计图代替结果截图。

## 修改约束

- 收紧公共手机页头、返回栏和团队工具栏，保留可用的导航与长标题空间。宠物继续全站悬浮，不根据宠物显隐给报告页增加特殊留白。
- 长文件名只在自身区域换行或省略，不能挤掉大小及操作。
- 附件删除、草稿播放及强度标签的实际触摸区域至少 44px，保持图标紧凑，避免命中区重叠。
- 大字下“＋”面板入口允许换行／调整列数，普通字号布局保持简洁。
- 宠物隐藏时，侧栏顶部提供通知图标和未读数；手机导航按钮附未读提示，用户打开导航即可进入通知。宠物显示时沿用宠物入口；复用现有通知状态，不新增轮询。
- 材料范围正常完整项合并为简洁摘要；部分、失败、未读文字／图片、原文件未提取范围与代码执行来源差异仍明确提示。根据现有读取记录本地整理，不增加模型调用、文件读取、提示词或校验步骤，不把“已准备”误称“模型已读”。
- 清空记忆及删除声纹复用公共 React 确认框，保留取消、提交中禁用、防重复、失败恢复与原有接口。

## 实施与验证

本次涉及共享布局、局部状态与服务端展示摘要，按 S2 做相关子系统的定向验证。先冻结并截图旧状态，再改动；保留既有未提交审计文档和脚本。UI 与服务端摘要文件边界明确，可分别实施；截图脚本由独立执行者维护，最后由新的验收 Agent 检查。

- 视觉：每项至少一组同条件前后图；手机 320／390、长文件名、大字、深色及桌面只对受影响边界定向检查，不重跑全量审计。
- 逻辑：通知显隐／未读及导航，确认框取消／成功／失败，材料完整／部分／失败／未提供与重复追加的定向测试。各实施者完成必要检查后不无理由重复。
- 截图不可包含真实账号或密钥；浏览器原生确认框若不能被页面截图捕获，需明确截图边界并保留原生事件证据，不能伪造原生窗口。
- 不改生产配置、默认 CI、模型请求或业务数据权限。测试结束清理本次自有资源，保留截图。

## 文件边界

```text
apps/web/src/
├── components/layout/page-header/PageHeader.module.css          [修改] 手机公共页头
├── components/navigation/DetailBackLink.module.css              [修改] 返回区
├── app/layout/{Sidebar,pet/PetStage}.*                          [修改] 隐藏宠物后的通知入口
├── features/team/…                                            [修改] 窄屏筛选排列
├── features/work/components/materials/WorkMaterials.*          [修改] 长文件名
├── features/assistant/components/composer/
│   ├── MobileComposerPanel.module.css                         [修改] 大字标签
│   └── attachments/Composer{Attachments,AudioPreview}.*         [修改] 触摸范围
├── features/model-services/components/catalog/ReasoningSettings.* [修改] 标签触摸范围
├── features/settings/components/memory/MemoryEditor.tsx        [修改] 公共确认框
└── features/voiceprints/components/VoiceprintsPage.tsx          [修改] 公共确认框
apps/server/app/modules/attachments/documents.py                [修改] 材料范围展示摘要
tests/web/… / tests/server/modules/work/test_material_coverage.py [必要时修改] 定向回归
scripts/company/web-acceptance/mobile-ui-audit/                 [新增/修改] 定向前后截图
specs/spec-073-mobile-ui-layout-audit/
├── repair-plan.md                                             [新增] 本修复范围
├── repair-report.md                                           [新增] 修改、检查及前后图索引
├── repair-acceptance.md                                       [新增] 首轮验收及返工依据
└── repair-acceptance-final.md                                 [新增] 返工后的独立验收
artifacts/spec073-fixes/<run-id>/                               [生成，不入Git] 前后原图与检查证据
```

不新增目录层级或迁移产品代码；文件名按实际涉及范围在修复报告列明。
