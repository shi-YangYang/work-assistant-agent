# AGENTS.md — 通用项目 Agent 说明与基础约束

本规范用于约束 AI Agent 在软件项目中的需求分析、项目初始化、规格设计、实施、验收、返工与交付行为。

本规范遵循 SDD（规格驱动开发）流程，并融合多 Agent 协作开发模式。

适用场景包括：

- 从空白目录开始的新项目；
- 已经存在业务代码和工程结构的旧项目；
- 单 Agent 开发环境；
- 支持协调 Agent / 实施 Agent / 验收 Agent 的多 Agent 开发环境。

本规范的核心目标不是强制所有项目采用完全相同的业务目录，而是建立统一、稳定、可追踪的 Agent 开发工作流。

---

## 验证与停止规则

验证范围必须与改动的风险和范围成正比。目标是达到“足够的验证”，而不是追求最大化确定性。

在开始验证前，先判断改动级别：

- **S0：极小改动**\
  文案、注释、样式微调、简单重命名、明显不影响逻辑的小配置修改。\
  默认只检查 diff，不运行测试、build、lint 或 typecheck。
- **S1：局部逻辑修改**\
  单个函数、单个组件、局部 bug 修复、明确隔离的行为修改。\
  默认最多运行一个最相关、范围最小的测试或检查；通过后立即停止。
- **S2：中等范围修改**\
  涉及多个相关模块、模块间交互、接口行为或共享逻辑。\
  运行相关模块或子系统的检查，不默认运行整个项目的完整测试套件。
- **S3：高风险修改**\
  涉及数据库 migration、schema、认证与权限、安全逻辑、公共 API、构建系统、发布流程、大范围重构或核心共享基础设施。\
  可以进行更全面的测试、构建和验证。

对于 S0 和 S1 修改：

- 不要仅仅为了覆盖实现而新增测试。
- 不要默认运行完整测试套件、完整 build、全量 lint 或全量 typecheck。
- 优先检查 diff；确有必要时，只运行与本次修改最直接相关的最小检查。
- 小型修改通常最多执行 0～2 个验证命令。
- 一旦相关检查通过，立即停止验证。

只有在以下情况之一成立时，才允许扩大验证范围：

- 修改跨越多个模块、包或子系统；
- 定向测试或检查失败；
- 修改涉及共享基础设施、schema、公共 API、构建配置、安全相关代码或持久化逻辑；
- 用户明确要求进行更全面的验证；
- 项目已有明确规则要求必须执行某项检查。

不要自行把 S0 或 S1 修改升级为 S2/S3 级别的验证。扩大验证范围必须有明确、具体的技术依据。

不要重复执行已经通过的检查，除非：

- 检查之后相关代码又发生了修改；
- 上一次结果不明确或存在明显的随机失败；
- 为了复现某个具体失败，需要再次运行。

以下理由不足以扩大或重复验证：

- “保险起见”
- “为了完整性”
- “为了更加彻底”
- “顺便确认一下”
- “可能还有问题”

不要为了测试而测试，不要为了提高主观信心而不断追加验证。

只完成用户明确要求的修改，不要自行扩大任务范围，不要顺手修复与当前任务无关的问题。

当以下条件同时满足时，立即停止工作：

1. 用户要求的修改已经完成；
2. diff 符合预期；
3. 与改动规模相称的必要检查已经通过；
4. 没有发现与本次修改直接相关的具体未解决问题。

满足以上条件后，不要继续探索代码库，不要追加测试，不要重复检查，不要进行“最后再确认一次”。

**核心原则：验证范围与改动规模成正比；已经通过的检查不得无理由重复执行；需求满足且必要验证通过后立即停止。**

---

## 0. 项目模式与核心概念

### 0.1 可选项目模式

默认配置：

```yaml
project_mode: AUTO       # AUTO | NEW | EXISTING
business_code_dir: AUTO  # AUTO 或用户明确指定
multi_agent: AUTO        # AUTO | true | false
```

说明：

- `AUTO`：由协调 Agent 根据当前仓库实际状态判断。
- `NEW`：明确按空白项目初始化流程执行。
- `EXISTING`：明确按已有项目接入流程执行。
- 用户显式配置优先于 Agent 自动判断。

当 `project_mode: AUTO` 时：

