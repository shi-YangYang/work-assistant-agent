# Token Plan 图片接口纠错实施报告

## 改动

- `wan.py` 按精确的 `token-plan.cn-beijing.maas.aliyuncs.com` 主机识别同步图片接口，使用原服务主机与密钥，POST `/api/v1/services/aigc/multimodal-generation/generation`，不发送异步请求头。百炼原生地址保留原异步提交／查询流程。
- Token Plan 请求仅发送文字和尺寸；默认 2K 对应 `2048*2048`，1K 对应 `1024*1024`，已有明确像素保持。同步图片使用独立 300 秒网络与总预算，聊天超时不变。
- 管理员测试使用同一分流逻辑。前端允许 Token Plan 发现的 `wan2.7-image` 自动匹配图片协议，移除错误的禁用提示；不扩大为其他图片模型。
- 新增 `0030_image_provider_result`，为图片操作增加独立 JSONB 回执。同步结果的图片地址、有效用量和请求编号先保存，再下载／发布；不伪造异步 task_id，不把临时签名链接暴露给前端或 Agent。
- 同步回执在下载、发布、缓存失效、租约换代后可恢复。首次回执提交失败会尽力保存已取得的事实；无回执的未知提交禁止自动重发，迟到结果不能绕过取消、租约、权限或服务撤销检查。
- 未改动普通 Agent 提示词、工具目录、规划或最终文字生成流程；同步图片发布不依赖最终文字成功。

## 验证

后端入口均为：

```sh
.venv-server/bin/python scripts/company/web-acceptance/environment.py exec \
  --metadata artifacts/spec065/tests/environment.json -- \
  .venv-server/bin/python -m pytest -q --tb=short <测试路径>
```

| 范围 | 结果 |
| --- | --- |
| `tests/server/modules/image_generation/test_protocol.py` | 45 passed，0.11 秒；覆盖 Token Plan 官方同步请求形状、同主机密钥、独立超时、原生异步及既有下载安全／尺寸 |
| `test_token_plan.py test_migration.py test_operations.py test_configuration.py`（均在上述图片测试目录） | 39 passed，11.14 秒；证据 `artifacts/spec065/tests/token-plan-fix.log` |
| `test_operations.py::test_agent_lazy_generation_duplicate_calls_persists_before_final_text` + `test_token_plan.py::test_sync_expired_receipt_result_is_terminal_without_new_generation` | 5 passed，4.86 秒；补齐同步／异步最终文字成功／失败及同步地址过期，证据 `artifacts/spec065/tests/token-plan-agent.log` |
| `npm run test:web -- tests/web/model-services` | 首轮 38 passed、1 failed；失败为旧测试把 Token Plan Wan 预期写成不支持 |
| 更新旧断言后，`npm run test:web -- tests/web/model-services/model-service-drafts.test.ts` | 31 passed；其余三个未改动测试文件沿用首轮通过结果，未重复运行 |
| 本次 4 个 TS 文件限定 Prettier／ESLint、`git diff --check` | 通过 |

0030 先在 owned tests schema 迁移。迁移测试另建并清理独有临时 schema，执行 `0028 → 0029 → 0030 → 0029 → 0028`，实际插入旧账号、路由和异步图片记录；升级新增空回执而其他字段逐值不变，降级保留旧数据。未在用户库做降级或破坏性测试。

关键故障断言包括：一次同步 POST、不同工具调用去重、等待同步响应时数据库连接池无占用、回执首次提交失败、下载／发布失败、缓存文件丢失、未知超时、迟到回执与租约换代、取消后不发布、空图片与过期结果不重发。Agent 固定流程断言图片在最终文字失败前已经持久可读。

## 边界

本实施 Agent 未使用真实密钥、未发起真实生图、未操作日常或生产数据库，未 commit／push。协调 Agent 已另行完成真实 Token Plan 一次出图与日常迁移重启，其证据由协调 Agent 记录，不能混为本报告的自动化夹具结果。

所有本次定向检查已通过；未运行全仓测试或重复既存架构检查。外部成功与本地存储仍无法实现端到端 exactly-once，无回执的中断窗口选择阻止盲目重发。等待新的独立验收。
