# 返工验收

## Result

**FAIL**。流式连接回收和授权证据更新已修复原问题，但重新授权后仍会沿用旧的 `not_requested` 内存标记，错误跳过尚未完成的用户请求。真实性能矩阵仍在执行，当前不判定整体验收或 20% 目标通过。

## 已确认

- [冻结清单](../../artifacts/spec056/implementation/source-manifest-rework.json)的 19 个文件哈希与审查源码一致。
- SSE 收到合法结束后继续消费同一响应迭代器，最多等待 50ms、读取 8KiB／128 行；超时、异常尾部关闭连接，外部取消继续传播。原有 2MiB 单行保护保留。
- [真实 HTTP 复现](../../artifacts/spec056/rework/stream-reuse.json)为 4 次流式请求复用 1 条 TCP 连接。已有 7 项正常结束、异常尾部和取消检查通过，未重复运行。
- 授权缓存使用当前用户原文、已授权实际读取、成果版本和业务回执摘要；新证据触发独立重判，不直接授权。来源归属、条目关联、角色、版本、幂等检查仍在实际执行前生效。
- 成功创建工作补齐合法成果来源后，只跨步骤清除相同完整业务载荷的未关联旧错误；不同内容、已绑定条目和独立副本不参与该新增匹配。
- 已有 8 项授权／反馈及 13 项旧工具／网络／大小保护检查的日志和 XML 均已审阅，未重复运行。前次独立 148 项结果继续保留。

## 新发现

### P2：重新判断后旧的“不需要执行”分类仍会覆盖当前结论

`agent/actions/intent.py` 只向 `context.unrequested_actions` 添加提案摘要，没有在证据变化、重新判断后移除旧分类。`agent/actions/operations.py` 会优先读取该集合。

受控复现使用真实 `execute`、读取工具及节点持久化：首次返回 `not_requested` → 实际读取改变证据 → 独立授权模型第二次返回 `missing_info`。模型确实调用了两次，但业务入口仍返回 `{"state":"not_requested","message":"仍缺目标说明"}`，而非当前的 `clarification / missing_info`。后续任务完成判断会漏掉这项仍需处理的请求。

应以每次有效判断的当前分类替换该提案旧分类，包括拒绝缓存命中路径；保持独立授权与失败原因，不能通过把所有拒绝清为成功解决。

## 验证证据

新增独立最小检查 **1 passed、1 failed，2.22 秒**，0 次外部模型调用：

- 失败：上述真实证据更新后的分类替换。
- 通过：直接调用注册的 `finish_task.ainvoke`，核对实际终态交付结构、正文和无业务写入标记。此前 `test_model_response_length[completion-True]` 只覆盖参数解码与预览，不应独自标记为工具执行覆盖。
- [复现代码](../../artifacts/spec056/acceptance-rework/test_review_probes.py)
- [日志](../../artifacts/spec056/acceptance-rework/probes.log)／[XML](../../artifacts/spec056/acceptance-rework/probes.xml)／[隔离与清理](../../artifacts/spec056/acceptance-rework/result.json)

没有修改业务代码。自建数据库 schema 已删除，无后台进程，未读取或修改日常业务数据。

## 后续验收

修复上述当前分类替换后，由新的独立验收检查相关差异与最小复现；不重复已经通过的无关测试。最终还需核对冻结真实配对、离线质量、完整成果可用时间和资源清理，再给出整体验收结论。