- 当前仓库没有有意义的业务代码、工程配置、依赖清单或既有工程结构 → 按空白项目处理；
- 当前仓库已经存在业务代码、工程配置、依赖、构建方式或稳定目录结构 → 按已有项目处理；
- 无法可靠判断时，为避免破坏既有项目，默认按已有项目处理。

---

### 0.2 项目结构（Project Structure）

项目结构负责：

> 项目本身如何组织。

包括但不限于：

- 业务代码；
- 前端；
- 后端；
- 应用模块；
- Packages；
- Tests；
- Docs；
- 配置文件；
- 构建脚本；
- 数据库；
- 部署文件；
- 项目自己的工程目录。

例如：

```text
src/
frontend/
backend/
apps/
packages/
docs/
tests/
```

项目结构根据项目类型、技术栈和已有工程状态决定。

---

### 0.3 Agent 结构（Agent Structure）

Agent 结构负责：

> Agent 如何理解、规划、实施、验收和持续维护这个项目。

Agent 结构是统一的 Agent 开发工作流基础设施。

标准 Agent 结构为：

```text
AGENTS.md

constitution/
├── mission.md
├── roadmap.md
└── tech-stack.md

specs/
├── README.md
└── _template/
    ├── spec.md
    ├── plan.md
    └── acceptance.md

.ai/
├── decisions/
├── workflows/
├── prompts/
└── rules/
```

这些目录属于本开发框架的固定结构。

Agent 可以在其基础上扩展，但未经用户明确授权，不得：

- 删除；
- 重命名；
- 移动；
- 合并；
- 使用其他目录替代；
- 改变目录原有职责；
- 重新建立一套与其职责重复的 Agent 治理体系。

核心原则：

> Agent 结构允许扩展，不允许擅自替换。

---

### 0.4 新项目与旧项目的区别

统一规则：

```text
                    当前项目
                       │
              ┌────────┴────────┐
              │                 │
           空白项目           已有项目
              │                 │
              ▼                 ▼
      按标准初始化项目结构    保留原项目结构
              │                 │
              └────────┬────────┘
                       ▼
                使用 Agent 结构
                       │
                       ▼
        constitution / specs / .ai
                       │
                       ▼
              统一 Agent 开发流
```

一句话：

> 项目结构负责“项目怎么组织”，Agent 结构负责“Agent 怎么开发这个项目”。

---

## 1. Agent 角色

### 项目补充约定：Spec 决策无需子 Agent 验证

用户已明确：Spec 的讨论、起草、技术选型决策及相应文档更新，由协调 Agent 直接处理并自行检查，不创建子 Agent 专门验证或验收这些决策。

本约定适用于后续所有 Spec 决策，除非用户明确改变要求。业务代码实施后的独立验收继续遵循下文规则。详见 [Spec 决策工作规则](.ai/rules/spec-decision-workflow.md)。

| 角色 | 定位 | 职责 |
|---|---|---|
| **协调开发 Agent** | 主 Agent | 与用户沟通、识别项目状态、理解现有项目、处理决策、编写和维护 Spec、调度和管理子 Agent |
| **实施 Agent** | 子 Agent | 按照已确认的 Spec 和项目约束完成具体开发任务 |
| **验收 Agent** | 子 Agent | 根据 Spec 独立检查和验收实施结果 |

在支持多 Agent 的环境中，优先采用以上角色分工。

如果当前运行环境不支持子 Agent，则允许降级为单 Agent 工作流，但必须保持“规划 → 实施 → 二次审查 → 验证”的阶段隔离，不得伪造独立 Agent 验收。

---

## 2. 总体协作流程

### 2.1 通用开发流程

1. 协调 Agent 判断当前项目属于空白项目还是已有项目。
2. 按对应初始化规则完成项目理解或 Agent 结构接入。
3. 协调 Agent 与用户沟通需求，读取项目现状，起草和完善 Spec。
4. 影响实施结果的关键决策确认后，将 Spec 标记为可实施状态。
5. 协调 Agent 创建实施 Agent，按 Spec 实施。
6. 实施 Agent 返回 Implementation Report。
7. 协调 Agent 创建**新的独立验收 Agent**进行验收。
8. 验收未通过 → 协调 Agent 根据验收结果创建新的实施 Agent 返工 → 新验收 Agent 重新验收。
9. 重复实施 / 验收 / 返工，直到验收通过。
10. 协调 Agent 汇总结果交用户审查。

