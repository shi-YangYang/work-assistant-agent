# Implementation — 公司级模型服务管理

2026-09-12 · 业务实施及定向返工完成，新的独立 Agent [工程复验通过](acceptance.md)；本文记录实现与检查证据。

## 实现

- 管理员 Web 新增“服务配置／用途分配”两页签，多服务、目录搜索／手填、按模型推理预设、默认聊天流式、版本冲突恢复与三类用途分配。沿用现有 Web／Electron 的面包屑、内容面与控件；窄屏服务列表和编辑器分层，长模型 ID 可换行。
- 密钥只写，非敏感草稿跨页面保留，Key 仅在管理页内存；React Router data router 支持离开时保存／丢弃提示，退出／失效后组件释放敏感状态。换地址不沿用已存 Key。
- 公司 schema `0002_model_services` 增加服务、不可变修订、用途、检测摘要及任务配置绑定。AES-GCM 将公司、服务及修订加入认证数据；主密钥丢失、权限错误、被替换或密文不可解时失败，不另造密钥谱系。服务撤销删除其凭证可用性，保留业务历史。
- 受控 HTTP 实际连接前解析并检查全部 DNS 地址，然后固定数值 IP，TLS 仍校验原域名。默认公共 HTTPS、不跟随重定向、不读取环境代理；部署方可放行精确私有源站。目录有同源百炼适配与分页／大小限制；压缩响应被拒绝，避免绕过字节上限。
- 聊天经 ChatOpenAI 子类的消息／工具转换与同一预算入口调用，完整汇总流式文字／工具后再执行；非流式、断流及用量约束保持一致。文件转写与 Qwen-ASR 独立适配。自定义参数不能覆盖消息、工具、凭证、传输及资源限制。
- 首次处理绑定用途和配置修订，普通重试保留原绑定；“使用当前配置重新处理”增加独立尝试维度，同时保留输入修订和摘要隔离。报告新尝试保留旧草稿并生成候选，不能自动发布或覆盖人工确认。
- 主动检测固定文字、红色图片、无业务写权限的 `probe_echo` 工具往返及合成中文音频；检测结果仅保存摘要和经过筛选的数值用量，不回显原始服务错误。公司并发检测使用现有请求事务的 PostgreSQL advisory lock，避免小连接池死锁。

## 验证

本轮为 S3，仅检查公司服务端／Web 与部署支持，未运行桌面录音、全项目套件、发行包或 CI。

- 新增 `tests/server/test_model_services.py` 的 **15 项**定向用例分别通过：权限／CSRF／跨公司、AES-GCM 与备份配对、密钥文件缺失／替换、换址、版本冲突、删除／撤销、用途绑定、环境显式导入与无回退、DNS 固定／压缩拒绝、协议／流式工具和断流、真实 BoundedChatModel／DeepAgents 的预算路径、检测与公司并发限制、配置重试及报告候选恢复。命令为 `node scripts/company.mjs test tests/server/test_model_services.py::<对应测试> --tb=short`，按开发增量执行，并非最后重复全文件。
- `tests/server/test_boundaries.py`、`test_recovery.py`、`test_transcript_recovery.py` 相关 **16 项**通过，外部响应受控，PostgreSQL checkpoint 和业务工具真实执行。连续运行暴露既有 ASGI fixture 未结束 lifespan 导致连接池未释放，已关闭生命周期；仅重跑失败／未完成的 8 项。
- 管理检测并发用例发现独立锁连接与小池叠加造成等待，改为复用请求事务后，该用例与正常检测两项通过。最初 DELETE 测试误用 httpx 不支持的快捷方法 JSON 参数，改为 `request('DELETE', …)` 后通过；没有降低断言。
- `npm run test:web -- tests/web/model-service-drafts.test.ts`：2 项通过。`npm run typecheck:web` 通过；本轮源码 Prettier 整理完成、相关 ESLint 无错误或警告。新 data router 入口的 `npm run build:web` 通过。
- 新迁移已在独立测试库执行成功；协调 Agent 对开发库先备份后迁移并检查原有实体数量，证据为忽略的 `artifacts/spec009/development-migration.json`。`docker compose --env-file .env.company.example -f deploy/company/compose.yml config --quiet`、备份脚本／辅助脚本语法检查通过；这不是部署或恢复演练。
- 协调 Agent 在正常 Web、固定本机网关上已验证目录、流式文字／红图／工具、文件 ASR、保存清空 Key、换址拒绝、密钥离开保护、用途绑定及 360px 长 ID 修复；浅色／深色、1280px／360px、普通草稿保留、用途解除及删除清理也已检查；原主题与环境配置来源恢复，固定网关和临时放行已关闭，正常 API／worker 已重启加载最终代码。证据在忽略的 `artifacts/spec009/web-verification.json`。此类网关证据不等于真实供应商验证。

## 文件与部署

