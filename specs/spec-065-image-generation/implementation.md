# Implementation Report

本文件记录首批实现及其验证。Token Plan 同步接口修补见 [token-plan-fix.md](token-plan-fix.md)；后续兼容图片模型、尺寸配置和本地运行验证见 [model-config.md](model-config.md)。尺寸及型号范围以最新 Spec 和扩展报告为准。

## Summary

已实现管理员独立图片用途、`dashscope-image` 协议与 `wan2.7-image` 文字生图，复用个人成果的 PNG 预览、下载和实际宽高展示。普通聊天仅增加简短能力目录，完整图片工具按需加载，不新增规划、润色或核对模型阶段。

异步生成先领取持久操作，再提交、查询、下载和发布。相同消息的操作编号／规范化请求均可复用；未知提交阻断重复 POST，已知 task_id 只恢复查询或下载。提交回执首次落库失败仍尽力保留 task_id，任何已有无 task_id 操作都不会重新提交。租约、权限、服务撤销在发布前复验；成果发布不依赖最终文字回答成功。

未 commit、未 push、未修改生产环境或用户存量模型配置。

## Files Changed

- `integrations/models/images/`：原生异步协议、固定尺寸换算、逐跳与 DNS 校验的受限 PNG 下载、真实解码。
- `modules/image_generation/`、`0029_image_generation.py`、ORM registry：幂等操作、任务与配置快照、租约恢复、私有成果发布及缓存文件完整性校验。
- `modules/model_services/`：显式聊天／ASR／图片能力映射、用途与旧客户端兼容、冻结配置及图片测试。图片测试使用独立 `/settings/model-services/test-image` 入口，300 秒服务端预算及 310 秒客户端预算；旧 `/test` 的图片用途仍兼容。
- Agent tools/catalog/prompts/progress：按需 `images` 能力、`generate_image`、生成图片进度与回执复用。
- 成果 serializer、文件 cleanup、Web 模型配置／用途／测试／用量／图片成果、公共 API 类型同步调整。
- `tests/server/modules/image_generation/`、相关 Web 测试：协议、尺寸、权限、破坏性故障与端到端受控工具调用。

文件树见 `plan.md`。未新增依赖或常驻容器；最长新增业务 Python 文件为 240 行。

## Important Decisions

- 首轮仅实现万相原生协议，误拒绝了官方支持的 Token Plan；当前补齐同步接口，修补证据另见后续验收。
- 默认省略 size 沿用服务商 2K；按用途／比例固定换算，合法自定义像素优先，4K 和矛盾尺寸在请求前拒绝。思考参数不覆盖服务商默认。
- 生成图片领取现有成果的空闲 step 槽，避免与同轮文稿／沙盒成果冲突。
- 网络等待不在数据库事务内。图片服务成功与本地交付失败区分，恢复沿用同一用量记录，不制造重复调用。
- 未发布文件保留 24 小时供恢复；删除会话后沿用私有文件清理。外部签名 URL 不进入 Agent 结果或前端。
- 未发布文件过期或损坏时不信任缓存元数据；只恢复原任务下载或明确失败。发布与清理共用存储锁，完整文件校验在数据库连接外执行，详见 [缓存恢复返工](rework.md)。

## Tests

本次为 S3，限定图片、模型服务、Agent 工具目录、相关 Web 与迁移／模块边界；未运行全仓测试。

后端通过下列隔离入口执行（只注入自有测试 schema，不包含凭证输出）：

```sh
.venv-server/bin/python scripts/company/web-acceptance/environment.py exec \
  --metadata artifacts/spec065/tests/environment.json -- \
  .venv-server/bin/python -m pytest -q --tb=short <下列测试路径>
```

| 范围 | 结果 |
| --- | --- |
| 首批 `tests/server/modules/image_generation` | 47 passed |
| 图片模块 + `tests/server/modules/model_services/test_model_services.py` + `tests/server/agent/tools/test_tool_catalog.py` | 101 passed；24 项因并行验收进程耗尽本地 PostgreSQL 连接失败 |
| 释放已完成采样进程后，仅对上述模型服务／目录失败项使用 `--lf` | 24 passed、48 deselected；未改产品连接限制、未重发模型样本 |
| 更新后的 `test_operations.py` + 配置测试单例 | 15 passed |
| 回执提交失败、最终文字成功／失败、未知提交、迟到 task_id、非预设比例与畸形额外结果定向项 | 17 passed |
| 独立迁移、429／内容拒绝／空结果、ORM 注册 | 5 passed |
| `test_architecture.py::test_dependencies_are_acyclic_and_do_not_import_entrypoints` | **既存失败**，见下文 |
| 未发布缓存完整性、保留期清理、并发清理／发布、过期恢复及既有图片操作 | 28 passed、41 deselected |
| 受共用存储锁影响的既有沙盒清理与额度定向项 | 5 passed、7 deselected |

