# 本地 Agent 评测

这里存放 Agent 的模型能力评测、测试集、评分器和真实流程运行器。验证工具、权限、接口和业务逻辑的普通自动化测试仍在 `tests/`；共用的隔离环境管理仍在 `scripts/company/web-acceptance/`。

```text
eval/
├── agent-evaluation.py    # 统一入口，兼容原有专项参数
├── agent_eval/           # 计划、执行、评分、复核、报告与自检
│   └── cases/            # 固定测试集与合成材料
├── support/              # 原 tests/server/_support 中的评测专用夹具和评分辅助
├── benchmarks/           # 速度、权限、记忆、沙盒、文档及工作内容专项
└── web/                  # 真实 HTTP、浏览器流程与采集器
    └── agent-audit/      # 冻结套件、隔离进程启动和调用证据
```

从项目根目录运行：

```sh
.venv-server/bin/python eval/agent-evaluation.py list --suite core
.venv-server/bin/python eval/agent-evaluation.py check
```

这两个命令不调用模型。真实执行和离线模型评分须显式运行 `run`、`grade` 等命令，完整步骤见[安装说明](../docs/setup.md#本地-agent-评测手动)。CI 不运行评测；格式和静态检查继续覆盖这里的源码。

`eval/` 与 `tests/` 的源码、合成测试集正常提交 Git。运行结果、下载、截图和脱敏调用记录仍写入被忽略的 `artifacts/agent-eval/`，凭证与真实用户资料不提交。

原入口 `scripts/benchmarks/agent-evaluation.py` 改为 `eval/agent-evaluation.py`；原 `scripts/benchmarks/agent_eval/` 改为 `eval/agent_eval/`；专项脚本迁到 `eval/benchmarks/`；Agent 浏览器和 HTTP 脚本迁到 `eval/web/`。历史 Spec、`inventory.json` 中的来源快照及已经冻结的评测产物保留原始路径和哈希，不改写旧证据。迁移后的新执行必须重新生成计划；仍可读取旧报告。
