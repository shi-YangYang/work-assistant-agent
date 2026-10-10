# Implementation Report

## 交付协议简化

删除在线字数声明、句型推断、计数门槛与自动长度改写；旧长度字段和预览标记仅供读取兼容。普通回答与协议恢复直接交付正文，不重新填写任务、业务和核验表单。恢复期间禁止工具执行和未经验证的正文预览，真实回执、未完成项与权限边界保留。

定向检查和源码范围见[实施记录](../../artifacts/spec055/remove-burdens/implementation.json)，独立检查见[移除负担验收](acceptance-burdens.md)。传输与协议简化已验收，整体性能仍有限制。

## 最终源码真实计时

同一源码、模型服务修订与四条固定输入，分别使用 low 和 max。时间从发送请求开始；首字为 SSE 客户端收到正文，完成为终态读回，不冒充浏览器绘制时间。每档一轮，不足以计算稳定分位数。

| 场景             | low 首字／完成 | max 首字／结束  | 结果                                                                 |
| ---------------- | -------------- | --------------- | -------------------------------------------------------------------- |
| 你是谁           | 5.58s／7.43s   | 4.42s／5.32s    | 两档成功                                                             |
| 1000 字作文      | 17.24s／21.36s | 47.14s／51.72s  | 两档完成，但篇幅偏短；不判质量全通过                                 |
| 创建工作         | 无预览／8.93s  | 无预览／166.63s | low 成功；max 上游响应后超时，后续重试在发送前网络失败               |
| 修改刚创建的工作 | 无预览／27.13s | 无预览／8.99s   | low 成功；max 请求未发出，且前一步未创建对象，不是有效的修改性能样本 |

low 完成一次创建、一次修改；相对日期被规范为具体日期，旧字面比较失败不等于业务修改失败。作文 low 全文 763 个汉字；max 全文 802 个汉字、正文 782 个汉字。在线长度门槛已移除，偏短作为离线质量问题保留。

max 创建的主请求已经收到 HTTP 200，随后以超时结束；现有日志缺少最后有效分片时间，不能区分供应商停止输出、网络故障或主机暂停，也不能把 166.63s 归为正常模型推理。后续七次调用尝试在网络阶段失败，未送达供应商。两轮均未改日常账号配置，测试进程、容器、凭据和数据已清理。

原始证据：[low](../../artifacts/spec055/remove-burdens/real-timing/report.md)、[max](../../artifacts/spec055/remove-burdens/real-timing-max/report.md)。这些本地采样不能证明稳定的全流程降幅。

## 按需工具与预算返工

初始请求仅提供 `load_tools`；同一主模型按需加载 work、reports、research、documents、files、memory、task_context 的完整定义与专项规则。精简通用规则和运行时人设，不增加分类模型、不降低思考强度。工具仍执行原权限、来源、范围、授权、版本和幂等检查。加载状态按任务 scope 持久化，旧 checkpoint 合法调用兼容，不重放成功写入；加载不占业务工具步骤，模型与时间预算保持原值。

实际工具额度拒绝保存具体未执行项，正文、任务状态和回执保持 blocked；仅达到软封口阈值且实际操作全部成功时仍完成。首轮独立验收的失败及复现见 [验收记录](acceptance-shared-flow.md)。

定向结果：预算返工 7 项通过；目录组 26 项通过；相邻组 42 项通过，3 项旧队列状态假设修正后连同 6 项压缩／记忆检查通过。组间有交叉，不相加为独立数量。测试 schema 已清理，真实模型和浏览器结果另行验收。[目录实施明细](../../artifacts/spec055/shared-flow/catalog/implementation-report.md)。

## 内部摘要隔离返工

独立验收发现，压缩复用主模型时被正文校验器误识别为用户答复。`runtime/model.py` 与 `context/compaction.py` 使用调用级 `ContextVar` 隔离整个分块摘要和最终合并；不创建正文发布器、不运行正文交付校验，计时归入 compaction，原用量、预算与时限保留。异常或取消通过 `finally` 恢复，不改变共享模型实例。

定向检查覆盖单块、多块合并、合并异常、实际任务取消、并发 `tools=[]` 正文和既有业务回执。首轮修复曾遗漏多块合并，独立复现失败记录保留；最终合并组 4 项通过，1 项取消替身假设修正后仅复测该项通过。[原发现](acceptance-shared-flow-final.md)、[合并入口遗漏](acceptance-compaction-rework.md)、[最终定向日志](../../artifacts/spec055/shared-flow/compaction-rework/merge-targeted.log)、[取消复测](../../artifacts/spec055/shared-flow/compaction-rework/merge-cancelled.log)。

