# Acceptance

## Result

PASS。新的独立验收确认 DOCX 活动字段绕过已修复；其余范围沿用前轮独立审查及已通过证据，不重复未受影响的全量测试。通过范围受下述生产部署与开放式任务限制约束。

## Spec Coverage

- 通用任务、真实计算与九格式成果、连续版本和选中条目写工作：已有真实模型与确定性证据；普通任务的 `awaiting_input` 是既有队列状态，实际 `taskOutcome` 为完成。初轮 Office PDF 的结构通过不作为视觉通过依据。
- 执行隔离、来源传播、鉴权下载、任务租约、配额、恢复与清理：已核对当前源码、上一独立审查及对应定向证据。上一轮来源链、PDF 转义活动动作、失效成果元数据问题已修复。
- 中文 PDF：前轮独立验收已核对嵌入字体检查、实际中文提取及修复后两页截图；PPTX 步骤页无裁切。完整五页视觉证据由协调 Agent 保存于 `artifacts/spec042/model-office-fixed-rendered/`，前轮独立验收抽查 PDF 两页和 PPTX 一页。
- 浏览器：既有 20 项与生成文件 6 项使用真实 API；涵盖两角色、手机／桌面、主题、版本、12 个文件下载与摘要、错误和账号切换。没有未捕获异常、非预期 5xx 或横向溢出。
- 容量：`capacity.json` 记录总 4 CPU／8 GiB 等效限制下两个运行任务与一个排队任务全部成功；748 次真实 API 请求全 200，p95 16.77 ms。是临时 Linux 容器资源预算验证，不是生产服务器压测，也不代表长期满负载承载能力。

## Tests

- 后端全量 pytest：`server-final.xml` 为 693 通过、3 跳过；跳过的真实运行时项在 `sandbox-runtime-server.xml` 单独 3 通过。原组合命令随后因两个 `app` 模块命名空间冲突退出 1，实施已修测试入口；最终协议 10 项另行通过，含 18 个危险字段拒绝与 12 个普通字段兼容子用例，不能把原组合日志写成 exit 0。
- Web：全量 491 通过；类型、构建、相关 ESLint 与改动源码格式化采用协调 Agent 已执行的最终结果，不重复运行。保留的早期 `web-typecheck.log` 是修复前失败日志，不代表最终检查状态。
- 最后配额与文件回执定向检查：`sandbox-file-checks.xml` 12 通过、`sandbox-storage-quota.xml` 2 通过。
- 真实 runsc 隔离、资源耗尽、同名文件隔离、幂等、取消、控制进程重启、串行公平、worker 被 KILL 后回收：证据为 `sandbox-real.json`、`sandbox-recovery.json`、`sandbox-serial.json` 和 `sandbox-runtime-server.xml`。worker 故障证据证明回收，不扩大为新 worker 续跑。
- 请求覆盖：`server-final-requests.json` 覆盖 113／114 个方法与路由组合；剩余 health 已在容量测试真实访问。
- 本轮独立检查返工涉及的 `apps/sandbox/app/files.py` 和 `tests/sandbox/test_protocol.py` 当前源码与新增用例；这两个新文件尚未提交，无返工前源码快照，不将其称为 Git 增量审查。
- 本轮仅额外运行只解析的 DOCX 对抗复现：`.venv-server/bin/python artifacts/spec042/accept-office-fields.py`。`accept-office-fields-before.log` 的两个已接受反例，在 `accept-office-fields-after.log` 均变为 `REJECTED: Unsafe formula or field`。没有执行字段命令、修改业务代码或访问生产环境。

## Issues

- **已修复：DOCX 活动字段校验绕过。** `fldSimple` 现在检查 `w:instr`；复杂字段按 `begin`／`separate`／`end` 边界拼接 `instrText` 后检查完整指令，原有两个独立反例均被拒绝。外部载入字段按指令首词拒绝，保留 PAGE、NUMPAGES、DATE、REF 及 `REF INCLUDETEXT` 等普通引用；未发现本次返工的未解决阻断项。

## Regression Risks

- 生产启用仍须在目标 Linux 主机安装并验证 runsc、镜像与私有令牌配置；默认关闭时原助手仍可用。本地容量结果不替代目标主机隔离验收。
- 文件格式检查不保证开放式任务内容或全部排版正确；实际样本检查与普遍能力保证必须区分。未执行 Electron／ASR／发行包验证，均不属本次改动范围。未提交、推送或触发远端 CI。

## Required Rework

无。