标准闭环：

```text
需求
↓
项目理解 / 初始化
↓
Spec
↓
实施 Agent
↓
实施报告
↓
独立验收 Agent
↓
验收报告
↓
PASS ─────────────→ 最终交付
│
FAIL
↓
返工任务
↓
新的实施 Agent
↓
新的验收 Agent
↓
重新验收
```

**实施 Agent 与验收 Agent 必须相互独立。验收 Agent 不得代替实施 Agent 修改业务代码。实施 Agent 不负责最终验收。**

---

## 3. 空白项目初始化规则

本规范主要支持从空白项目开始进行 Agent 驱动开发。

当项目被判定为 `NEW` 时，应按照以下流程初始化。

### 3.1 创建标准基础结构

空白项目必须以以下结构作为基础：

```text
AGENTS.md

constitution/
├── mission.md
├── roadmap.md
└── tech-stack.md

specs/
├── README.md
└── _template/
    ├── spec.md
    ├── plan.md
    └── acceptance.md

docs/

tests/

.ai/
├── decisions/
├── workflows/
├── prompts/
└── rules/

<业务代码目录，根据项目实际情况确定>
```

其中：

- `AGENTS.md`、`constitution/`、`specs/`、`.ai/` 属于 Agent 结构；
- `docs/`、`tests/` 与业务代码目录属于空白项目的基础项目结构；
- 业务代码目录由项目类型和技术栈决定，不在本规范中写死。

允许根据项目需要继续扩展，例如：

```text
frontend/
backend/
src/
apps/
packages/
scripts/
infra/
examples/
```

但不得因为 Agent 偏好而删除、移动、重命名或替换已经确定的基础目录。

---

### 3.2 先理解项目，再创建业务代码

协调 Agent 不得在尚未理解产品目标的情况下直接生成大量业务代码。

至少应理解：

- 项目是什么；
- 解决什么问题；
- 目标用户是谁；
- 核心能力是什么；
- 当前阶段需要做到什么；
- 明确不做什么；
- 是否存在重要外部约束。

用户已经说明的信息不得重复询问。

---

### 3.3 初始化 constitution

#### `constitution/mission.md`

记录长期稳定的信息：

- 项目背景；
- 项目使命；
- 产品目标；
- 核心用户价值；
- 核心原则；
- 长期方向；
- 明确非目标。

#### `constitution/roadmap.md`

记录项目路线与阶段目标，例如：

```text
Phase 0 — Prototype
Phase 1 — MVP
Phase 2 — Productization
Phase 3 — Expansion
```

Roadmap 描述阶段方向，不替代具体 Spec。

#### `constitution/tech-stack.md`

记录已经确认的技术与工程约束：

- 编程语言；
- 框架；
- Runtime；
- 包管理器；
- 数据库；
- AI / LLM 服务；
- 前后端架构；
- 业务代码目录；
- 测试框架；
- Build 命令；
- Test 命令；
- Lint 命令；
- Format 命令；
- 部署方式；
- 外部依赖；
- 重要技术限制。

一旦业务代码目录已经确定并投入使用，除非用户明确批准架构调整，否则 Agent 不得擅自迁移或重命名。

---

### 3.4 创建第一个 Spec

产品目标和技术方向具备实施条件后，创建：

```text
specs/spec-001-short-name/
```

至少包含：

```text
spec.md
plan.md
```

实施完成后产生：

```text
acceptance.md
```

如发生返工，可以扩展：

```text
rework.md
implementation.md
```

---

### 3.5 创建业务项目结构

业务目录应由技术方案决定。

例如：

```text
src/
```

或：

```text
frontend/
backend/
```

或：

```text
apps/
packages/
```

不得为了追求“统一目录”而忽略技术栈本身的合理工程结构。

最终确定的业务代码位置必须记录到：

```text
constitution/tech-stack.md
```

---

## 4. 已有项目接入规则

当项目被判定为 `EXISTING` 时：

> **已有项目结构优先，Agent 开发结构嵌入其中。**

不是让旧项目适配本规范的业务目录，而是把 Agent 开发流接入旧项目。

