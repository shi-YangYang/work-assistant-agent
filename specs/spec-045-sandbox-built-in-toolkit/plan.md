# 实施计划

## 对应 Spec

[沙盒内置工具与统一执行](spec.md)。按已确认方案实施。

## 涉及模块

- Agent 工具层：五个结构化工具，负责参数描述与轻量适配；`run_python` 保留为自定义代码入口。
- `modules/executions`：统一请求、输入授权、幂等、持久记录、取消及成果保存；不复制两套生命周期。
- 私有协议与沙盒控制服务：校验任务类型和大小，沿用原队列与受限容器。
- runner：Python 任务运行用户代码；内置任务通过固定注册表执行 `noria_tools`，不使用动态代码拼接。
- Agent 运行链：同步工具白名单、启用条件、节点标签、历史阅读与结果核对，避免只注册工具却无法正常收尾。

## 修改顺序

1. 定义结构化参数、互斥任务类型、结果结构及旧协议兼容规则。
2. 给执行记录增加可选请求快照，将现有执行生命周期收敛为共同入口，保留旧 Python 幂等计算和调用方式。
3. 实现四类内部工具及固定分派器，更新控制协议、runner 与镜像。
4. 接入五个模型工具，统一可用性、重试、节点与执行证据处理；补文档。
5. 验证新旧执行、迁移、真实产物与少量 Agent 流程；实施 Agent 交付后，由新的独立验收 Agent 检查。

## 数据流

```text
Agent
├─ 结构化工具 → 有类型的参数 → 内置任务
└─ run_python → Python 代码 → 代码任务
                 ↓
统一执行服务：输入授权、幂等、记录
                 ↓
原沙盒控制服务：队列、资源与取消
                 ↓
同类隔离容器：固定工具分派 / Python 执行
                 ↓
结构化结果、标准输出、错误、文件
                 ↓
校验 → 保存回执及私有成果 → 返回实际结果
```

不新增文件交付路径或业务写入入口。

## 接口变化

### 模型入口

| 接口 | 职责 |
| --- | --- |
| `inspect_table` | 读取授权 CSV/XLSX，返回结构、质量摘要和有限样本 |
| `export_table` | 将内联数据或授权表格写成 CSV/XLSX，不自行汇总或清洗 |
| `create_chart` | 根据内联数据或授权表格中的指定字段生成 PNG |
| `create_document` | 将结构化内容块写成 DOCX/PDF |
| `create_slides` | 将结构化页面写成 PPTX |
| `run_python` | 保持现有参数，处理自定义计算、实验和复杂文件操作 |

创建 PDF 的模型参数示例：

```json
{
  "format": "pdf",
  "filename": "实施计划.pdf",
  "title": "项目实施计划",
  "blocks": [
    {"type": "heading", "text": "第一阶段"},
    {"type": "paragraph", "text": "完成需求确认和原型设计。"}
  ]
}
```

文件参数沿用附件／成果引用，由服务端解析成仅本次任务可用的输入标识。修改旧成果继续使用 `deliverable_id`、`expected_revision` 和现有步骤机制；大表通过文件传递，不让模型把整表复制进参数。

### 私有执行协议

- 旧请求 `{id, owner, code, inputs}` 继续有效。
- 新请求使用 `{id, owner, task: {kind: "builtin", name, version, arguments}, inputs}`；`code` 与 `task` 恰好提供一个。
- `name` 必须匹配固定注册表，版本由服务端适配器设置；拒绝未知类型、未知字段和超限内容。内置参数不允许 Python、Shell 或可执行表达式。
- 内置任务由入口启动镜像内的固定分派器，参数通过 JSON 传递。分派器与自由 Python 使用相同的隔离和资源限制，均不在 API／控制进程运行文件处理库。
- 结果沿用现有状态、标准输出、错误、文件字段，增加有大小限制的结构化 `data` 和 `warnings`。检查表格的样本明确标记截断；超过上限不能输出被截成无效 JSON 的“成功结果”。
- 规范化任务类型、工具版本、参数和输入参与幂等。旧 Python 请求维持已有身份算法和控制服务指纹，新增空字段不能使已有回执失配或导致再次执行。

### 持久化与证据

