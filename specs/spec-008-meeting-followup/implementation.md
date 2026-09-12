# Implementation — Spec 008

2026-09-12 · 业务实施及两轮返工完成，独立工程 [PASS](acceptance.md)。本文记录实现差异与检查；行为见 [Spec](spec.md)，接口、限额及恢复契约见 [Plan](plan.md)。

## 已实现

- 独立 React Web：登录／首次改密、工作助手、进展确认／更正、来源、日报／周报／候选结果、老板看板、成员与汇报规则；响应式、主题、导航、草稿与冲突恢复。
- FastAPI／PostgreSQL：服务端身份与材料权限、版本／事务幂等、原始附件、图片规范化、短语音转换和转写修正；新增接口可查 `/openapi.json`，不含凭证。
- 实际 Deep Agents／LangGraph 工具循环、PostgreSQL checkpoint、StateBackend、预算、租约与 fencing；禁用通用工具／子 Agent，正式确认和发布由员工 API 执行。
- 按公司时区和规则准备报告草稿，固定已确认输入修订；晚到结果进入候选，不覆盖人工编辑或已提交版本。
- 独立公司依赖／启动／Compose／Caddy／备份支持；桌面启动与数据保持，仅共用语义主题。新增单个 Linux／PostgreSQL 模块 CI，不添加真实模型或桌面重检查。

具体版本与路径见 [技术栈](../../constitution/tech-stack.md)，安装和运行只在 [README](../../README.md#公司工作助手-webspec-008) 维护。

## 实现与验证

按 S3（认证、API、持久化及构建入口）和 S2（Web）选择范围，未重跑 Electron／ASR／安装包套件。

| 检查 | 结果与边界 |
| --- | --- |
| 独立 Python 3.12 依赖、`pip check` | 通过；固定版本在服务端锁文件，不混入桌面环境 |
| PostgreSQL／checkpoint 迁移 | 开发库及独立 `paa_company_test` 成功，初始迁移冻结 |
| 初轮 server | 9 个 API／harness／媒体／事务场景＋2 个长上下文／旧修订场景通过；真实 PostgreSQL／Deep Agents，外部模型受控 |
| 初轮 Web | 3 项 CSRF／幂等／冲突／日期用例通过；Web／新 Node 配置类型、变更文件 lint 和格式通过 |
| 普通 Web 构建 | 成功，约 294 kB JS／17 kB CSS；不代表部署 |
| Compose／备份脚本 | 开发和生产 `config -q`、`sh -n` 通过 |
| Docker 服务镜像 | 获取 Python 基础镜像鉴权时 IPv6 超时，后续未构建；未换源或重跑到绿 |

服务端场景覆盖前后关联、草稿不可见／跨员工隔离、确认去重、版本冲突、并发幂等、提交版本与私有更正分离、候选结果、周期、图片和 FFmpeg 真实规范化、受控 ASR、租约过期／旧 worker、额度与上下文压缩。替身仅在 `tests/server/fakes.py`，正式服务无演示开关。

另修复报告 revision 更新后来源未刷新、409 后读取／保留／采用最新版本入口，以及 HMR 重建 Context 丢失 Workspace；后者抽离稳定 Provider，首登改密直接接收成员信息，不用空草稿掩盖故障。对应 Web 类型／lint 通过。

主 Agent 在正常开发环境以明确标注的验收账号完成登录、成员创建／首次改密、草稿跨页、发送、进展编辑确认、日报编辑提交和管理员查看第 3 版及来源；模型为受控响应。900px 菜单／Esc、360px 无整页横溢；Electron `npm run dev` 的原 4 条会议、主题及已下载模型保持，未录音或改 Key。

## 首轮验收返工

首轮 FAIL 的三项问题由新实施 Agent 修复，再由独立 Agent 复核：

| 缺陷 | 修复 |
| --- | --- |
| 不同消息／报告任务共享可执行 checkpoint | 按公司／员工／job 隔离；从授权业务记录重建有界历史、截断未来消息、优先显式回复；同 job 同输入仍可复用 pending 或完成结果 |
| 录音申请与离页竞态 | 控制器按代次拥有媒体流，申请防重入、可取消；迟到轨道停止，失败释放；旧会话不能覆盖新文字或停止新录音 |
| 更正已有工作时 null 被回填 | 区分未缓存与明确 null，普通保存及冲突“保留我的修改”均保留用户选择 |

定向证据：真实 PostgreSQL／Deep Agents 的任务隔离、恢复、历史／长上下文 4 项＋受影响的确认／报告／权限 1 项通过；媒体 5 项、编辑映射 1 项、Web 类型／改动文件 lint 通过，源码已格式化。未重复全套测试或构建。

## 输入版本返工

第二轮 FAIL：语音文字纠正后重试仍恢复旧输入。仅修复 `agent/harness.py`、`worker.py` 的恢复／写入边界：checkpoint 绑定转写 revision 和输入 SHA-256，同输入续跑，纠正后新建执行上下文；ASR、工具及最终回复在锁内选择／校验源 revision，迟到输出失败并可手动重试。原音频、建议、人工修订和报告输入快照保留；不改 API／schema／依赖。

`node scripts/company.mjs test tests/server/test_transcript_recovery.py tests/server/test_recovery.py tests/server/test_boundaries.py::test_long_conversation_is_summarized_before_hard_context_limit`：**11 项通过，4.38 秒**。新增 7 项覆盖模型前失败、旧 pending／completed 状态、同 job 幂等、写入竞态和 ASR 途中纠正；另 4 项覆盖任务隔离／报告恢复／历史。使用独立测试库，未清理开发样本或调用真实模型。

## 用户体验后的直接修复（2026-09-12）

主 Agent 按用户要求完成，未新增 Spec／独立验收：

- 团队列表／统计只包含员工；团队详情及通用资料接口拒绝跨管理员读取，本人资料和账号管理保留。顶部图标统一尺寸，日期起止标签成组。S3 仅跑 2 项相关 API／PostgreSQL 检查及 Web 类型，均通过；浏览器看板为 1/1，556／360px 图标同线、日期同排且无横溢。数据库初次连接被本机沙箱禁止，获执行许可后通过，不是业务断言失败。
- Web 对齐 Electron 的 216px 侧栏、底部设置、54px 面包屑、单标题、canvas／surface 和控件层级。S2 Web 类型／改动文件 Prettier／diff 通过；1280px 浅深色、360px 看板和外观观察通过，恢复原主题。

这些是主 Agent 增量验证，不扩大此前独立 PASS。后续控件／提示文案及真实文字联调归入 [Spec 009 实施摘要](../spec-009-company-model-services/implementation.md#用户直接修复与真实联调2026-09-12)，全站布局维护见 Spec 010。

## 已知外部边界

本 Spec 实施使用受控模型；真实文字与周报的后续证据见上方 Spec 009 引用。真实图片／ASR、iOS／Android 麦克风与锁屏、公网 HTTPS、完整 Linux 镜像、生产备份恢复和 2 核 2 GB 负载仍未验证。没有开通云资源或以窄屏截图代替实体设备。