---

### 4.1 保留现有项目结构

协调 Agent 应首先阅读并理解旧项目：

- README；
- 业务代码；
- package / manifest；
- lockfile；
- build 配置；
- test 配置；
- CI；
- Docker；
- 部署配置；
- 现有文档；
- 现有 Agent 规则；
- 现有架构说明。

不得因为本规范存在默认新项目结构，就擅自：

- 移动旧代码；
- 重命名旧目录；
- 将旧目录改造成自己的偏好结构；
- 新建职责重复的业务目录；
- 大规模重构工程结构；
- 修改已有测试目录位置；
- 修改已有文档目录位置。

例如旧项目已经采用：

```text
app/
components/
lib/
```

或者：

```text
server/
client/
shared/
```

应继续沿用。

---

### 4.2 向旧项目加入 Agent 结构

旧项目接入时，应加入或补齐：

```text
AGENTS.md

constitution/
├── mission.md
├── roadmap.md
└── tech-stack.md

specs/
├── README.md
└── _template/
    ├── spec.md
    ├── plan.md
    └── acceptance.md

.ai/
├── decisions/
├── workflows/
├── prompts/
└── rules/
```

这些结构用于描述和管理原项目，不用于改变原项目。

如果旧项目已经存在同名 Agent 文件或同类 Agent 规则：

1. 先读取；
2. 保留已有有效约束；
3. 不直接覆盖；
4. 将本规范与旧规则进行兼容整合；
5. 存在重大冲突且无法可靠判断时，由协调 Agent 请求用户决策。

---

### 4.3 为旧项目建立 constitution

`constitution/mission.md`：

- 根据 README、产品文档、现有代码和用户说明总结项目当前使命；
- 不得凭空创造不存在的产品目标。

`constitution/roadmap.md`：

- 有现成 Roadmap 时，应引用或整理现有 Roadmap；
- 没有足够依据时，记录当前已知阶段和待确认内容；
- 不得擅自替用户规划长期业务方向。

`constitution/tech-stack.md`：

必须描述实际存在的项目：

- 当前技术栈；
- 当前业务代码目录；
- 当前测试位置；
- 当前文档位置；
- 当前构建方式；
- 当前运行方式；
- 当前依赖与部署方式。

其作用是建立 Agent 对旧项目的可靠认知，不是重新设计旧项目。

---

### 4.4 旧项目不强制创建重复项目目录

`docs/`、`tests/` 属于项目结构而非 Agent 结构。

因此旧项目如果已经使用：

```text
__tests__/
documentation/
e2e/
test/
wiki/
```

等其他结构，不得为了与空白项目默认结构一致而新建重复目录。

只需要在：

```text
constitution/tech-stack.md
```

记录真实位置。

---

## 5. 协调 Agent 职责边界

协调 Agent 负责：

- 与用户沟通；
- 判断 NEW / EXISTING；
- 理解项目现状；
- 识别需要用户决策的问题；
- 起草、完善和维护 Spec；
- 管理重要决策；
- 创建和控制子 Agent；
- 向子 Agent 完整传递上下文；
- 组织返工；
- 汇总结果；
- 维护 Agent 结构；
- 恢复中断任务状态。

在多 Agent 环境中，协调 Agent 原则上不直接编写或修改主要业务代码。

协调 Agent 可以：

- 阅读业务代码；
- 搜索项目；
- 分析 Git diff；
- 阅读测试；
- 维护 `constitution/`；
- 维护 `specs/`；
- 维护 `.ai/`；
- 创建任务交接；
- 分析子 Agent 结果。

业务实现应交由实施 Agent。

如果当前运行环境不支持子 Agent，或者用户明确要求主 Agent 直接开发，则允许协调 Agent 降级执行实施工作。

---

## 6. 子 Agent 硬性约束

- 禁止子 Agent 再创建子 Agent，除非用户或更高层规则明确允许。
- 给予子 Agent 足够思考和执行时间。
- 禁止因单次等待超时就擅自终止仍在正常运行的子 Agent。
- 对仍有明确进展或仍在正常工作的子 Agent 不得擅自关闭；无任何有效进展且持续空转超过 1 小时，才可考虑关闭并重新分配任务。
- 子 Agent 任务完成并且结果已处理后，应及时释放或删除。
- 一个任务如果涉及多个高度耦合模块修改，默认只派给一个实施 Agent 串行实施。
- 实施 Agent 不做最终验收。
- 验收 Agent 不修改业务代码。
- 子 Agent 不得绕过协调 Agent 替用户做重大项目决策。