- `SandboxExecution` 新增可空的 `request` JSONB，用于内置任务的原始结构化快照。旧 Python 记录仍使用 `code`，内置任务的 `code` 留空；禁止把 JSON 填入代码字段冒充代码。
- `read_execution` 返回明确任务类型，按现有授权读取请求及实际结果，支持有界阅读。旧记录无需回填；已执行的旧参数不套用新版默认值。
- 统一识别两类执行回执，更新核对说明和历史上下文；成功文件不要求另有公司业务回执。
- 同一任务重复调用恢复回执；不同参数不能误复用结果，旧成果修改仍检查版本冲突和来源。

## 测试计划

实施涉及数据库扩展、执行协议和镜像，按 S3 对相关子系统验证，不默认重跑整个项目。

| 层次 | 验证内容 |
| --- | --- |
| 工具库 | 固定表格数值与类型；空数据、缺列、前导零、公式文本；中文图表；文档内容、分页与可编辑 PPT；错误不留下成功产物 |
| 协议与迁移 | 新旧请求兼容、互斥类型、未知工具／版本、超限参数与代码注入文本；新增字段迁移、旧记录阅读、请求幂等与参数变化 |
| 现有边界 | 输入授权、执行回执、成果版本、取消及失败发布行为；关闭沙盒同时禁用新旧执行工具 |
| 真实镜像 | 固定分派器与 Python 两类执行、五个结构化工具结果、文件下载与解析；路径越界、超限和跨用户隔离的定向场景 |
| 渲染 | 检查中文 PDF、图表及长内容 DOCX/PPTX 样本；渲染用于验收，不宣称所有产物已自动视觉审查 |
| 真实 Agent | 固定 6 个流程：表格检查并导出、中文图表、长文档双格式、简单 PPT、继续修改已有成果、自定义 Python 计算后交给内置工具；另确认普通问答不强制调用沙盒 |

工具库测试在具备 runner 依赖的隔离环境执行，不把重依赖装入公司 API 环境。预计命令：

```sh
PYTHONPATH=apps/sandbox/runner python -m unittest discover -s tests/sandbox/toolkit -p 'test_*.py'
PYTHONPATH=apps/sandbox python -m unittest discover -s tests/sandbox -p 'test_protocol.py'
python -m pytest tests/server/test_sandbox_execution.py tests/server/test_execution_evidence.py tests/server/test_builtin_execution.py tests/server/test_builtin_execution_migration.py
```

真实镜像检查复用 `tests/sandbox/real_execution.py` 的独立服务、显式测试开关和清理机制。不得对用户日常沙盒或生产环境执行破坏性测试。

常规生成流程须观察到直接调用结构化工具；出现改写整段 Python 或无法发现工具时记录原因，不能只看最终文件成功。记录首次结果、具体修正与实际复测，不反复运行同一模型直到通过。只在发现直接相关问题后扩大验证；产物内容正确性不能只用“文件存在”断言。

## 风险

- 功能膨胀：限制首期类型与样式选项；特殊任务继续使用现有库。
- 新入口遗漏运行链：统一执行工具名称集合，核对注册、可用性、重试、节点和证据读取，避免散落判断只识别 `run_python`。
- 统计口径被工具隐式改变：不自动清洗、聚合或推断业务规则，编码和类型可显式指定。
- 文件排版受长度和字体影响：使用固定中文字体和有限布局，超出能力明确失败或警告。
- 重依赖影响启动：按需导入；沿用现有资源限制，不增加常驻渲染进程。
- 工具说明与镜像不一致：兼容版本先部署沙盒，再更新业务服务；未知协议报明确兼容错误，不伪装网络失败。

## 迁移策略

新增可空请求字段，无历史数据改写。先更新兼容旧请求的沙盒控制服务和 runner，再执行加列迁移、更新业务服务。迁移编号接续实施时的 Alembic head。

本地沿用 `npm run sandbox:setup`；构建指纹已递归覆盖 `apps/sandbox`，无需新增环境变量或修改该机制。

回滚优先停用内置入口并保留可读结构化回执的新协议版本；不直接删除已有请求数据或降级到只理解 Python 记录的业务版本。紧急退回旧版本前，先结束或取消在途内置任务，并明确旧版不能完整阅读内置请求的限制；原 Python 记录和成果文件仍保留。

## 预计涉及文件