关键断言包括：一次外部 POST、同输入不同 call ID／操作编号复用、同轮不同成果槽、未知状态禁止改提示词再提交、结果恢复、首次回执提交失败、取消／撤销不发布、私人文件越权拒绝、有效部分结果保留、最终文字失败后 PNG 仍可读取、真实解码尺寸、私网／元数据／恶意重定向拒绝。

迁移测试在自建 `image_migration_<uuid>` schema 中执行 `0028 → 0029 → 0028`，验证旧账号、用途 JSON 与 revision 不变、新唯一约束存在；结束后仅删除该临时 schema。另有 tests/candidate schema 的实际升级完成。未对有用户数据的库降级。

Web：

```sh
npm run typecheck:web
npm run test:web -- tests/web/model-services tests/web/dom/assistant/assistant-deliverables.test.tsx tests/web/dom/assistant/generated-image-size.test.tsx
npm run test:web -- tests/web/requests/api.test.ts
```

类型检查通过；相关 Web 6 文件 47 测试通过；请求客户端 20 测试通过。本次改动的 TS／TSX 使用安装的 Prettier 格式化，限定这些文件的 ESLint 通过，diff 空白检查通过。

协调 Agent 在隔离公司实操：wan 自动识别、图片模型无聊天参数、独立用途保存、1440／390 宽度、通过真实持久化流程注入合成 PNG 后的多图、实际尺寸、刷新恢复与私有下载。截图在 `artifacts/spec065/ui/`，**合成夹具不是 Wan 真实出图**。

## 普通 Agent 性能对照

协调 Agent 的独立采样：相同配置与输入，基线8条后候选8条，low／high 每种场景各一对。

| 场景 | low 总耗时，基线→候选 | high 总耗时，基线→候选 | Provider 请求数 low / high |
| --- | --- | --- | --- |
| 知识 | 3.22 → 4.22 秒 | 5.82 → 3.12 秒 | 1→1 / 1→1 |
| 工作查询 | 6.37 → 6.31 秒 | 5.25 → 6.84 秒 | 3→3 / 3→3 |
| 搜索 | 25.03 → 25.13 秒 | 16.76 → 12.06 秒 | 5→7 / 4→3 |
| 沙盒 | 9.43 → 9.018 秒* | 8.40 → 9.41 秒 | 3→3 / 3→3 |

*候选 low 沙盒 9.018 秒为终态 SSE；随后独立取证连接耗尽，完整 HTTP 读回时间未保存，不能视为同一耗时口径。没有重发该样本。

16 条均有完整回复，无业务写入、无图片工具调用，已有四份沙盒文件鉴权下载成功。普通文本／查询／搜索终态为 awaiting_input，沙盒为 succeeded。搜索调用数变化来自模型选择不同抓取路径，没有新增图片规划阶段。每组仅一对且非随机交替，不能据此声称总体准确率不变、稳定提速或统计显著结论。

## Known Limitations

- 首轮原生 wan2.7-image 真实方图／横图／竖图验收**未执行**。原先误判 Token Plan 不支持生图；官方已提供同步图片接口，需补实现并另行记录真实调用，模拟 PNG 与聊天模型采样不能替代该证据。
- 全后端依赖检查发现 `work/content/document.py → checklist.py → document.py` 循环。两文件与 HEAD 逐字相同，属于既存问题；未修改无关业务，也不把该检查写成通过。
- 外部提交与本地持久化不能获得端到端 exactly-once；无法确认提交结果时保留未知并阻止盲目重发。这里选择避免重复副作用，而不是伪造成功或自动换参数。
- 实施完成，等待新的独立 Agent 验收；本报告不替代 acceptance。

## Token Plan 真实配置复验

已使用本地保存的 Token Plan 服务及原密钥，通过修正后的管理员 `image_probe` 完成一次真实图片生成与读取：`wan2.7-image` 返回 2048 × 2048 PNG，总耗时 13.565 秒；实际用量为输入 849、输出 2、总计 851 tokens。未更换服务地址、密钥或用途路由。结果在 `artifacts/spec065/token-plan/real-probe.json`，图片在同目录 `generated-bird.png`。此证据覆盖配置测试及真实方图，不代表原生异步服务、横／竖图和完整聊天浏览器流程均已真实验证。
