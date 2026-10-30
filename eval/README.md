# 本地 Agent 评测

这里用于回答三个问题：Agent 有没有完成请求，有没有越权或多做操作，修改后是否在质量相当的前提下更快。

评测在本地手动运行，**CI 不调用模型做 eval**。普通单元、接口和业务流程测试仍在 `tests/`；格式与静态检查继续覆盖两个目录的源码。

## 先看用例

完成[公司开发环境安装](../docs/setup.md#公司-web)后，从仓库根目录运行。Windows 将解释器路径换为 `.venv-server\Scripts\python.exe`。

```sh
.venv-server/bin/python eval/agent-evaluation.py list --suite core
.venv-server/bin/python eval/agent-evaluation.py check
```

`list` 列出用例，`check` 检查评测器本身；两者均不调用模型。完整套件定义在 [suites.json](agent_eval/suites.json)，用例入口在 [catalog.json](agent_eval/catalog.json)。

## 怎样读结果

| 层次         | 能说明什么                                   | 不能代替什么               |
| ------------ | -------------------------------------------- | -------------------------- |
| 程序断言     | 对象、权限、保存次数、文件和状态是否符合要求 | 自由文本是否准确、完整     |
| 离线模型初评 | 根据已保存输入、回复和事实判断语义质量       | 人工复核；它也可能判断错误 |
| 人工复核     | 逐项查看原请求、回复与证据后作出结论         | 未执行或缺证据的测试       |

`PASS` 表示该层要求通过，`FAIL` 表示已有明确失败，`INCOMPLETE` 表示执行、证据或复核尚不完整。框架验收通过，不等于全部业务用例通过。人工复核尚未录入时，程序和初评均通过也可能仍为 `INCOMPLETE`。

每次试验有固定编号（slot），多轮对话属于同一试验。报告保留失败和超时，不只计算成功样本。先看质量与未完成原因，再看耗时；单次更快不能证明普遍提速。

## 运行一次真实评测

### 1. 准备隔离环境

使用 `scripts/company/web-acceptance/environment.py prepare --suite spec082 --purpose web --output <目录>/metadata.json` 创建带归属标记的测试环境，再用 `eval/web/agent-audit/configure.py --metadata <环境文件> --source-user <本地账号>` 只读复制模型配置。

通过 `eval/web/agent-audit/launch.py --metadata <环境文件> --trace <调用记录> api` 和相同参数的 `worker` 分别启动隔离服务。启动时设置 `PAA_EVAL_FULL_INPUT=1`，仅在合成评测环境记录真实模型输入；浏览器评测的前端必须指向同一隔离 API。

共用环境管理脚本仍在 `scripts/company/web-acceptance/`。不要用日常或生产数据库代替隔离环境，也不要把临时账号和密钥加入 Git。

### 2. 冻结计划

本地配置 JSON 包含以下字段，不含密钥：

| 字段             | 内容                                                                       |
| ---------------- | -------------------------------------------------------------------------- |
| `models`         | 每项含 `id`、`provider`、`model`、`parameters`、实际 `effort`（low／high） |
| `environment`    | 隔离 `schema` 与环境 `profile`                                             |
| `timeoutSeconds` | 本次超时，不超过既有 1860 秒边界                                           |
| `comparison`     | 配对比较时声明 `order`（AB／BA）及 `sampleSize`，样本数须等于计划槽位数    |

```text
.venv-server/bin/python eval/agent-evaluation.py plan --suite representative-http --config <配置.json> --output <计划.json>
.venv-server/bin/python eval/agent-evaluation.py run --plan <计划.json> --metadata <环境文件> --output <新的运行目录>
```

`plan` 不调用模型；`run` 才执行真实业务流程。开始后不可覆盖原结果。重用目录只补未开始的槽位，源码改变后必须生成新计划。`--slots s0001,s0002` 可限定必要的后续处理，但不会从总数中删除未执行项。

### 3. 评分并查看实际回复

```text
.venv-server/bin/python eval/agent-evaluation.py grade --run <运行目录> --source-user <本地账号>
.venv-server/bin/python eval/agent-evaluation.py report --run <运行目录>
```

`grade` 默认调用真实离线评分模型，不会重跑业务。只做程序断言时加 `--mode deterministic`，语义项继续待判。需要修正评分证据时，用 `--slots` 追加受影响槽位的新评分，旧评分保留。

`report` 输出 JSON 与 HTML，并打印文件位置。用浏览器打开 HTML，从对应试验查看实际回复、工具轨迹、截图和文件。记录集中在 `trials/`，追加的初评在 `grades/`，人工复核在 `reviews/`。报告展示的是保存的证据，不会再次向 Agent 提问。

### 4. 人工复核

逐项对照用户原请求和实际回复，再检查业务保存、来源和文件。不要只看模型初评的 PASS。

复核 JSON 每条包含 `slot`、复核者 `actor`、`actorType`、复核说明 `provenance`、对应的 `evidenceSha256`、最新 `gradeSha256` 和 `requirements`。每项要求填写 `id`、`status`（PASS／FAIL／INCOMPLETE）及所依据的 `evidence`；这些哈希使用评测器的规范化摘要，不能混用文件字节哈希。

```text
.venv-server/bin/python eval/agent-evaluation.py review --run <运行目录> --decisions <复核.json>
```

真实人工复核才使用 `actorType=human`。Agent 的代码检查或复核记录为 `agent`，不满足人工门槛。录入后重新生成报告即可查看汇总，无需重跑模型。

### 5. 收尾

先停止本次启动的 API、worker 和 Web 进程，再预览清理范围：

```text
.venv-server/bin/python eval/agent-evaluation.py cleanup --metadata <环境文件> --runs <运行目录>
```

确认范围后加 `--apply`，删除已验证归属的测试 schema、私有环境和各试验凭证。该命令不会停止共享 PostgreSQL、Redis 或沙盒容器。保留回复、失败记录和脱敏证据。

## 专项检查与对照

- `diagnose --output <新目录>`：运行固定输入的契约与界面诊断，结果不冒充真实模型表现。
- `plan --suite contracts ...`：选择对象权限、跨公司隔离、取消等契约用例，不调用业务模型。
- `calibrate --source-user <账号> --ids equivalent,added-condition,absent-evidence --output <新目录>`：检查真实离线评分模型；`--replay <旧目录>` 只重放已有评分。
- `compare --baseline <目录> --candidate <目录>`：比较相同任务、材料、模型配置、初态、评分版本和环境的结果。共享 worker 上重叠运行的样本不能当作串行提速对照。

旧专项参数 `--suite business/persona/task-consistency/work-records --source-user ...` 仍由统一入口接收。使用历史用例前应先核对其业务约定是否仍有效。

## 文件放在哪里

```text
eval/
├── agent-evaluation.py    统一命令入口
├── agent_eval/           计划、评分、复核、报告与自检
│   └── cases/            固定测试集与合成材料
├── support/              评测专用夹具和评分辅助
├── benchmarks/           速度、权限、记忆、沙盒及文档专项
└── web/                  真实 HTTP、浏览器流程与调用采集
```

`eval/` 和 `tests/` 的源码、合成测试集提交 Git；运行产物写入被忽略的 `artifacts/agent-eval/`。测试凭证与真实用户资料不提交。

旧入口 `scripts/benchmarks/agent-evaluation.py` 已移至本目录。历史 Spec、`inventory.json` 来源快照及冻结产物保留当时路径和哈希；查旧记录时应使用对应 Git 版本，新运行则使用当前入口和新计划。