```text
apps/sandbox/
├── app/
│   ├── main.py                          # 修改：兼容新增参数的请求大小上限
│   ├── schemas.py                       # 修改：兼容代码请求与结构化请求
│   ├── runtime.py                       # 修改：任务传递、有界结构化结果
│   └── service.py                       # 修改：统一请求摘要与结果留存
└── runner/
    ├── entrypoint.py                    # 修改：两类任务的固定入口
    ├── builtin.py                       # 新增：白名单分派与参数处理
    └── noria_tools/                     # 新增：执行容器内工具库
        ├── __init__.py                  # 公开接口、版本与按需导入
        ├── contracts.py                 # runner 内的输入校验
        ├── common/
        │   ├── paths.py                 # 输入、输出、临时文件边界
        │   ├── fonts.py                 # 中文字体与基本样式
        │   └── results.py               # 导出结果和警告
        ├── tables/
        │   ├── io.py                    # CSV/XLSX 读取和导出
        │   └── inspect.py               # 数据结构与质量摘要
        ├── charts/render.py             # 中文柱状图、折线图
        ├── documents/
        │   ├── blocks.py                # 文档内容结构与校验
        │   ├── word.py                  # DOCX 生成
        │   └── pdf.py                   # PDF 分页与字体嵌入
        └── slides/presentation.py       # PPTX 生成与内容容量处理
apps/server/app/
├── agent/
│   ├── tools/
│   │   ├── execution.py                 # 修改：Python 与历史阅读说明
│   │   ├── registry.py                  # 修改：注册结构化工具
│   │   └── sandbox/                     # 新增：轻量模型工具适配
│   │       ├── __init__.py              # 导出工具列表
│   │       ├── common.py                # 参数归一化、调用与错误反馈
│   │       ├── tables.py                # 检查、导出表格
│   │       ├── charts.py                # 生成图表
│   │       ├── documents.py             # 生成文档
│   │       └── slides.py                # 生成演示文稿
│   ├── prompts/
│   │   ├── policies.py                  # 修改：工具选择、白名单、能力说明
│   │   └── evidence.py                  # 修改：两类实际执行结果的使用规则
│   ├── harness.py                       # 修改：统一执行能力启用条件
│   ├── runtime/
│   │   ├── middleware.py                # 修改：新旧工具调用边界
│   │   └── tool_nodes.py                # 修改：节点名称与回执恢复
│   ├── context/history.py               # 修改：代码／结构化执行历史
│   └── completion/reply_review.py        # 修改：两类真实执行证据
├── modules/executions/
│   ├── service.py                       # 修改：共同执行生命周期
│   ├── requests.py                      # 新增：任务归一化与幂等身份
│   ├── models.py                        # 修改：内置请求快照
│   ├── queries.py                       # 修改：新旧执行记录阅读
│   └── builtin/                         # 新增：业务侧轻量契约
│       ├── schemas.py                   # 有类型的参数、文件引用与统一工具名称
│       └── results.py                   # 有界结构化结果处理
├── integrations/sandbox/client.py       # 修改：协议兼容错误分类
└── migrations/versions/
    └── 0023_builtin_execution.py         # 新增：可空请求字段
deploy/company/
└── Dockerfile.sandbox                   # 修改：runner 工具库与固定分派器
tests/sandbox/
├── toolkit/                             # 新增：公共边界与四类工具测试
│   ├── support.py                       # 独立临时工作目录
│   ├── test_common.py
│   ├── test_tables.py
│   ├── test_charts.py
│   ├── test_documents.py
│   └── test_slides.py
├── test_protocol.py                     # 修改：新旧协议与边界
└── real_execution.py                    # 修改：实际镜像与工具产物验证
tests/server/
├── test_company.py                      # 修改：同步沙盒关闭时的工具集合
├── test_sandbox_execution.py             # 沿用：共享生命周期回归
├── test_execution_evidence.py            # 沿用：历史与真实结果
├── test_sandbox_runtime.py               # 沿用：真实容器与数据库恢复
├── test_builtin_execution.py             # 新增：工具调用、可用性与幂等
├── test_execution_history.py             # 新增：有界历史错误、成果引用与撤销权限
└── test_builtin_execution_migration.py   # 新增：迁移与历史兼容
docs/
├── architecture.md                      # 修改：工具库与执行边界
└── setup.md                             # 修改：接口示例与镜像更新
specs/
├── README.md                            # 修改：Spec 索引
└── spec-045-sandbox-built-in-toolkit/
    ├── spec.md                          # 新增：需求与验收标准
    ├── plan.md                          # 新增：实施与验证方案
    ├── implementation.md                # 新增：实施结果与验证限制
    └── acceptance.md                    # 新增：独立验收
```

不移动现有目录，不改 Web／Electron 界面及公司工作／报告 API；仅扩展私有执行协议与执行记录。