---

## 7. 子 Agent 等待与消息闭环

创建子 Agent 后，协调 Agent 必须保持当前任务活动状态，并使用当前运行环境提供的：

- `wait_agent`；
- `list_agents`；
- status；
- receive；
- polling；
- 或等价能力；

持续等待和检查子 Agent。

规则：

- 单次等待超时 → 只代表需要继续等待；
- 暂无消息 → 不代表完成；
- Agent 仍在运行 → 不代表失败；
- Agent 已完成但报告未读取 → 任务仍未闭环。

存在仍在运行的子 Agent 时，协调 Agent 不得发送任务完成式最终回复。

存在已返回但尚未读取和处理的 Agent 报告时，协调 Agent 不得发送任务完成式最终回复。

进度通知只能作为中间状态消息；最终回复是任务闭环动作，不得用于“已创建 Agent，请稍后等待”之类的未完成状态。

---

## 8. Spec 沟通与决策规则

### 8.1 Spec 的目的

Spec 用于定义：

> 要实现什么，以及怎样才算正确完成。

Spec 不只是代码修改清单。

---

### 8.2 需要确认的问题

每次起草新 Spec 时，协调 Agent 必须识别会影响实施结果的关键决策。

包括：

- 需求范围；
- 业务规则；
- 用户可见行为；
- 数据模型；
- API 行为；
- 权限和安全；
- 外部服务；
- 兼容性；
- 不可逆操作；
- 可能产生费用的技术选择；
- 验收标准。

关键问题未确认前，不得让实施 Agent 擅自开始存在重大歧义的实施。

但不得为了“走流程”机械提问。

如果信息已经由用户明确说明，禁止重复询问。

---

### 8.3 决策优先顺序

遇到不明确之处时，按照：

```text
用户当前明确说明
↓
AGENTS.md
↓
constitution
↓
.ai/rules
↓
当前 Spec
↓
已有 Decision
↓
项目现有行为和代码事实
↓
可靠工程惯例
↓
询问用户
```

可以从项目可靠判断的工程细节，应根据项目现状自行判断。

涉及重大产品决策、不可逆行为或明显存在多个合理方向的问题，应交给用户决定。

---

## 9. Spec 目录与规范

Spec 统一放置在：

```text
specs/
```

命名格式：

```text
spec-XXX-short-name
```

例如：

```text
specs/
├── README.md
├── _template/
└── spec-001-user-auth/
    ├── spec.md
    ├── plan.md
    ├── acceptance.md
    └── rework.md        # 可选
```

不得擅自把 Spec 改放到 `.ai/specs/`、`docs/specs/` 或其他目录。

---

### 9.1 `spec.md`

至少包含：

```markdown
# Spec

## 背景

## 目标

## 非目标

## 当前行为

## 目标行为

## 功能需求

## 边界条件

## 技术约束

## 兼容性要求

## 验收标准

- [ ]
- [ ]

## 待确认问题
```

---

### 9.2 `plan.md`

描述如何实施已经确认的 Spec，包括：

- 涉及模块；
- 修改顺序；
- 数据流；
- 接口变化；
- 测试计划；
- 风险；
- 迁移策略；
- 预计涉及文件。

Plan 可以随着代码调研完善，但不得绕过 Spec 改变需求本身。

---

### 9.3 `acceptance.md`

记录独立验收结果：

```markdown
# Acceptance

## Result

PASS / FAIL

## Spec Coverage

## Tests

## Issues

## Regression Risks

## Required Rework
```

---

## 10. 重要决策留痕

重要决策统一记录到：

```text
.ai/decisions/
```

包括但不限于：

- 架构方案；
- 数据模型；
- API 设计；
- 第三方服务；
- 业务规则；
- 兼容策略；
- 技术栈变更；
- 目录结构变更；
- 用户明确否决的关键方案；
- 重要临时方案；
- 未来需要偿还的技术债。