核心新增：`model_schemas.py`、`model_secrets.py`、`model_provider.py`、`model_services.py`、迁移及固定音频资源；修改现有 API／worker／harness 与模型存储，新增 Web 管理页、草稿边界和测试。运行／主密钥挂载及独立备份说明统一维护在 [README](../../README.md#公司工作助手-webspec-008)，未新增云服务或依赖框架。`cryptography` 原已锁定，本次将直接使用关系补入服务依赖输入文件；Docker Web 复制共享纯参数校验依赖。

## 独立验收后的定向返工

首次验收发现管理员检测中途删除已保存服务后，后续检测仍复用旧密钥。本轮在每次文字／图片／工具及语音出站前，通过现有请求事务读取同公司服务与绑定修订的凭证，并核对未撤销和解密可用；不使用 ORM 缓存，不新增连接或持锁阻止删除。编辑服务时检测继续使用原修订与本次草稿，删除后当前项失败、剩余项未测试，新服务草稿仍正常。

`node scripts/company.mjs test tests/server/test_model_services.py -k 'probe_stops_unissued_calls or probe_keeps_original_revision or asr_probe_checks_revocation or admin_probe_and_directory or company_probe_concurrency' --tb=short`：**8 项通过，2.80 秒**。覆盖文字后／图片后／工具首次返回后撤销、草稿新 Key 的已存服务引用、并发保存不切地址／Key／模型、两种 ASR 出站前撤销，以及既有正常草稿检测和公司并发限制。仅使用独立测试库及固定 HTTP 响应；未重跑其它已通过检查，未启动服务、迁移开发库或运行 CI。仅修改 `model_services.py`、对应服务测试与本增量说明，新的独立 Agent 已复验通过，协调 Agent 已重启日常 API／worker 加载修复。

## 用户直接修复与真实联调（2026-09-12）

按用户要求由主 Agent 直接完成，不新建 Spec、不派子 Agent。Web 与 Electron 共用 `src/ui/select.css`；Web 菜单按内容扩宽、保持触发位置与主题，输入框聚焦轮廓取消 3px 间距。删除消息／进展／报告／设置中重复解释权限和内部流程的提示。正常 Web 已检查菜单展开、长名称、深浅色与聚焦边缘，恢复原浅色主题。

用户明确授权使用 Electron 中基元律动现有配置，仅作真实文字与报告联调。通过 Electron safeStorage 在内存解密，临时写入公司服务的加密存储；测试材料为新编写的“真实联调—海星方案”。凭证未输出、未写入源码或日志，未读取真实会议或录音，也没有调用图片／语音接口。

实际调用发现并修复了固定响应未覆盖的问题：工具状态增加明确枚举；新工作支持省略关联 ID，以及兼容供应商返回的空字符串／字符串 null；不存在或越权的模型引用返回可纠正的工具结果，不放宽公司和员工范围。补充上报时，工作名空格与破折号差异造成检索遗漏，已改为按关键词匹配；读取原消息同时返回进展当前确认状态，防止旧助手回复误导模型。回复约束改为业务内容，减少工具名与内部 ID。

定向检查：`tests/server/test_recovery.py -k model_recovers_invalid_references` 最终 **2 项通过，1.68 秒**，覆盖同事／跨公司引用、模型纠正、可选空引用与状态枚举；`-k work_search_and_message_context` **1 项通过，1.14 秒**，覆盖分隔符差异、权限过滤和确认状态更新。未重复其它已通过检查。源码按项目配置格式化；本次未运行 CI、整套测试或发行包检查。

真实服务过程与最终结果在忽略的 `artifacts/spec009/real-integration*.json` 中；首次进展建议保留了报价阻碍，但状态由人工确认时从“进行中”纠正为“有阻碍”。前几次失败的原始记录保留，不将模型输出质量等同于工程检查通过。

确认后立即读取还暴露了事务晚于响应提交的问题。数据库依赖改为 `scope='function'`，完成提交后才返回成功，依据 [FastAPI 依赖作用域](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope)。`tests/server/test_boundaries.py -k progress_confirmation_commits` **2 项通过，1.41 秒**：在响应头发送时读取独立事务，验证成功已提交，以及提交失败返回 503 且无写入。此项涉及共享持久化入口，按 S3 定向验证，未扩展到全项目检查。本次最终共 5 项定向回归通过。

最终真实链路 **PASS**：文字上报、人工确认／纠正、补充自动关联同一工作、确认保留两版历史、周报引用第 2 版与原始上报。周报准确区分初稿完成、报价收到、成本测算进行中和整体方案未完成，保持未发布草稿。使用 `https://tokenrhythm.studio/v1` 的 `glm-5.3-flash`，流式开启；含定位失败在内，真实请求累计文字 23 次、报告 4 次，费用未知。临时服务凭证已撤销，原环境配置来源已恢复，Electron 原配置保持；测试资料保留在日常开发库。

## 未验证与限制

- 本次真实文字与报告联调范围见上节；中文图片／ASR、实际员工长期业务材料与正式报告质量仍需后续验证，不能从单一样本推断。
- 语音探测是无用户资料的离线合成短句，仅核对实际转写主要内容，不是人声准确率基准。来源与校验值在资源目录 README。
- 未执行完整 Linux 镜像部署、生产数据恢复、服务器容量测试或手机实体录音。主密钥和数据库必须分别备份并配对恢复；没有增加自动路由、失败换模型或默认重型 CI。
- 用户已验收当前交付并要求提交、推送 dev；提交号及远端状态以 Git 记录为准，合并由用户执行。
