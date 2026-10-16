# Implementation Report

## Summary

实现 DOC／RTF／ODT → DOCX、XLS／ODS → XLSX、PPT／ODP → PPTX 的 worker 固定转换链路。选择时显示旧 Office 兼容提示，上传仅保存；发送后转换、解析并保存分段，原件不变。现有 PDF、OOXML、文本及代码保持直接解析和原 parserVersion，未增加模型轮次、模型工具或 Agent 沙盒依赖。

新增格式每 worker 转换并发 1，普通解析并发 2；混合任务不会用等待转换占住普通解析槽。转换与解析共用 60 秒处理预算，排队服从现有任务期限。成功结果按原件及转换策略版本复用，同消息相同内容共享任务，各附件仍独立保存身份和分段。修复消息 DTO 未排序导致发送／刷新后附件顺序随机的问题，使用已有 attachmentOrder，并给历史记录稳定 fallback。

## Files Changed

- `packages/api-contracts/input-rules.json`、`src/index.ts`：7 种转换路由、可选阶段及格式字段。
- `apps/server/app/integrations/parsing/{formats,office_conversion,office_process,office_validation,office_preflight}.py`：路由、固定转换、进程管理、结构及公式缓存核对、真实部署预检。
- `document_parser.py`：允许固定转换 supervisor 配置 Windows Job 资源上限；原解析器默认仍为单进程、512 MB、禁止网络／子进程，新增 Job 总内存限制。
- `modules/attachments/{policy,router,documents}.py`：上传规则、轻量文件头、明确 MIME、安全 DTO 白名单。
- `tasks/processing/{documents,handlers}.py`：阶段、版本、共享任务引用计数、取消、轻重调度、持久化及计时；`modules/messages/serializers.py`：附件顺序。
- `worker.py`、Python requirements、worker Dockerfile、release.sh、CI：一次依赖探测、残留目录清理、固定生产 LibreOffice 依赖、切换服务前真实预检；API 镜像不安装 LibreOffice。
- Web 由 frontend071 实施：`Documents.tsx`、`ComposerAttachments.tsx/.module.css`、`utils/attachments.ts`，以及对应 DOM／资源规则测试。
- 测试：`legacy_samples.py`、`test_office_conversion.py`、`test_document_parser.py`、`test_release.py`；workflow071 独立实施 `test_document_preparation.py` 与 `test_legacy_document_workflow.py`。
- `docs/setup.md`、`docs/architecture.md`、`constitution/tech-stack.md`：本地安装、兼容边界及运维说明。

## Important Decisions

- 生产 LibreOffice Writer／Calc／Impress 固定 `4:7.4.7-1+deb12u14`，仅 worker 安装。启动探测缓存，普通消息不执行版本检查；冷探测不持有数据库事务。
- 转换和旧解析器是不同进程。固定 CLI、内部生成输入名、私有目录、最小环境及 profile/user 配置，不继承业务凭据／代理。拒绝宏、自动外部引用、活动嵌入对象和异常结构。ODF 自动资源必须是包内实际成员，拒绝相对越界和编码绕过；普通超链接不自动访问。
- POSIX 全部后代继承 supervisor 的独立进程组，父 finally 即使遇到 supervisor 硬杀也回收整组；worker 死亡由 supervisor 检测并清理。父进程拥有临时目录，supervisor 崩溃仍可清理；启动仅删除拥有者已死亡且有有效 owner 标记的本项目目录。
- 转换器仍是业务 worker 的子进程，**不具备完整网络／文件系统沙盒隔离**。现有 parser 审计限制保持；固定转换依赖漏洞仍需正常维护。
- XLS／ODS 仅核对序列化公式缓存，不另建旧格式正文解析器。数值、字符串、错误、布尔及坐标不一致时失败。仅对严格等值的布尔和数值 0／1，双向恢复派生 XLSX 的原件缓存类型，不修改数值；ODS 布尔缓存只接受 `true/false/1/0`，缺失或非法值明确失败，不推为 false。对过期缓存 42.125 被转换成 2469 的固定样本明确拒绝；正常已知公式、金额和日期通过。

## Tests

本次按 S3 验证附件、转换、相关 UI 和部署子系统，没有运行无关桌面／全产品验收，也未操作线上。

实施 Agent 实际执行：

