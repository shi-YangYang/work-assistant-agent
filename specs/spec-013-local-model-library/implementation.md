# Implementation — Spec 013

## 结果

业务、返工与日常 GUI 检查完成，新的独立验收为 [PASS](acceptance.md)。真实模型矩阵已结束，17 组成功、base 中文异常中断，详细结果只在 [verification.md](verification.md) 与共享 JSON 维护。未提交、推送或触发 CI。

## 实现

- `model_catalog.py` 固定六款模型的真实来源、revision、完整 SHA256／大小清单，保留旧 small 路径。`model_manager.py` 管理单次准备、校验、取消、重试、多缓存、原子默认设置、空间检查和受引用／文件占用保护；缓存启动只校验，不逐个载入全部大模型。
- `asr_worker.py` 提供真实 `zh/en/mixed` 配置；混合开启 multilingual 自动检测，三者均 transcribe。工作线程按完整配置加载，加载和推理串行；试加载不抢占当前推理，取消准备使用独立 token；切换时释放旧 Provider。
- SQLite schema 6 在迁移前备份。候选 job/chunk/segment 独立保存，generation 拦截晚到提交，成功事务一次切换已发布文字和配置。失败、暂停和取消保留旧文字／纪要；完成候选不触发自动付费纪要。旧文字分页标识失效时重新读取，旧来源 ID 不复用，搜索查询新已发布文字。
- 纪要注册与候选注册互斥，旧快照不能在文字更新后发起生成。旧纪要显示“文字记录已更新，纪要待更新”，隐藏失效原文按钮，复制／导出附同样说明；手动新纪要成功后清除标记。
- 受控 stdio／IPC 管理操作贯通，新增模型和文字版本错误在桌面保留可操作说明。模型设置页为紧凑响应式列表，真实下载／占用大小、当前默认与语言、下载／切换／确认删除、按语言展开质量。历史会议显示实际使用配置，并提供确认模型／语言的重新转写及取消。
- 质量 UI 只投影错误率和独立进程峰值内存，附来源、测试机与样本条件。基准未完成项显示失败原因，不用估计数字替代，不展示耗时。

## 本次文件

业务：`src/python/paa_core/{model_catalog,model_manager,asr_worker,transcription,transcript_store,repository,summary_store,meeting_library,protocol}.py`；`src/desktop/{main,preload,core-manager,json-line-client}.ts`；`src/shared/{contracts,summary-contracts}.ts`；`src/renderer/{LocalModelSettings,Transcription,MeetingMinutes}.tsx`、`styles.css`。

测试：`tests/python/test_model_library.py`、已有 `test_recording.py`／`test_summary.py` 的 schema 6 断言、`tests/desktop/core-manager.test.ts`。共享质量 JSON 和基准脚本由评测协作者负责；Spec／决策／交接及长期文档由协调 Agent 负责。

## 验证（S3 定向范围）

| 命令／范围 | 结果 |
| --- | --- |
| `npm run typecheck` | 通过；最新合同与 UI 类型检查 |
| `PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_model_library -v` | 最后 13 项通过：目录、真实模式、默认持久化与不可变任务、失败／取消／发布事务、搜索／摘要、恢复、引用删除、试加载互斥、空间与 schema 5 升级 |
| `PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_model_library test_transcription test_meeting_library -v` | 当时 39 项全部通过；随后只新增上述 3 个模型测试并定向运行 13 项 |
| `PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_summary test_meeting_library test_protocol -v` | 25 项摘要和 7 项协议通过；一个旧 library 删除晚到 fixture 缺少 generation 被发现并修复，library 全部 12 项已在上行重跑通过 |
| `PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_recording.RecordingTests.test_schema3_backup_and_paused_crash_recovery_preserve_frames -v` | 通过；录音旧库迁移断言更新为 schema 6 |
| `npx --no-install vitest run tests/desktop/core-manager.test.ts tests/desktop/json-line-client.test.ts` | 最后 19 项通过，包括实际 Python 目录／默认设置、受控无效请求。发现新增公开错误被转换为 remote_error，补齐明确允许列表后通过 |
| `npx --no-install vitest run tests/desktop/core-manager.test.ts tests/desktop/meeting-processing.test.ts tests/desktop/meeting-library.test.ts` | 15 项通过；后续增加 core 目录测试见上一行 |
| 修改 TS／TSX／CSS 的本地 Prettier、定向 ESLint、`npm run build`、`git diff --check` | 通过 |

测试使用临时夹具，不修改用户会议或使用付费密钥。日常 GUI 由协调 Agent 使用 `npm run dev` 验证；协作者真实评测读取公开音频和已验证模型，不新增用户会议。未运行 Windows 实机推理、全量公司服务测试、安装包验收或 CI。

## 已知边界

- base／中文的真实样本触发现有单块 500 词输出保护，完整语料组错误率和内存标为测试未完成；未抬高边界或重复选样跑分。其余实际测量与异常由 verification.md 记录。
- 中英混合为逐段语言检测，不承诺逐词切换正确；错误率按真实记录显示。
- 本轮保留 CPU INT8／单 worker 与有界请求。大型权重在 CPU 上较慢；未验证的 Windows 性能不能从 macOS 推断。
- 用户资料迁移前另有协调 Agent 备份，正式迁移仍会生成 schema 5 备份。schema 6 新写入数据不宣称可由旧核心直接打开。

## 实测后的等待预算

large-v3 混合组单块达到 84.561 秒，原 90 秒预算仅余约 5.4 秒。默认等待按操作分为加载 90 秒／单块推理 180 秒，仍可取消且无自动重试；显式 `timeout`（包括运行时赋值）继续覆盖两类请求。未改变 Provider、语言配置或分块，不重跑已完成质量矩阵。此处是协调 Agent 在新增实施任务遭工具名额限制后完成的小范围集成，仍交新的独立验收者复核。

定向运行 `PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_transcription.TranscriptionTests.test_worker_allows_slow_inference_but_bounds_loading_and_overrides test_transcription.TranscriptionTests.test_worker_crash_and_timeout_are_bounded_and_leave_no_child -v`：2 项通过。虚拟时钟验证较慢推理可完成、加载和推理仍有界、动态短预算生效；既有真实 spawn 检查确认崩溃／超时回收子进程。未追加全套测试或构建。

## 首轮验收返工

- 修复 R2：`continuationBlockedReason` 从持久化任务的原模型／revision 解析错误生成，与 `canContinue` 同次计算；缺失／损坏和版本不匹配均返回明确原因，不使用当前默认模型替代。版本不匹配说明包含所需模型与 revision。
- 会议文字区域直接展示恢复阻止原因，并提供“查看本地转写模型”入口；显示条件不再依赖默认模型是否就绪。原模型恢复就绪后清除原因，保留原任务配置。
- 定向回归 `PYTHONPATH=src/python:tests/python .venv/bin/python -m unittest test_model_library.ModelLibraryTests.test_resume_reports_original_model_blocker_even_when_default_is_ready -v` 通过：默认 small 就绪而原 tiny 缺失／损坏、原 revision 不匹配、就绪后原因清除、继续失败不改快照。`npm run typecheck`、本次 TS／TSX Prettier 及 `git diff --check` 通过。
- 返工仅修改状态、错误说明、对应 UI 导航及上述回归；未改 Provider／评测参数，未操作用户会议、密钥或模型文件。新的独立验收者已确认该缺陷关闭。
