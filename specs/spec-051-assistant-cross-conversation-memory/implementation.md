# Implementation Report

## Summary

已实现本人账号的跨会话 Markdown 记忆、设置页开关与编辑、Agent 保存／忘记、实时有界注入和失效恢复保护。迁移仅新增记忆表，旧账号默认开启且为空；不回扫历史，不增加独立提取调用、向量服务或轮询。

## Files Changed

- `modules/memories/`、迁移 `0026_assistant_memory.py`、ORM／路由注册：当前身份 CRUD、JSONB 唯一正文、片段注解、版本、失效代次、来源绑定和幂等回执。
- `agent/memory/`、`agent/tools/memory.py`、工具注册／标签／白名单、人设和 harness：当前模型选择记忆操作，临时请求背景与旧回执过滤。
- `agent/context/compaction.py`：记忆计入输入预算，压缩材料排除注入及专用工具载荷。
- `tasks/context.py`、`tasks/processing/handlers.py`、`modules/members/commands.py`：类型化输入快照、缓存答复／最终交付时失效核验和删账号清理。处理器补齐旧 `pendingReply` 恢复路径，已同步 Plan 目录。
- Web 设置 memory API／组件／CSS Modules、路由、导航、共享类型：独立保存的开关、安全预览、草稿、显式冲突合并、清空确认与账号隔离。
- 新增 4 个服务端记忆测试文件、Web DOM 测试及导航断言；新增冻结 12 组真实模型入口 `scripts/benchmarks/memory-evaluation.py`。
- `docs/architecture.md`、`docs/setup.md`：实现边界及用户管理方式。

## Important Decisions

- 任务第一次读取记忆时将输入消息、修订号、原文摘要、文档版本和失效代次保存到 Job；恢复不能重读新代次取得旧输入的写入资格。人工变更发生前就排队的旧输入也被时间屏障拒绝。
- Agent 精确局部补丁保留无关文本。服务端保护人工片段，模型仍可追加无关新事实；不以全局禁止自动追加代替语义冲突判断。
- 注入仅用于当前请求，完整语义块按人工／明确来源、最近更新时间优先。明确期限过滤不重写正文，有期限的替换须覆盖完整段落／列表。
- 开关关闭时忘记工具只在服务端定位用户明确指出的唯一句／分句，不返回其它正文；不以删除整个段落误删无关事实。
- 成功回执只保存版本、操作和长度；恢复／最终交付核对当前版本，删除或人工变更后的旧“已保存”结果失效。

## Tests

按 S3 的相关子系统检查，未运行桌面、ASR、打包或全仓测试。

- 服务端记忆 CRUD／并发／来源／生命周期、文档补丁、上下文压缩、成员删除、执行权限、请求覆盖、架构：**78 passed**。日志 `/tmp/memory-server-tests.log`。
- 服务端记忆运行时和迁移：**5 passed**。日志 `/tmp/memory-runtime-tests.log`。
- 最新局部补丁／关闭删除定位的纯文档测试：**4 passed**。
- Web 记忆 DOM、导航、架构：**10 passed**；增加双角色入口断言后，仅重跑导航：**4 passed**。
- `npm run typecheck:web`：通过。
- 改动 TS／TSX 的定向 ESLint、改动覆盖文件 Prettier、`git diff --check`：通过。
- 真实评测脚本 `--help` 加载检查通过；主 Agent 正在独立运行真实模型 12 组及浏览器验证，结果由验收报告记录。本报告不将正在运行项计为通过。

可复现服务端命令为设置指向 `paa_company_test` 的 `DATABASE_TEST_URL` 后运行：

```sh
npm run test:server -- tests/server/test_memory_document.py tests/server/test_assistant_memory.py tests/server/test_assistant_memory_runtime.py tests/server/test_assistant_memory_migration.py tests/server/test_context_compaction.py tests/server/test_member_deletion.py tests/server/test_execution_permissions.py tests/server/test_request_contract_coverage.py tests/server/test_architecture.py
```

执行时必须避免与使用 public schema 的真实模型评测并发。第一次回归丢失了终端输出句柄，因此结果不明确而重跑到日志；没有因“保险”重复已通过检查。

## Known Limitations

- 是否属于长期自述、敏感内容、语义重复或明确纠正，仍由本轮模型判断；服务端来源和结构校验不能证明全部语义，凭证模式拦截只是补充防护。固定测试与真实模型语义验证分开记录。
- 最新服务端两处小保护（关闭删除定位和拒绝用空保存变相删除）已通过纯文档测试；为避免与真实评测争库，未在此后重复服务端数据库测试。独立验收可在评测结束后定向检查记忆模块。
- 真实评测 M03 初始断言要求旧职责词完全消失，对“运营（不再做产品设计）”产生误报。保留原始结果，需改用版本／局部补丁结构断言及独立语义审查，不通过重跑消除误报。

## Remaining Questions

无产品决策问题。待新的独立验收 Agent 完成验收，以及主 Agent 汇总真实模型与浏览器证据；尚未 commit／push。

## 返工实施

保留首轮独立验收 FAIL 及真实模型原始结果，以下为针对已确认问题的修复。

- `document.annotations_after` 不再将整个 Markdown 段落选成一条注解。原样保存保留全部注解；完整未变或移动的注解逐段保留来源和期限；修改命中的原注解整体标为人工，避免到期后只剩被改动的单个字。同段内其他独立注解不受影响。
- `forget_fragment` 对开启和关闭状态统一使用完整句／分句的唯一匹配，只附带删除相邻标点、列表标记及已空段落的间隔。`Alpha`、多事实句中的 `A` 等不完整目标返回澄清，不扩张到未经明确请求的文字。工具描述指导从本轮请求提取完整事实，关闭状态也可自然完成明确忘记。
- M04 单次诊断保留在 `artifacts/spec051/memory-m04-diagnostic.jsonl`。该次 `finish_task.answer` 含完整对比表，最终回复逐字一致；没有发现答案抽取丢失。首轮仅交付总结的失败未保存原始 checkpoint，因此不能确证当时模型是否把正文放在同次消息 content。仅在收尾提示和工具描述中明确 answer 是唯一最终正文，解释、表格和代码必须完整放入；未增加额外模型审核、强制表格正则或新重试体系。
- 评测升级为 `memory-051-v2`，每轮在 fixture 清理前保留该任务的模型 content、toolCalls 和工具结果。M03 改为版本增长、标题保留和旧完整句被替换的结构断言，语义另行审查，不重跑抹掉初始误报。M06／M08 断言精确剩余正文；M12 保存实际进展正文、下载文件、SHA-256、CSV 表头和数据，并核对实际内容。

定向验证：`test_memory_document.py`、`test_assistant_memory.py`、`test_assistant_memory_runtime.py` 合计 **29 passed**，日志 `/tmp/memory-rework-tests.log`。覆盖无改动保存、跨段／段内移动的独立期限、单字编辑后完整事实、开启／关闭时拒绝不完整目标、英文句号、多事实句、列表和删除后的标点／空段清理。评测入口 `--help` 和 `git diff --check` 通过；本次只改 Python，项目未为 Python 配置格式化器。

业务和评测代码已交回主 Agent 冻结，主 Agent 对 M04／M06／M08／M12 运行一次有修改依据的真实检查，并安排新的独立验收。其结果尚不计入以上通过项；未重复 UI、迁移、全仓测试或构建，未 commit／push。
