# Acceptance

## Result

PASS。请求精简已通过独立复验。后续五项既存失败由协调 Agent 按用户要求直接修复，Web／API 全量复测通过；这五项修复未另作独立 Agent 验收。

## Spec Coverage

- 六类初始化资源、StrictMode、空会话、静置 60 秒、focus 静默、恢复合并、共享 SSE、终态同步及旧 GET 失效有组合 DOM／浏览器证据。返工后的 Chromium 记录仍为已有会话六类各 1 次 GET、focus 0 次、online 与 visible 合并一轮；整页启动另有 1 次 `/auth/me`，通知单独计数。修改前已有会话助手 GET 为 14 次，修改后为 6 次，详见[浏览器验证](../../artifacts/spec039/browser-validation.md)和[返工请求记录](../../artifacts/spec039/browser-after-rework.json)。
- 身份代次、成员范围与完整路径隔离，订阅取消、有限闲置释放、Retry-After、完整写入结果与旧响应竞争、历史展开范围、首屏外任务及迟到 SSE 终态均有定向断言。共享只读资源仍使用唯一 API 客户端，未扩大至写请求或全站隐式缓存。
- [Web 请求覆盖清单](../../artifacts/spec039/request-coverage.md)逐项列出 101 个方法／路由入口，区分真实请求封装的传输契约、服务端 HTTP／数据库、DOM 和浏览器证据；覆盖 GET、写入、上传／下载、认证跳转和 SSE。契约通过不能替代页面交互、供应商或媒体设备验收。
- Chromium 的 12 条组合流程核对首条创建与重复点击、连续追问、人设／权限、临时回答、工作确认、中断、失败重试、断流、文件上传、幂等重试和冲突后的 UI／受控业务结果；报告、联网及其他服务端业务断言见请求清单。未把受控模型或 HTTP／SSE 响应写成真实供应商验证。

## Rework Verification

1. **恢复入口手动重试：通过。** `QueryResource.get(..., { fresh: true })` 显式重新读取，普通 `get()` 保留稳定错误与 Retry-After；`restoreConversation`／`latestChat` 透传选项，页面只消费一次新的 `resumeRevision`，避免导航交接再请求。正式用例覆盖 remembered／default／latest 三个入口、并发 fresh 去重及 Retry-After；浏览器实际点击上次会话恢复重试后，详情 GET 从 1 次变为 2 次且输入框恢复。
2. **详情首次失败后的恢复：通过。** `Assistant` 在聊天区尚未挂载时持有恢复监听，详情错误提供手动重试；聊天区通过注册回调复用父入口，保留同一恢复合并窗口。正式 DOM 用例核对网络恢复挂载聊天区后紧邻的 visible 不再次刷新；浏览器网络恢复和手动重试各只新增 1 次详情 GET 并恢复输入框。
3. **未共享分页写后补读：通过。** `PagedResource.refresh()` 仅对显式共享实例采用被动合并；未共享实例保留请求期间的 `refreshPending`，旧 GET 完成后补读一次。正式回归模拟报告写入发生在旧列表 GET 期间，断言共 2 次读取及新报告结果；共享实例的重复被动刷新仍只有 1 次读取。

以上结论基于独立代码／断言审查和已有执行证据；本轮未修改业务代码或正式测试，未重复执行已经通过的检查。上一轮 `acceptance-repro` 的默认恢复二次调用不再代表显式手动重试 API，保留为历史失败证据，不用它否定新的 fresh 入口。

## Tests

- 返工相关最终覆盖为 54 项通过：从 [rework-tests.json](../../artifacts/spec039/rework-tests.json) 采用资源、分页、恢复 API 和独立聊天的 43 项通过结果；页面恢复与预算采用最终 [rework-recovery-tests.json](../../artifacts/spec039/rework-recovery-tests.json) 的 11 项通过。前一个日志原始结果为 53 通过、1 失败，其重复 fresh 问题已修复并由后一日志覆盖，不能称该原始日志全绿。
- [浏览器恢复记录](../../artifacts/spec039/browser-recovery.json)的 remembered-retry、detail-online、detail-retry 三项均通过；已核对脚本实际断言恢复输入框和详情 GET 增量，未出现页面异常。
- 修复后的 Web 全量：**475 项通过**，见[Web 测试日志](../../artifacts/spec039/five-fixes-web.log)。Web 源码此后未再修改。
- 修复后的公司 API 全量：**659 项通过**，见[API 测试日志](../../artifacts/spec039/five-fixes-server-final.log)和[结构化结果](../../artifacts/spec039/five-fixes-server-final.xml)。使用专用测试数据库的独立 schema，结束后清理；未使用业务数据或真实模型密钥。
- 已核对此前 Web 类型／构建、86 项助手回归、129 项资源／请求契约日志；最终返工源码的类型和改动文件 ESLint／Prettier／diff 检查通过见[实施报告](implementation.md)。构建通过证据来自返工前，返工未重复构建；本次没有新增检查结果冒充既有结果。
- 上述为本地验证，未推送或查询远端 CI，不能声明 CI 通过。

## Issues

五项既存失败均已解决：

- Web `architecture.test.ts`：附件限制常量移至纯工具层，保留依赖边界检查。
- Web `component-composition.test.ts`：核对实际录音按钮的可访问名称、录音状态和时长。
- API `test_architecture.py`：解除问题过期、任务续接、报告提交和答复核对的四组依赖环；复用原处理逻辑，不放宽架构规则。
- API `test_attachment_experience.py`：通过修正、重试接口和任务领取处理转写，验证新输入版本、历史保留及不重复 ASR。
- API `test_management.py`：允许当前会话任务投影，明确断言不包含其他会话的内容、消息 ID 或授权来源。

## Regression Risks

- 真实模型／钉钉／ASR 供应商、浏览器原生媒体播放／下载及真实设备未执行；受控证据不替代这些环境验收。

## Required Rework

无。