重要对话结论、需求变化和影响后续开发的信息必须留痕，不能只存在于聊天上下文。

推荐格式：

```markdown
# Decision

## Context

## Decision

## Reason

## Alternatives

## Consequences
```

---

## 11. 初始化 Prompt 的阅读要求

每个 Agent 启动时，应按以下顺序阅读。

### 11.1 固定必读

```text
AGENTS.md
constitution/mission.md
constitution/tech-stack.md
.ai/rules/
```

`.ai/rules/` 下存在的全部有效规则都需要读取。

### 11.2 任务必读

- 当前 Spec：`specs/spec-XXX-*/spec.md`
- 当前 Plan：对应 `plan.md`（如存在）
- 被当前任务引用的重要决策：`.ai/decisions/`
- 当前任务交接：优先读取 `.ai/prompts/task-handoff.md` 的当前任务渲染产物；项目如已扩展其他 handoff 文件，也一并读取

### 11.3 条件必读

返工任务：

- 当前 Spec 历次 `acceptance.md`；
- `rework.md`；
- 上一轮实施报告。

验收 Agent：

- `spec.md`；
- `plan.md`；
- 实施报告；
- 相关 diff；
- 相关测试。

实施 Agent：

- `spec.md`；
- `plan.md`；
- 相关 `.ai/workflows/`；
- 实施任务优先读取 `.ai/workflows/implementation.md`（如存在）；
- 相关业务代码。

项目规划任务：

- `constitution/mission.md`；
- `constitution/roadmap.md`；
- `constitution/tech-stack.md`。

---

## 12. 指令冲突优先级

默认优先级：

```text
用户当前明确指令
↓
AGENTS.md
↓
constitution
↓
.ai/rules
↓
当前 Spec
↓
.ai/workflows
↓
相关 Decision
↓
项目现有文档与稳定工程约定
↓
历史对话上下文
```

如果旧项目已有更细粒度的目录级 Agent 指令，则协调 Agent 应读取，并在不违反更高优先级约束的前提下遵守局部规则。

任何规则冲突都不得成为擅自删除、移动或重构已有目录的理由。

---

## 13. Task Handoff 规范

协调 Agent 向实施 Agent 或验收 Agent 分配任务时，必须完整传递上下文。

不得只发送：

> 实现这个功能。

推荐结构：

```markdown
# Task Handoff

## Role

Implementation / Acceptance

## Goal

## Context

## Project Mode

NEW / EXISTING

## Spec

## Relevant Files

## Scope

## Out of Scope

## Constraints

## Acceptance Criteria

## Commands

## Expected Output
```

任务交接内容必须让子 Agent 在不依赖隐式聊天上下文的情况下理解当前任务。

---

## 14. 实施 Agent 返回规范

实施 Agent 完成后，应返回 Implementation Report：

```markdown
# Implementation Report

## Summary

## Files Changed

## Important Decisions

## Tests

## Known Limitations

## Remaining Questions
```

如果存在无法执行的测试，必须明确说明，不得把“未执行”表述为“已通过”。

---

## 15. 验收 Agent 规则

验收 Agent 必须独立于实施 Agent。

验收内容包括：

- Spec 是否逐项满足；
- 实现是否符合项目结构和技术约束；
- 是否修改无关代码；
- 是否存在边界遗漏；
- 是否存在明显回归风险；
- 测试是否充分；
- 文档是否需要更新；
- 是否违反目录结构规则；
- 是否擅自改变业务行为。

验收结果只能是：

```text
PASS
```

或：

```text
FAIL
```

验收 Agent 发现问题时，应返回问题，不得自己修改业务代码。

---

## 16. 返工规则

验收失败时：

1. 协调 Agent 读取完整 Acceptance Report。
2. 将失败原因整理为明确返工目标。
3. 必要时创建或更新 `rework.md`。
4. 创建新的实施 Agent 进行返工。
5. 返工完成后创建新的独立验收 Agent。
6. 不得直接复用上一验收 Agent 的结论作为新一轮结果。

流程持续直到：

- PASS；
- 用户明确接受已知问题；
- 用户取消任务。

---

## 17. 并行实施规则

默认：

```yaml
allow_parallel_implementation: false
```

如果一个任务涉及多个模块但彼此高度耦合，应由一个实施 Agent 串行完成。

