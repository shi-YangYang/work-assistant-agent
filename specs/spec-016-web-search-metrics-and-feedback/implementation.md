# Implementation — Spec 016

## Summary

已完成业务实施及定向返工，通过[独立验收](acceptance.md)；没有提交或推送。

- 工作列表改为服务端授权后游标分页，每页 20 条；关键词覆盖标题、摘要、阻碍与下一步，保留 URL 筛选、返回位置与空页回退。
- 团队看板和三类明细共用公司时区、员工集合及期间查询；工作读取期间末的可访问修订，报告按实际提交修订去重。明细链接选择历史版本。
- 聊天增加持久反馈快照、同源 SSE 和只读恢复；普通本人正文可逐步显示，团队与文档来源相关输出保留完整校验。工具参数不进反馈，正式结果优先，旧尝试无权写入，临时正文 24 小时过期。
- 管理员模型用量页按实际请求记录用途／服务／模型快照、结果、耗时及实际 Token；预算估算、缺失值和历史未知分开。聊天、语音、配置测试共用请求生命周期记录。

## Files

- `services/company/src/paa_server/queries.py`、`api.py`：授权分页、看板／明细、历史版本、用量及 SSE 路由。
- `usage.py`、`model_provider.py`、`model_services.py`、`models.py`、`agent/harness.py`、`worker.py`、`feedback.py`、`documents.py`、`service.py`：请求生命周期、真实阶段、授权快照与定期清理。
- `migrations/versions/0006_feedback_usage.py`：仅新增字段与索引，旧记录保留历史未知；拒绝破坏历史数据的 schema 降级，应用可独立回滚。
- Web 的列表／团队／详情、用量页、反馈订阅、共用日期／分页控件与响应式样式；同步 `packages/api-contracts`。
- `deploy/company/Caddyfile`：API 逐步刷新响应。
- `tests/server/test_search_metrics_feedback.py`、`tests/web/list-feedback.test.ts`：定向回归。

## Validation

- 独立 `paa_company_test` 由 0005 升级到 0006 成功；测试只使用固定模型与专用数据库。
- `npm run test:server -- tests/server/test_search_metrics_feedback.py tests/server/test_model_services.py tests/server/test_business_assistant.py tests/server/test_boundaries.py`：首轮 71 项通过，3 项新流式断言失败，定位为首片被节流抑制；修复后对应测试通过。
- `npm run test:server -- tests/server/test_search_metrics_feedback.py -k real_incremental --tb=short`：4 种 gate 场景通过（本人用户、本人管理员、断流、工具混合）。在上游尚未结束时直接捕获 API `/events` ASGI 输出，验证临时正文、恢复不重复调用、用量及终态。
- `npm run test:server -- tests/server/test_company.py tests/server/test_management.py --tb=short`：14 项通过。
- `npm run test:server -- tests/server/test_search_metrics_feedback.py -k 'full_authorized or document_stage' --tb=short`：2 项通过，覆盖授权后完整分页、实际解析阶段／缓存复用及反馈过期。
- 以上合计 90 个不同服务器用例通过；不重复已通过的无关检查。
- `npm run test:web -- tests/web/list-feedback.test.ts tests/web/navigation.test.ts tests/web/paged-resource.test.ts`：13 项通过，包含分页返回、旧请求丢弃、迟到事件与正式终态抢先到达。
- `npm run typecheck:web`、修改文件的 ESLint、Prettier、`git diff --check` 通过；`npm run build:web` 普通构建通过。未运行桌面检查。
- 复用已有 Caddy 镜像校验生产配置，并只替换上游地址连接临时固定 SSE 服务；带 gzip 请求时首快照在上游结束前 0.04 秒交付。临时容器与文件已清理。

## Targeted Rework

首轮验收指出的发送前地址拒绝归类已修复并通过新的独立验收：`RequestRecord.finish` 仅将无 HTTP 状态的地址校验失败记为 `not_sent`，清空开始时间和耗时，保留错误诊断；带 HTTP 状态的重定向仍为实际失败，网络中断的未知分类不变。

定向验证通过：`PYTHONPATH=services/company/src .venv-server/bin/python` 中将测试连接限定为 `paa_company_test`，执行 `pytest.main(['-q', 'tests/server/test_search_metrics_feedback.py', '-k', 'address_rejection_not_sent', '--tb=short'])`，**2 项通过**。聊天／文件转写均经过真实 `SafeTransport` 的受限地址拦截，并以固定 HTTP 307 响应对照核对请求数、成功率和耗时；没有重跑此前已通过检查。

## Limits

本轮没有调用真实在线模型，没有向日常会话写入测试消息。协调 Agent 已备份日常数据库、迁移到 0006、重启 Web／API／worker 加载最终代码，并完成只读电脑、手机页面检查；不把固定响应验证表述为实际服务商兼容性或生产部署验证。
