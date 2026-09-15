# 技术架构

同仓库维护独立的桌面应用、公司 Web 与后端，根目录提供统一开发命令。实际版本与目录见 [技术栈](../constitution/tech-stack.md)，安装部署见 [README](../README.md)，迁移取舍见 [决策 0015](../.ai/decisions/0015-multi-client-repository.md)。

## 应用与服务

```text
Electron renderer ──受限 preload API──→ Electron main
                                        │ JSON Lines／stdio
                                        ▼
                              内置 Python 本地核心
                              ├─ 麦克风 → WAV
                              ├─ 本地模型 → 转写
                              ├─ 在线模型 → 纪要
                              └─ SQLite／用户数据目录

电脑／手机浏览器 ──HTTPS──→ Caddy ──/api──→ 公司 API
                            │               │
                            └─ Web 静态文件  ▼
                                      PostgreSQL ←→ worker／harness
                                      私有附件卷      │
                                                      ▼
                                               外部模型／ASR API
```

Electron 保留本地会议能力；公司 Web 与后端处理账号、员工消息、文件、工作、报告及授权团队问答。两者独立运行与发布，当前没有自动同步会议、模型或密钥。未来移动 App 使用公司 API；本轮仓库整理不代表移动端已实现。

## 桌面边界

- `apps/desktop/src/main` 管理窗口、权限、核心进程、加密服务配置及受限音频协议；`preload` 只公开类型化业务接口，renderer 不具备 Node、任意 IPC、文件或网络代理权限。
- `apps/desktop/core/src/paa_core` 负责录音、SQLite、模型下载、受管 ASR worker 和纪要任务。录音回调、有界队列、WAV 写盘、推理与网络请求分离，ASR／LLM 延迟不阻塞采集。
- 播放通过授权的 `paa-audio` Range 读取，引用跳转复用同一播放器。原始录音、模型、SQLite 及系统加密配置保存在原 userData；正式包从资源目录启动随包 Python 核心，无需系统解释器。
- 转写任务锁定模型／语言，候选完成后原子发布；纪要固定输入与配置，失败保留旧结果，不自动重复付费请求。完整行为与恢复边界见 [Spec 013](../specs/spec-013-local-model-library/spec.md) 和 [Spec 004](../specs/spec-004-meeting-minutes/spec.md)。

## 公司业务与 Harness

- `apps/web` 是独立的浏览器应用，通过同源 API 使用公司业务；`services/company/src/paa_server` 同时提供 API 和 worker，二者共用业务服务与数据库，没有按进程拆成多个微服务。
- API 负责会话身份、公司／成员授权、输入校验和业务事务。worker 执行可恢复任务，harness 管理授权上下文、工具、预算、checkpoint 和人工确认；模型不能凭参数更改真实身份或绕过业务权限。
- PostgreSQL 保存业务、修订、任务及文件分段，原件在私有附件卷。文档解析通过受管子进程进行；图片／短语音调用外部服务，本机模型不被迁到公司服务器。
- 员工确认工作与提交报告，管理员查看授权业务并创建自己的督办。团队来源依赖贯穿模型输入、历史回答、恢复与确认，撤权／删除后重新校验；具体范围见 [Spec 014](../specs/spec-014-admin-business-assistant/spec.md)。
- 工作检索在服务端授权后分页，看板与明细共用期间和人员范围。worker 将受控聊天反馈写入 PostgreSQL 有界快照，API 经权限复核后通过 SSE 交付；正式结果仍来自业务记录。管理员用量按模型请求记录真实返回值，缺失数据保留未知，见 [Spec 016](../specs/spec-016-web-search-metrics-and-feedback/spec.md)。
- 公司 Key 在服务端加密保存，API 与 worker 使用同一独立私有主密钥；数据库、附件和主密钥分开备份、配对恢复。部署挂载、迁移与备份命令以 README 为准。

## 共享代码与工程边界

`packages/api-contracts` 仅提供公司 HTTP 的 TypeScript 类型；`model-config` 提供已被两端使用的纯校验；`ui-web` 提供浏览器 CSS。共享包不导入应用或服务端，桌面协议留在桌面。CSS 不是原生 Android／iOS UI，移动框架及原生适配尚待立项。

JS 应用由 npm workspaces 管理，各自声明依赖与构建配置；Python 核心与后端保留不同锁文件和虚拟环境。测试仍集中在 `tests`，按对象分区；CI 分层唯一说明在 [README](../README.md#ci-分层)，具体通过与未验范围在 [各 Spec 验收](../specs/README.md)。

此前混入本页的旧 schema、协议清单和逐轮状态已归回各 Spec；整理前原文保留在 [6e83d28 快照](https://github.com/shi-YangYang/work-assistant-agent/blob/6e83d289a16a0783705ae17c879d39d1e059e839/docs/architecture.md)，不把旧 CI 结果当成当前代码的验证。