只有同时满足以下条件，才考虑并行：

1. 子任务真正独立；
2. 修改文件不重叠；
3. 接口边界已经确认；
4. 数据结构已经确认；
5. 合并顺序明确；
6. 协调 Agent 可以统一验收。

否则禁止为了追求速度而并行创建多个实施 Agent 修改同一项目区域。

---

## 18. 项目目录结构变更规则

目录结构属于高影响工程决策。

### 18.1 Agent 结构

以下结构未经用户明确授权不得删除、移动、重命名或替代：

```text
AGENTS.md
constitution/
specs/
.ai/
```

### 18.2 空白项目初始化后的项目结构

空白项目一旦建立：

```text
docs/
tests/
<业务代码目录>
```

后续允许扩展，但不得擅自：

- 删除；
- 重命名；
- 移动；
- 重构为另一套目录体系。

### 18.3 已有项目结构

已有项目的原始目录默认视为既有工程约束。

除非当前任务本身就是经用户批准的目录 / 架构重构，否则不得改变其位置和职责。

### 18.4 必须修改目录时

如果确实需要结构调整，必须：

1. 说明为什么现有结构无法满足需求；
2. 明确影响范围；
3. 给出迁移方案；
4. 说明兼容和回滚风险；
5. 获得用户确认；
6. 在 `.ai/decisions/` 留痕；
7. 再实施。

---

## 19. Git 与用户已有修改

开始修改前，应检查当前工作区状态。

Agent 不得：

- 删除用户尚未提交的修改；
- revert 与当前任务无关的代码；
- 因为工作区不干净就擅自 reset；
- force checkout 覆盖未知修改；
- 将用户修改误认为 Agent 自己产生的修改。

发现相关文件已经存在修改时：

1. 先阅读；
2. 判断修改来源和意图；
3. 尽可能兼容；
4. 存在不可安全合并的冲突时，由协调 Agent 处理。

---

## 20. 依赖与技术栈规则

Agent 必须优先遵循：

```text
constitution/tech-stack.md
```

不得无必要：

- 更换语言；
- 更换框架；
- 更换包管理器；
- 删除 lockfile；
- 重建整个 lockfile；
- 升级大量无关依赖；
- 替换核心基础设施；
- 引入功能明显重复的依赖。

添加重要外部服务前，应判断：

- 项目是否已有等价能力；
- 是否产生费用；
- 是否引入账号、密钥或平台绑定；
- 是否形成重大架构依赖。

重大技术选择应记录到 `.ai/decisions/`。

---

## 21. 测试与验证规则

不得仅凭代码阅读就宣布功能完成。

验证优先级：

```text
任务相关测试
↓
模块测试
↓
类型检查
↓
Lint
↓
Build
↓
必要时更大范围测试
```

实际命令以：

```text
constitution/tech-stack.md
```

和项目真实配置为准。

不得凭空假设：

```bash
npm test
pytest
pnpm build
```

一定可用。

必须从项目真实配置中确认。

如果无法执行测试，Implementation Report / Acceptance Report 必须说明：

- 哪个测试没有运行；
- 为什么；
- 做了什么替代验证；
- 剩余风险是什么。

---

## 22. 文档规则

### 22.1 Agent 文档

以下内容发生重要变化时，应同步维护：

- `constitution/`；
- `specs/`；
- `.ai/decisions/`；
- `.ai/rules/`；
- `.ai/workflows/`。

### 22.2 项目文档

项目行为发生变化时，应判断是否需要同步修改：

- README；
- API 文档；
- 配置说明；
- Examples；
- Deployment Guide；
- Migration Guide；
- 项目已有其他文档。

空白项目中新建 README 时，默认遵循 `standard-readme` 的清晰结构，不使用 readme-standard 徽章。

已有项目存在成熟 README 规范时，优先保持旧项目风格，不因本规范而强制重写。

---

## 23. 安全规则

Agent 不得：

- 输出或提交真实密钥；
- 将 `.env` 中敏感信息写入日志；
- 将凭证硬编码到代码；
- 擅自删除生产数据；
- 擅自操作生产环境；
- 擅自执行明显不可逆操作；
- 在用户未确认的情况下创建明显会持续计费的云资源。

以下行为属于高风险动作：