AFTER2 真实模型对照冻结在上述压缩隔离修复前；样本未发生压缩，不能把其结果宣称为最终源码所有分支的真实模型验收。新增隔离分支使用实际适配器的受控输入验证。

## 共享主流程返工

普通回答和业务共用精简主提示，正常调用使用 `auto`；普通正文直接交付，不再为收尾包装补调模型。正文预览使用极小标记，任务变更改为独立的 `set_task_context`。保留旧 Delivery/checkpoint、实际回执、授权、范围、版本、幂等、来源与取消检查；未完成事项同步到任务状态和回执。原有在线篇幅计数已由上方交付协议简化移除；历史 767 字不足样本不改判通过。

本轮文件范围见 [返工方案](rework.md#实施范围)，与冻结 before 的差异见 [补丁](../../artifacts/spec055/shared-flow/implementation/shared-flow.patch)。未改用户日常模型、强度或业务数据。专项授权流程本轮保持不变。

定向验证：90 项交付/篇幅检查、55 项流式检查、33 项交付契约检查及 26 项边界检查通过；这些组存在交集，不相加为独立用例数。业务/恢复初测 162 通过、14 失败：9 项为隔离环境未配置 Redis，修正测试环境后通过；5 项在冻结 before 同样失败，旧全局审稿假设更新为当前显式任务/交付契约后通过。原失败、基线及修正日志均保留在 `artifacts/spec055/shared-flow/implementation/`。所有自有测试 schema 和 Redis 已清理。

保留质量边界：程序能够检查已识别的缺失项和业务回执，不能保证发现模型完全未声明、未尝试的所有语义遗漏，也不保证精确字数。本次没有增加全局审稿。真实耗时与浏览器结果另行记录，不能用原型替代最终验收。

## 原传输阶段实现

以下记录已完成的传输阶段；交付协议以本页上方返工为准。未推送或部署。

- 原阶段曾使用 `tool_choice=required`，现已由共享流程返工改为 `auto`；既有有界协议修正、授权和变更范围判断保留。
- 新长度 schema 移除 `body`，从最终 `answer` 计数；旧字段、完整覆盖和单行标题规则兼容。
- RunContext 公开网页缓存限制为 8 页、8 MiB、120 秒，合并同时下载，支持刷新，保留请求 URL、最终 URL、抓取时间及命中标志；关闭时释放下载任务。
- 一个受管理的发布任务合并候选正文；来源校验与 Redis IO 脱离模型分片消费。生成中不更新 PostgreSQL 正文，最终提交、授权中断快照和业务回执保持各自持久化边界。
- Redis 原子维护快照、游标和增量，隔离公司／账号／job／attempt／fence／generation，校验 call 与 seq。快照与事件各最多 480 KiB，最多 256 事件，单事件含元数据不超过 64 KiB，TTL 900 秒。硬封口 tombstone 拒绝所有迟到世代；软撤回不能覆盖较新世代。
- SSE v2 发送 sync／delta／withdrawn／unavailable，旧 v1 由服务端组装快照；每次暴露及无新分片的状态检查均重新验证权限和来源。终态优先使用数据库，取消期间旧临时快照不能覆盖持久化结果。
- 前端复用唯一订阅与既有打字效果，独立处理正文游标；恢复快照修复缺口，重复／旧世代／旧执行被丢弃。
- Redis 7.4.2、redis-py 5.2.1 接入开发、Compose、CI 与进程关闭。生产 Redis 私网、64 MiB/noeviction、128 MiB 容器；发布停止入口并排空旧任务后再切换。没有迁移、模型配置或思考强度变更。

## Files Changed

主要新增：`tasks/streaming/{protocol,redis_store,publisher}.py`、`tasks/timing.py`、`integrations/web_page_cache.py`、Web `api/reply-stream.ts`、`scripts/company/reply-stream-local.mjs`，以及对应服务端、Web、部署定向测试。

主要原位修改：Agent middleware/model/completion/web tools、模型 chat 适配器、任务 context/feedback/handlers/router/cancellation/runner、API/worker 生命周期、Web job-feedback、API contracts、依赖与 Compose/release/CI，以及 setup/architecture/tech-stack 文档。

相对计划树的调整：工具计时放在既有 middleware，新增 `actions/work_change_plan.py` 的调用分类和 `modules/messages/commands.py` 的接收计时；无须修改 harness、候选解析器、delivery、node_execution、Message serializer 或 usage 表逻辑。未观察到需要实施连接复用的因果证据，因此未修改 models/transport.py。新增 `tests/deploy/local-reply-stream.test.mjs`；协调 Agent 另负责浏览器与基准脚本文件。

## Tests

验证级别 S3，范围限于本次影响的交付、网页、正文流、持久化、前端订阅和部署。所有数据库写入使用独占 `paa_company_test` schema；真实 Redis 使用隔离实例／命名空间。

| 检查                                                                                                                                                                                                        | 结果与证据                                                                                                                                                                                                                                                                                                         |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `pytest test_reply_publisher_lifecycle.py test_reply_stream_transport.py test_web_page_cache.py test_assistant_timing.py test_answer_length.py test_response_delivery.py test_model_stream_errors.py -q -s` | 101 passed，30.73s；[最终定向日志](../../artifacts/spec055/implementation/final-targeted.log)。含真实 Redis 拒写／重启、独立 writer 与两 reader 进程、严格字节预算、长度兼容、协议修正与模型错误。                                                                                                                 |
| `pytest test_reply_publisher_lifecycle.py test_reply_stream_transport.py test_assistant_reply_stream.py -q`                                                                                                 | 65 passed、1 skipped，22.55s；[流式兼容日志](../../artifacts/spec055/implementation/stream-final.log)。此组故障 Redis 未启用的 skip 已在上组显式启用并通过，不计作未覆盖。                                                                                                                                         |
| 终态清理集中到 finally 后，复测 shutdown／database_retry                                                                                                                                                    | 3 passed；[清理边界](../../artifacts/spec055/implementation/cleanup-boundary.log)。                                                                                                                                                                                                                                |
| `pytest tests/server/test_web_research.py -q`                                                                                                                                                               | 49 passed，2.97s；[网页安全与工具回归](../../artifacts/spec055/implementation/web-research-final.log)。                                                                                                                                                                                                            |
| Web reply-stream、job-connection、dom assistant streaming                                                                                                                                                   | 3 files、38 tests passed；[Web 单测](../../artifacts/spec055/implementation/web-tests.log)。                                                                                                                                                                                                                       |
| Web typecheck、修改文件 ESLint、Prettier                                                                                                                                                                    | 通过；[类型](../../artifacts/spec055/implementation/typecheck.log)、[Lint](../../artifacts/spec055/implementation/lint.log)、[最后启动脚本 Lint](../../artifacts/spec055/implementation/local-lint.log)、[格式](../../artifacts/spec055/implementation/format.log)。最后修改的启动脚本与 CI 再次用 Prettier 整理。 |
| `pytest tests/deploy/test_release.py -q`                                                                                                                                                                    | 13 passed、9 subtests passed；[发布检查](../../artifacts/spec055/implementation/deploy-final.log)。包含真实 Compose 配置解析、入口停止→drain→backup 次序。                                                                                                                                                         |
| `node --test tests/deploy/local-reply-stream.test.mjs`                                                                                                                                                      | 2 passed；[本地 Redis 生命周期](../../artifacts/spec055/implementation/local-redis.log)。覆盖运行中复用、仅停止自己启动的资源、启动失败清理、外部实例不受影响。                                                                                                                                                    |
| Compose dev/prod `config --quiet`、`bash -n release.sh`、`git diff --check`                                                                                                                                 | 通过；未启动生产服务。                                                                                                                                                                                                                                                                                             |

各组有交叉覆盖，不能把上述数量相加宣称独立用例总数。初次默认测试库缺少既有 `company_member.reasoning_revision` 列，改用独占迁移 schema 后通过；未迁移共享测试库。期间修复了旧 fake 的 body/schema 和 web_search domains 假设，以及 SSE 撤回在 yield 前封口的实际竞争问题；保留早期失败日志，不以失败重跑代替根因修复。

## Controlled Timing Evidence

| 受控场景                                             |                               实测 | 解释                                                                                    |
| ---------------------------------------------------- | ---------------------------------: | --------------------------------------------------------------------------------------- |
| 发布端注入 200ms 等待时连续提交 2000 次候选更新      | producer 5.661ms；正文 UPDATE 0 次 | 一个后台任务，最新候选槽有界；模型消费不逐片等待发布。SQL 监听核对生成阶段没有 UPDATE。 |
| 合法候选 `write` → 真实 Redis → 服务端 SSE generator |                           63.242ms | 同进程单调时钟测量，包含来源校验与原子流传输；不冒充浏览器绘制或供应商 TTFT。           |
| 同页三次不同片段及同时读取                           |                          下载 1 次 | 缓存命中保留同一抓取时间；新上下文、过期、刷新重新下载。                                |

前两项原始输出见 [最终定向日志](../../artifacts/spec055/implementation/final-targeted.log)。`paa.latency` 记录 job/attempt/fence/call，区分 main/protocol/length_repair/response_repair/change_scope/authorization/compaction，记录模型发送／有效事件／接收／用量、候选／授权首字、工具、来源、发布、SSE 和最终保存。高频发布／来源事件每类采样前 32 条，单 Timing 最多 512 条；日志不记录正文、凭据或隐藏推理。不同进程的单调计时不直接相减。

## Known Limitations

Redis 是可丢失缓存；worker 硬崩溃或 Redis 重启可能丢未保存尾部，既有消息和副作用回执仍由 PostgreSQL 保证。Redis 不可用时停止本次预览并显示提示，后台仍可完成；无高频正文写库回退。

本报告未宣称七轮模型对照或浏览器完整链路已通过，相关工作由协调 Agent 和 benchmark Agent 另行出具；此处只报告实施者已实际完成的检查。未运行全仓库 Server/Web/Electron、未发布、未触发远端 CI，未做最终独立验收。

## Resources

- 已清理独占 schema `spec055_recovery_7acff22333bd`、对应媒体、密钥及临时凭据；[清理日志](../../artifacts/spec055/implementation/cleanup.log)。
- 已停止并移除 `noria-spec055-redis-fault`（16380）；没有修改共享实例配置或停止日常服务。
- `noria-spec055-redis`（16379）暂留供协调 Agent 的真实浏览器链路验证，完成后由协调 Agent 停止；容器 `--rm`，无持久卷。
- 基线归档 `/tmp/noria-spec055-baseline` 与 benchmark 资源归 benchmark Agent 管理；不在此清理。实施者未启动 API/Web/worker 服务。

## Remaining Questions

无产品或技术决策待确认；等待协调 Agent 汇总其负责的对照／浏览器证据，并安排新的独立验收 Agent。

## Rework

针对独立验收的两项 P1 完成返工，未改变模型流程、配置或基准脚本：

- `feedback/feedback.py` 统一四类撤回的协议编码：空闲来源失效、新快照授权失败、Redis 封口和 generation 交接，v1 均收到空文本／`withdrawn` 的 `snapshot`，v2 保持 `reply_withdrawn`。状态去重在合并临时正文之后执行。
- `processing/handlers.py` 仅在最终／中断事务提交后，或来源／权限／租约撤回时清空临时正文。最终保存与恢复保存都失败时关闭发布任务，通过 `feedback/reply_stream.py` 和 `streaming/redis_store.py` 冻结 Redis 写入；保留已有正文、来源、执行身份、游标及原 TTL，拒绝当前与后续 generation 的迟到写入。恢复读取仍执行现有授权和来源检查，不发布成功终态，不追加模型调用或工具重放。
- `test_reply_publisher_lifecycle.py` 增加新旧协议四类撤回，以及连续保存失败、撤回伴随恢复数据库故障的定向用例。真实 PostgreSQL 独占 schema 与 Redis 独立 namespace 验证；模型使用固定替身，数据库故障通过保存边界注入 `OperationalError`，没有访问真实模型服务。

S3 返工仅运行直接受影响的检查：`pytest tests/server/test_reply_publisher_lifecycle.py -q -k 'all_withdrawals or final_and_interruption or source_revocation_still or shutdown or database_retry'`，结果 **13 passed、4 deselected，11.67s**，见[定向日志](../../artifacts/spec055/rework/targeted.log)。包括最终保存原有两次有界尝试、恢复保存失败、模型恰好一次、数据库没有成功回复、缓冲可恢复及后续来源失效拒绝。未重复其他已通过测试组；Python 文件不在项目 Prettier 覆盖范围。

已清理本次独占 schema `spec055_recovery_8a12c02ae72e` 及其临时凭据／媒体、Redis namespace `spec055:rework:ef1d`，保留其他任务的 Redis 服务与数据。未提交或推送，等待新的独立 Agent 验收。

## 最终补充

协调 Agent 已完成浏览器和真实模型对照汇总，新的独立验收结果为 [PASS](acceptance.md)。

- 真实 publisher → Redis → HTTP → 浏览器首绘 194.452ms；受控前端事件 → 首绘 61.7ms，终态事件 → 最终读取与绘制 30.4ms，首次出现即全文完整。刷新、离开返回、断网单次恢复、取消刷新和零 POST 重发检查通过。浏览器用例及隔离环境白名单已格式化，修改文件 ESLint 通过。
- 七组真实对照和分段原始证据见验收报告。两项基线超时、一次评测环境故障及最终故障边界代码差异均保留；不能根据混合失败的合计耗时宣称稳定整体提速。
- 所有本次独占 API、Web、worker、沙盒、Redis、PostgreSQL、schema 和临时凭据已清理；协调 Agent 已停止保留的16379 Redis，日常服务未动。
- 未提交、推送、部署或触发远端 CI。
