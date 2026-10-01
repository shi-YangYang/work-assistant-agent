# 返工前验收证据

以下保留首次独立验收的完整结论与问题。当前结果见 [acceptance.md](acceptance.md)；后续修复不能将原失败改记为通过。

# Acceptance

## Result

FAIL

独立审查发现报告事实遗漏、材料来源权限未继承，以及确认预览和清单布局缺口。后端全量回归尚有失败，真实模型矩阵未执行；当前不能宣称 Spec 验收通过。以下记录返工前证据，修复后由新的独立验收 Agent 核对。

## Spec Coverage

| 范围 | 已有证据与限制 |
| --- | --- |
| W01～W04 | 标题创建、正文与材料保存、刷新、进展新增／更正／删除、日期独立修改的 Chromium 主链已通过；服务端定向用例覆盖正文与进展分离、版本和历史快照。清单布局仍有下述问题。 |
| W05 | 已有早期进展搜索断言；尚缺正文、进展、材料超过一页后的无遗漏／无重复证据。 |
| W06 | 非法节点／链接／块修改、附件及语音组合限制、绑定失败回滚有定向证据；全量回归失败仍须分类处理。 |
| W07 | DOM 用例验证进展响应丢失后相同 payload/key 重试，服务端验证幂等重放。正文失败用例只有空 files 和单次提交，尚不能证明带材料正文失败后的完整重试。 |
| W08 | Chromium 并发正文保存返回 409、保留草稿和显式恢复流程已通过；属性冲突恢复有 DOM 断言。 |
| W09 | 聊天文件复制、删除源聊天后下载／文档读取／沙盒字节有确定性证据；生成成果回存待 A08。 |
| W10 | 移除当前材料后拒绝访问、授权历史仍可读取已有证据；复制材料后删除账号、删除工作与报告持有情况下的清理仍需定向证据。 |
| W11～W12 | 迁移保留旧日期／状态及新进展期间事实有定向证据；混合新旧写入遗漏报告事实，见问题 1。报告提交后再修改工作所保留的来源快照需完成验证。 |
| W13 | 同公司其他员工／跨公司拒绝、管理员读取及禁止写他人工作有确定性证据；旧文档工具未继承受限工作材料权限，见问题 2。 |
| W14 | 已检查桌面及 390px 手机截图；主要入口可见，无明显横向溢出，清单框与文字分离。深色、长文、多图及键盘边界不能由现有两张截图推定通过。 |
| A01～A24 | 真实多轮评测尚未执行。不能用直接工具测试代替。A21 还存在不符合未提交报告行为的断言，见问题 3。 |
| 非目标与结构 | 未发现新增子任务、依赖、甘特、自定义字段或工作专属会话。公共媒体能力从 assistant 提取供 work 复用，符合既定目录方案。 |

## Tests

复用协调与实施 Agent 已执行的结果；独立验收未重复启动服务测试、真实模型或用户实际服务。

- 服务端定向：新增工作记录／材料／动作 32 项通过；动作／工作历史／变更计划 21 项通过。完整日志包含后续修改，不能只用此前定向通过代表最终版本。
- 服务端全量：[server-tests.log](../../artifacts/spec047/server-tests.log) 为 **933 通过、9 失败、7 跳过**。失败涉及架构依赖、旧共享材料、会话压缩、公司流程、报告事实、迁移旧假设及工作工具概览；根因由返工 Agent 分类，未全部归为产品缺陷或环境问题。
- Web：协调 Agent 报告全量 541 项中 540 通过、1 项上传人设 fixture 失败；修复后相关 10 项通过。`typecheck:web`、`build:web` 已通过。
- Chromium 主链：[请求证据](../../artifacts/spec047/browser-dialog-fix/business-work-W01-W04-W14--1a938-s-and-latest-chat-reference-chromium/evidence.json) 无浏览器错误，涵盖桌面与手机进展操作。
- Chromium 并发：[请求证据](../../artifacts/spec047/browser/business-work-W08-concurre-dd2f0-d-exposes-explicit-recovery-chromium/evidence.json) 记录预期 409 与恢复流程。
- 真实模型 A01～A24：未执行。CI：未查询；未提交、推送或部署。

## Issues

### 1. P1：混合新旧进展写入会遗漏报告事实

`apps/server/app/modules/reports/sources.py` 的 `report_inputs` 只接纳修订内容带 `_updateId` 的进展，再按整个 `work_id` 排除旧来源。`apps/server/app/modules/work/service.py` 的旧 `Progress`／建议确认／纯 summary 写入会创建 `WorkUpdate`，却不写对应元数据。

复现：同一期间先用 `/updates` 保存进展 A，再用旧 `/progress` 或既存待确认建议保存进展 B；报告输入只留下 A。多个迁移导入条目仅更正其中一个时，其他未更正条目也会被整项工作排除。修复应统一条目快照来源、按条目去重，保留未修改条目，同时避免已更正／删除文本复活。

### 2. P1：旧文档读取工具丢失工作材料的来源限制

`apps/server/app/modules/attachments/documents.py` 的 `agent_attachment` 在工作材料分支调用 `work_for_material` 后直接返回，没有调用 `require_agent_work` 或向 job 继承 work 的访问范围。