| 检查 | 结果 |
| --- | --- |
| `PYTHONPATH=apps/server:tests/server .venv-server/bin/python -m pytest tests/server/modules/materials/test_office_conversion.py -q` | 20 passed，18.03 秒。7 种真实转换、原件不变、表格值与备注、过期缓存、结构／活动内容、ODF 越界、实际有效 profile、无输出／崩溃／超时／取消、worker 与 supervisor SIGKILL、子孙及临时文件清理、输出上限、目录权限错误、startup 安全清理。 |
| 指定 `DATABASE_TEST_URL` 的 pytest：`test_documents.py test_attachment_duplicates.py test_attachment_upload_lifecycle.py test_document_parser.py test_document_constraints.py test_work_materials.py` | 85 passed；另 2 条 Windows Job 原断言没有包含新总内存 flag，失败已定位并更新测试，未删除有效断言。 |
| `... pytest tests/server/modules/materials/test_document_parser.py -q -k windows_job_object` | 修订后 4 passed，0.05 秒；验证默认 parser 与 Office 配置的进程／单进程及总内存／CPU／失败关闭。属于 Windows API 契约测试，不冒称真实 Windows 内核运行。 |
| `.venv-server/bin/python -m unittest discover -s tests/deploy -p test_release.py -v` | 16 passed，25.114 秒；Office 预检失败不切换运行版本。 |
| 本次共享 JSON／TS／CI YAML 的项目 Prettier，`git diff --check` | 已整理；无空白错误。 |

其他实施／协调 Agent 的已报告证据：

- frontend071：完整 Web 92 个文件、832 条测试通过；Web typecheck、本次文件 lint／Prettier 通过。
- workflow071：两个新增测试文件累计 12 条通过，包含真实 7 格式、上传前零处理、跨批 12 文件／成果／来源、重复与坏文件隔离、9 附件含图片语音、工作材料源删除、共享取消、数据库提交失败后新租约恢复、旧 fence 拒绝、排队／转换／保存前取消后真实重试及其他用户登录／普通任务恢复。详细流程由该 Agent 报告，不以 mock 转换替代真实链路。
- root：完整 `docker build --target worker -f deploy/company/Dockerfile -t noria-spec071-worker .` 成功；原镜像和最新 `apps/server/app` 只读挂载后分别运行 `python -m app.integrations.parsing.office_preflight` 成功，实际为 LibreOffice 7.4.7.2。环境是本机 Linux ARM64 容器，未部署线上。
- root 浏览器：详见 [browser-verification.md](browser-verification.md)，包括 DOC 上传／发送／问答／刷新、坏文件与正常文件混合、7 附件稳定顺序、实际 SSE 分段正文与引用。
- 性能采集已完成，详见 [performance.md](performance.md)：普通路径 8 组各 30 配对通过，准备／首模型 p95 未超过规定阈值、模型轮次未增加；新增格式及参考／重复／复用共 360 个正式样本通过。四账号一慢三快中三个 TXT 任务先于大 DOC 完成。性能数据使用 native 26.8，先于下述 ODS 返工采集，不作为生产 7.4 最终源码性能结论。

固定样本生成入口为 `tests/server/_support/materials/legacy_samples.py`，材料均自行编写，经真实 LibreOffice 导出为 Office 97 容器及 RTF／ODF；不是改后缀的 ZIP。可检查生成副本 `artifacts/spec071/fixtures/`。测试数据库为本次独占 PostgreSQL（15471），未用员工数据。

独立验收补测后修复了 ODS 的重复空白计费、严格等值缓存类型恢复、缺失／非法布尔缓存三个边界。新增 19 条公式与边界用例，按实际改动定向运行 9／7／5／4 条均通过；固定生产版本七格式及完整性边界合计 25 项通过。详见 [rework.md](rework.md)；没有新增模型调用或改变普通文件路径。

## Known Limitations

- 本机 native LibreOfficeDev 26.8 与生产固定 7.4 不同；生产固定版本在 Linux ARM64 容器已补齐七类真实格式与公式边界，性能数据仍来自 native。没有真实 Windows、生产 AMD64 或 Microsoft Office／WPS 本体导出的额外样本，不把这些环境列为通过。
- 复杂版式、图形、字段、活动对象和特殊公式不承诺无损；DOC 固定样本的表格文字完整，但当前转换后的提取可能呈连续段落。公式无法可靠保留时明确拒绝，建议用户另存 XLSX。
- 实际低／高强度服务商模型样例尚未运行：本次隔离环境使用受控模型验证真正读取内容、来源及持久化；受控响应不代表所有真实模型均按相同方式调用工具。
- 未制造宿主机全盘耗尽或全机 OOM。已验证输出上限／权限失败、进程崩溃和清理，以及资源限制配置；不能将配置断言声称为所有内存／磁盘极端故障均实测完成。
- 本报告是实施结果，不是最终独立验收结论。没有 commit、push 或线上操作。
