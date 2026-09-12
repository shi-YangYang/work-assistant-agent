# Implementation — Spec 007

业务及定向返工已完成，独立工程复验和待补界面项见 [验收报告](acceptance.md)；未提交、推送或运行远端 CI。

## 实现

- `meeting_library.py` 在有界后台队列检索完整历史，日期按绝对时间比较，标题／转写／纪要仅匹配可见文本。返回每页最多 25 场及精确片段／纪要版本定位，SQL 查询有进度期限；页面通过请求代次处理旧响应，保留筛选与返回位置。
- 名称独立持久化，不改动 AI 标题或音频。列表和详情复用操作菜单、命名与永久删除确认框；纪要支持纯文本复制及系统保存的 Markdown／TXT 导出。
- 导出先以增量 SQLite backup 创建私有一致副本，再串行生成全文，不在录音数据库上长期持有读取事务。主进程每次读取 16 KiB，目标使用同目录临时文件加替换；取消、错误和过期均释放快照，内容不经过外部服务。
- schema 5 添加删除意图，文件清理前持久化；忙碌任务、后续任务启动及晚到写入共用 Repository 锁内状态判断。未完成清理仍显示会议及重试入口；重启在任务恢复前继续清理。删除限定会议目录内的标准 WAV 与恢复暂存文件，拒绝符号链接或未知文件。主进程阻止新的同会议媒体请求，并等待已打开读取流真正关闭。
- README 和技术基线记录实际操作、schema 与恢复边界。没有新增依赖、改变 CI、分支或模型配置。

## 验证

| 命令／范围 | 结果 |
| --- | --- |
| `PYTHONPATH=src/python .venv/bin/python -m unittest discover -s tests/python -p 'test_*.py' -k LibraryTests -k migration -k backup -v` | 14 通过：初始 8 项资料用例及既有 6 项备份／迁移 |
| 后补安全边界后的 `... -p 'test_meeting_library.py' -v` | 10 通过，新增纪要忙碌／晚到完成及符号链接保护 |
| 取消／过期资源释放改动后的 `... -p 'test_meeting_library.py' -k export -v` | 2 通过，最终资料测试文件共 11 项，各相关版本已定向验证 |
| 拒绝活动录音期间退出的顺序调整后 `... -p 'test_meeting_library.py' -k worker -v` | 1 通过，拒绝退出不提前关闭资料 worker |
| `npx vitest run tests/desktop/meeting-library.test.ts tests/desktop/media.test.ts` | 初始 8 通过，含现有媒体范围／边界 |
| `npx vitest run tests/desktop/meeting-library.test.ts` | 后补真实核心 JSON Lines 联通后 6 通过 |
| GUI 发现错误码白名单遗漏后 `npx vitest run tests/desktop/meeting-library.test.ts -t 'real core JSON Lines'` | 1 通过，确认空名称经真实核心返回可操作的领域错误 |
| `npm run typecheck` | 最新业务／测试类型通过 |
| 已安装 Prettier 整理本次 TS／TSX／CSS；ESLint 检查本次 TS／TSX | 通过；首轮 3 处规则问题修复后仅重检涉及文件 |
| `git diff --check` | 通过 |

测试使用临时资料，不改名、删除或覆盖用户会议。覆盖第 51 场／片段之后、中文和字面通配字符、日期偏移、稳定分页、改名持久化、完整多字节快照、取消／失败保持目标文件、剪贴板失败、任务忙碌及删除恢复、外键、迁移回滚和真实媒体流关闭。首轮一项时间戳测试误匹配元数据中的时长，已将断言限定到片段时间戳。

## 验证边界

协调 Agent 已在用户日常 `npm run dev` 环境完成主要非破坏性交互检查，具体证据与锁屏导致的待补项统一见 [验收报告](acceptance.md)。Windows 物理机、双平台安装包、真实麦克风／ASR、付费模型和远端 CI 未在本轮执行；不沿用旧 SHA 的通过结果。系统强制结束进程或断电期间操作系统临时目录的回收仍由系统管理；已登记的会议删除意图保存在数据库内，重启可继续。

## R1 定向返工 · 2026-09-12

- 分页请求绑定最后成功应用的查询，条件变更、清除和输入法组词立即使旧分页失效；首屏应用前及已有分页请求进行中不再产生分页请求。日期输入记录原生编辑状态，只有半输入时也可清除；清除时重新创建两端日期控件以清空浏览器编辑缓冲。
- 摘要先保留完整命中再分配有限上下文，允许的 200 字关键词不再被前文挤掉；每个预览正文最多 290 字，另有两端省略号。
- 按 S2 仅运行：`npx vitest run tests/desktop/meeting-library.test.ts -t 'preserves literal|pagination bound'`（2 通过，5 项无关测试跳过）、`PYTHONPATH=src/python .venv/bin/python -m unittest discover -s tests/python -p 'test_meeting_library.py' -k long_keyword -v`（1 通过，含 180／200 字两个子用例）、`npx tsc --noEmit -p tsconfig.web.json`（通过），以及本次三个 TS／TSX 文件的 Prettier 和 ESLint（通过）。未重复 R2～R4 已通过的检查，也未构建、提交或推送。
- 日期半输入的 GUI 复验尚未执行：协调 Agent 遇到 macOS 锁屏，待用户解锁后在原 `npm run dev` 窗口补验；本返工记录不宣称独立验收或 GUI 已通过。