- 数据删除；
- Migration；
- Force Push；
- Reset；
- Production Deployment；
- 权限变更；
- Secret Rotation；
- 外部收费 API；
- 云资源创建；
- 破坏性目录迁移。

涉及高风险动作时必须进行额外确认和留痕。

---

## 24. 上下文恢复

发生以下情况：

- 对话压缩；
- Agent 重启；
- 用户中途发送新消息；
- 工作流意外中断；
- 新 Agent 接手；

恢复时不得无依据重新开始任务。

首先检查：

1. 当前 `project_mode`；
2. `AGENTS.md`；
3. `constitution/`；
4. 当前 Spec；
5. 当前 Plan；
6. 已创建的子 Agent；
7. 已返回但未处理的报告；
8. `acceptance.md`；
9. `rework.md`；
10. `.ai/decisions/`；
11. Git diff；
12. 当前工作区状态。

然后判断当前任务处于：

```text
Initialization
Planning
Implementation
Acceptance
Rework
Done
```

从断点继续。

不得无依据：

- 重复创建同类 Agent；
- 重复实施；
- 覆盖已有修改；
- 跳过已有报告；
- 将普通用户追问理解为任务取消。

只有用户明确表示取消、停止或切换任务，才视为取消原任务。

---

## 25. README 与目录说明

### 25.1 `specs/README.md`

应说明：

- Spec 命名方式；
- Spec 生命周期；
- `spec.md` / `plan.md` / `acceptance.md` 职责；
- PASS / FAIL 规则；
- 返工规则。

### 25.2 目录不能因“更好看”而调整

Agent 不得为了：

- 更整洁；
- 更符合某个框架模板；
- 更符合个人习惯；
- 减少目录数量；
- 使用自己熟悉的项目脚手架；

擅自改变本规范确定的目录位置。

---

## 26. Definition of Done

任务只有在合理适用的以下条件满足后，才能认为完成：

- [ ] 已正确识别 NEW / EXISTING；
- [ ] 没有破坏项目原有目录结构；
- [ ] Agent 结构符合本规范；
- [ ] 用户目标已经实现；
- [ ] Spec 要求已经满足；
- [ ] 没有明显遗漏；
- [ ] 边界条件已经考虑；
- [ ] 相关测试已经执行；
- [ ] 测试通过，或未执行项已明确说明；
- [ ] 必要的 Build / Type Check / Lint 已完成；
- [ ] 没有引入明显回归；
- [ ] 没有修改无关代码；
- [ ] 重要决策已经记录；
- [ ] 相关文档已经同步；
- [ ] 多 Agent 模式下已完成独立验收；
- [ ] 所有子 Agent 结果已经读取和处理；
- [ ] 验收结果为 PASS，或用户明确接受剩余问题。

---

## 27. 最终交付规范

最终回复应简洁说明：

### 完成了什么

项目目标或当前任务的最终结果。

### 主要修改

重要文件、模块和行为变化。

### 验证

说明：

- 执行了什么；
- 什么通过；
- 什么没有执行。

### 重要决策

如存在，说明对应 Decision。

### 剩余问题

如存在，明确列出。

不得使用大量无价值过程日志代替最终结果。

---

## 28. 总原则

整个开发流程遵循：

```text
识别项目状态
↓
NEW：初始化项目结构 + Agent 结构
EXISTING：保留项目结构 + 接入 Agent 结构
↓
理解项目
↓
理解需求
↓
维护 constitution
↓
识别关键决策
↓
建立 Spec
↓
实施 Agent
↓
测试
↓
独立验收 Agent
↓
返工（如需要）
↓
PASS
↓
最终交付
```

本规范最重要的结构原则是：

> **新项目：按照标准项目结构开始，并允许在此基础上扩展，但不得擅自删除、移动或替换既有结构。**

> **旧项目：尊重并保留原有项目结构，只将 AGENTS.md、constitution、specs、.ai 等 Agent 开发结构接入项目，不得为了适配本规范而重构旧项目。**

本规范最重要的开发原则是：

> **Agent 的目标不是尽快生成代码，而是在充分理解项目和需求的前提下，通过 Spec、实施、独立验收、决策留痕和上下文恢复机制，以可验证、可追踪、可维护的方式完成正确的修改。**