复现：管理员在新的普通会话中通过 `find_documents`／`read_document` 读取本人保存、但 `access.team=true` 的工作文档；job 仍为普通访问范围。最终消息直接使用 `live.access`，成果和新工作也从 job/message 继承范围，因此派生内容失去团队来源限制，后续撤销角色／权限时可能仍按普通自有内容保留访问。应与 `read_work_material`、沙盒材料读取复用相同的来源授权与继承规则，并验证派生内容不能解除原限制。

### 3. P2：A21 将正确的未提交报告判为失败

`tests/server/work_record_eval_assertions.py` 要求第一轮 `reportRevisions` 非空，但 A21 两轮都明确不要提交；`ReportRevision` 仅由 `submit_report` 创建。应核对生成时 `sourceIds` 所引用的工作修订快照保持不变；另用明确提交的确定性流程验证 W12，不得为满足断言擅自提交报告。

### 4. P2：正文定点修改确认卡未展示被修改的原块

`apps/server/app/modules/operations/targets.py` 对 `bodyEdits` 只取 `target.content.get('bodyEdits')`，得不到原块。`apps/web/src/features/assistant/utils/work-action-preview.ts` 因此只显示“删除指定内容”或修改后的文字。谨慎模式下用户无法核对被删／替换的具体段落。预览应按已验证的 blockId 解析原块，展示明确的前后内容。

### 5. P2：桌面与手机清单框脱离对应文字

[桌面截图](../../artifacts/spec047/browser-dialog-fix/business-work-W01-W04-W14--1a938-s-and-latest-chat-reference-chromium/body-and-materials.png) 与 [手机截图](../../artifacts/spec047/browser-dialog-fix/business-work-W01-W04-W14--1a938-s-and-latest-chat-reference-chromium/mobile-progress.png) 中勾选框居中显示在文字上一行，无法自然辨认对应清单项。`WorkContent.module.css` 的 taskItem 选择器应核对实际 Tiptap node view DOM，保证框与文本相邻对齐；不能仅凭 E2E 的保存成功断言认定视觉通过。

## Regression Risks

- 旧工作建议和新进展混用属于实际兼容路径，报告既不能漏事实，也不能重新引入已删除条目。
- 文件读取的授权检查与来源范围继承是两项不同约束；当前可读不意味着派生内容可以解除原限制。
- 完整回归中的 9 个失败须保留原证据并按根因修复，不能用重跑到绿代替处理。

## Required Rework

1. 修复问题 1、2，并完成混合新旧进展、部分更正导入进展及受限材料派生内容的定向断言。
2. 修复 A21 的测试假设、定点正文确认预览及清单布局。
3. 完成现有失败的必要定向回归；补足 W05、W07、W10、W12 的具体证据缺口，不重复已通过且未变更的检查。
4. 串行执行 A01～A24，按实际结果记录 PASS／FAIL／BLOCKED 与模型、工具轨迹和持久结果；修复后由新的独立 Agent 再验收。

## 恢复阶段返工前问题

后续独立验收再次 FAIL，原真实失败保留在 `artifacts/spec047/agent/recovery-fixed.jsonl`：

- P2：谨慎模式的待确认步骤被取消后，新消息明确续接仍直接返回旧 cancelled 回执；taskId／taskItemKey 继续占位，尚未写入的事项无法完成。
- P2：初次版本检查通过，但授权模型运行期间人工更新工作；最终 perform 的 409 被内层转为 conflict，未设置 refresh_work_versions，后续节点仍被旧版本检查阻断，不能强制重读。
- P2：A18 重试只保留一条进展、答复也已提供建议，但重放参数带自身成功后的 expectedRevision 时返回 conflict，工具结果和 taskOutcome.remaining 遗留冲突，最终显示 partial。
- A19 随后已完成三步业务，但收尾核对误将材料 ID、持久副本 ID 与源附件 ID 视为应相同，并因正文未变否认独立进展；答复修复最终触发模型输出限制，不能将业务写入成功等同于完整任务完成。

## 修复与关闭证据

- 取消待确认卡仅在新的明确续接请求经过独立授权、当前权限和版本检查后释放旧执行槽位；旧卡保持 cancelled，新卡重新确认。授权期间并发修改在第二事务锁定目标并检查版本，未写入的尝试进入原有持久重读流程。
- 相同成功操作仅允许 expectedRevision 前移到自身成功版本，原始完整 digest 仍核对内容、来源及依赖；不同参数继续冲突。恢复组先 43 通过、1 项测试读取未生成 taskOutcome 的夹具错误，改用实际 derive 后该项通过，见 `finish-recovery-tests.log`、`finish-recovery-replay-test.log`。
- 新增共享的服务端回执证据按保存版本提供进展及材料映射，保留鉴权、失败状态和未知内容边界；未调整 token／超时限制。相关组 79 通过、1 项旧报告单来源断言失败，改为核对真实三份语义来源后该项通过，见 `server-rework-work-reply-evidence.log`、`server-rework-report-snapshot-compat.log`。
- 最后 A18、A19 在 `agent/receipt-fixed.jsonl` 均 PASS：A18 实际接受手动重试，单条进展、单次工作版本及原回执保留；A19 原正文回执不重建，文件与进展各保存一次，恢复任务 completed，最终答复核对通过。日志路径均相对 `artifacts/spec047/`。
