# 移除额外交付负担验收

## Result

PASS。仅验收取消在线字数协议、普通回答表单及旧 checkpoint 兼容返工；不代表整个响应速度改造的性能结论。

## 已确认

- 当前主提示只保留固定空预览标记，不再要求长度引用、计数范围、重复正文或普通回答的任务表单。长度类型仅供历史数据读取，线上计数与字数改写路径已删除。
- 新正文由服务端结合真实回执组装。旧 `finish_task` 保留读取；一次格式恢复只提供正文能力，禁止工具及混合写入，恢复内容不提前流出。
- 实际工具额度拒绝、显式未完成项与既有业务校验仍在。本次文件未调整模型配置、思考强度、输出上限或超时。

## 已修复问题

**P2：旧引用修复 checkpoint 恢复丢失未完成状态。** 原 `read_delivery` 只识别 `delivery-repair:<job>`，旧 `delivery-references:<job>` 恢复为普通正文时，“第二份材料不可用”误变成 `completed`、`remaining=[]`。独立最小复现曾得到业务断言失败。

返工已复用 middleware 的 `repairing_delivery`，统一识别两种标记；只继承通过 `TaskInterpretation` 校验的非完成 `state/remaining`，不继承持续指令、回执或授权声明。新独立静态审查确认三种历史顺序均由同一路径处理，未重新引入模型表单、字数门槛或业务重放。

## Tests

- 复用实施结果：相关四文件首次 67 通过、1 失败；修正测试替身对新正文恢复的假设后，受影响分支及新增边界 19 通过。组间有重叠，不相加。拒绝恶意重复表单的断言保留。
- 独立最小复现：`artifacts/spec055/remove-burdens/test_legacy_reference_checkpoint.py` 使用固定 checkpoint 与真实任务保存链路，0 模型调用，1 失败，2.50 秒。证据：同目录 `acceptance-legacy-references-v2.log`。首次收集因产物目录缺少测试模块搜索路径失败，修正运行夹具后得到上述业务断言失败；两次隔离 schema 均由 runner 清理。
- 返工定向检查：`test_legacy_repair_checkpoint_preserves_only_unfinished_state` 的 `repair`、`references`、`repair → references` 三种参数均通过，3 passed、42 deselected，2.83 秒；见 `artifacts/spec055/remove-burdens/legacy-state-rework.log`。断言未完成项保留、指令不继承、0 模型调用、无业务回执和工具重放。本次独立验收复用结果，未重复运行。
- 原实施哈希清单中仅返工两文件变化，其余 10 文件一致。最终 SHA-256：`harness.py` 为 `b3f31030452021f8456194e57b559980a9ee164de56dc407c9f3b6d2cc4fb3d7`；`test_response_delivery.py` 为 `b66920ef8831e775e18e4347bca4dfddbe1099579bb1bb8d8a81a029e35e1f58`。实施前无独立快照，不能声称已还原本次精确全量 diff。
- 未调用真实模型、未做浏览器或性能复测，未操作用户日常数据。本次独立验收未启动服务、未创建测试资源；实施者已清理返工 schema `spec055_burdens_2a4ea5ac3842`，无本次遗留服务。未提交或推送。

## 限制

用户篇幅要求仍原样交给模型，但不再提供在线精确字数保证；离线不足样本不能改判通过。没有新的真实测速，不能据此宣称整体延迟已恢复到十几秒。本次移除范围无待返工项，Spec 055 整体性能目标仍未完成。
