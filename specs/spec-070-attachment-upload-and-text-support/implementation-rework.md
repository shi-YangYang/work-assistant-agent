# Implementation Report — 定向返工

## Summary

已修复独立验收中的三项问题，等待新的独立验收。没有提交、推送、部署、迁移日常数据库或修改用户数据；保留原有未提交实现。

- 24 小时退役在独立事务中按公司→附件顺序加锁，再用新的查询复核工作材料实际引用及来源引用。初始候选仍排除已知正式引用，避免每分钟逐条锁住旧材料。先提交删除标记，再执行原有物理清理／失败重试。
- 身份暂停时移除 `directSend` 临时录音并释放本地 URL，保留正文和普通附件；不自动上传、重发或清理结果不明的服务端 ID。
- 消息附件校验仅对当前公司、当前所有者的已删除附件返回 `404 / attachment_unavailable / 附件已不可用，请移除后重新添加。`。其他归属、未知 ID 和缺失会话继续泛化 404。已有请求层及错误组件能够直接呈现恢复指引，不需要修改全局错误映射。

## Files Changed

- `apps/server/app/modules/attachments/lifecycle.py`：共享正式引用查询、过期退役锁与复核。
- `apps/server/app/tasks/maintenance/maintenance.py`：过期退役独立事务，避免其他附件写入 autoflush 后反向取公司锁。
- `apps/server/app/modules/messages/commands.py`：在既有幂等公司／成员锁之后校验附件归属与 tombstone，返回精确恢复错误。
- `apps/web/src/features/assistant/lib/composer-drafts.ts`：暂停释放直发录音。
- `tests/server/modules/materials/test_attachment_upload_lifecycle.py`：实际 maintenance 与工作绑定确定性竞争、真实孤儿回收、过期反馈、权限隔离、失败后替换及成功回执幂等。
- `tests/web/assistant/session-drafts.test.ts`：上传／发送中断后的同账号恢复、旧 writer 隔离、本地 URL 释放、普通附件可继续发送且不重传。
- `tests/web/dom/assistant/attachment-send-errors.test.tsx`：真实请求层→发送 Hook→ErrorNotice 的失效指引、普通 404、503 未知结果快照保护。

## Important Decisions

没有新增产品或架构决策；按既定归属、锁顺序、幂等和未知结果保护修复。专用错误只表示本人的附件不可用，不将所有 404 解释为过期。

## Tests

按 S3 中本次权限、删除持久化和并发风险进行定向验证，没有全项目测试或构建。

格式化编辑：

```sh
node_modules/.bin/prettier --write apps/web/src/features/assistant/lib/composer-drafts.ts tests/web/assistant/session-drafts.test.ts tests/web/dom/assistant/attachment-send-errors.test.tsx
```

Web：

```sh
npm run test:web -- tests/web/assistant/session-drafts.test.ts tests/web/dom/assistant/attachment-send-errors.test.tsx
```

结果：2 个文件，10 项全部通过。之后未修改这些文件，没有重复执行。

后端通过下列隔离 runner 执行，没有输出连接密钥：

```sh
PYTHONPATH=apps/server .venv-server/bin/python - <<'PY'
import os
import subprocess
from app.core.config import Settings
from sqlalchemy.engine import make_url
url = make_url(Settings().database_url).set(database='paa_company_test')
assert url.database == 'paa_company_test'
env = dict(os.environ, DATABASE_TEST_URL=url.render_as_string(hide_password=False))
raise SystemExit(subprocess.call([
    '.venv-server/bin/python', '-m', 'pytest', '-q',
    'tests/server/modules/materials/test_attachment_upload_lifecycle.py',
    '-k', 'draft_delete or sent_attachment or unavailable_attachment or maintenance_rechecks or binding_and_delete',
], env=env))
PY
```

结果：`8 passed, 3 deselected in 2.58s`。

首轮通过后的 diff 审查发现锁事务和候选范围可带来具体反序／开销风险，随后将过期退役单独提交、恢复初始引用排除。只将上述 runner 的 `-k` 改为 `draft_delete or sent_attachment or maintenance_rechecks` 重跑直接受影响检查：`3 passed, 8 deselected in 1.75s`。这三项属于前述八项，不重复计为新增覆盖。

竞争用例持有真实绑定公司锁，等待 maintenance 读取候选并开始获取同一公司锁，再执行真实 `bind_materials` 并提交；最后断言来源和副本原始字节均保留，另一真实孤儿已退役且文件已清理。所有测试数据和断言限定本 fixture，没有删除测试库历史遗留行，没有模型调用。

已检查本次 diff；第一次 `git diff --check` 通过，随后只审查实际新增的回收调整及本报告，没有重复检查未变化文件。

## Known Limitations

- 原报告中 Web 全量 typecheck 的六处既有 `message-voice.test.tsx` 隐式 `this` 错误仍未处理；本次未重复全量 typecheck，不声明其通过。
- 没有重复已通过且未受影响的浏览器矩阵、解析对照、真实沙盒或真实设备测试。
- 本报告为实施记录，不是最终验收；原 `acceptance.md` 的 FAIL 留作返工依据，由新的验收 Agent 检查修复。

## Remaining Questions

无待用户决策事项。等待新的独立验收。
