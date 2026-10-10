# Plan：本地启动与容器管理统一

对应 [规格](spec.md)。按统一分组、本地开发范围实施，生产部署与 CD 不变。

## 改造目录

```text
scripts/company/
├── run.mjs                          [修改] 接入统一依赖生命周期
├── database-local.mjs               [修改] 数据库配置与复用，移除重复编排
├── reply-stream-local.mjs           [修改] Redis 接入 Compose，移除 docker run
├── sandbox-local.mjs                [修改] 同项目启动、构建与 runner 载入
└── local-infra/                     [新增] 本地基础设施管理
    ├── compose.mjs                 [新增] 统一项目、配置与 Docker 调用
    ├── lifecycle.mjs               [新增] 归属、健康检查、停止与失败清理
    ├── processes.mjs               [新增] Unix 进程组与 Windows 子进程树停止
    ├── migrate.mjs                 [新增] 旧容器迁移、资源映射和回滚
    └── migration-data.mjs          [新增] 持久卷检查、备份恢复和数据核对
deploy/company/
├── compose.dev.yml                 [修改] 开发服务唯一配置与分组
└── compose.sandbox-local.yml        [修改] 沙盒覆盖、网络及旧卷显式映射
tests/
├── deploy/
│   ├── local-reply-stream.test.mjs  [修改] 统一 Compose 下的 Redis 生命周期
│   ├── local-infra.test.mjs         [新增] 启停、异常、外部资源和归属
│   ├── local-infra-migration.test.mjs [新增] 旧资源迁移与回滚
│   └── local-infra-rehearsal.mjs    [新增] 隔离 Docker 真实迁移与故障演练
└── sandbox/
    └── local-dev.test.mjs           [复用] 沙盒命令及配置兼容
.github/workflows/ci.yml             [修改] 接入快速编排测试
package.json                        [修改] 一次性本地环境迁移命令
README.md                           [修改] 启动入口说明
docs/
├── setup.md                        [修改] 初始化、迁移、停止与回滚
└── architecture.md                 [修改] 本地与生产的运行边界
constitution/tech-stack.md          [修改] 本地基础设施管理说明
```

业务 API、流式存储、前端和生产部署文件预计不修改；复用现有测试验证它们。文件职责可在实施时收敛，不扩展成通用容器管理框架。

## 实施顺序

1. 固化服务清单与资源映射：统一开发项目名，明确已存在容器、数据卷、网络、镜像和端口的识别规则。沿用现有 `paa-company` 开发项目名，避免再引入一套命名。
2. 为现有 Compose 增加安全的组合运行方式；数据库／Redis和沙盒网络分开，沙盒关闭时不要求令牌，不启动 runner-image 常驻服务。
3. 提取共用编排与生命周期逻辑。应用停止等待清理完成，保持数据库留存与外部服务豁免；沙盒引擎就绪后才能载入镜像和启动控制服务。
4. 实现可重复的一次性迁移。旧资源清单、回滚配置和本机映射写入被忽略的 `data/company/local-infra/`；在测试卷上演练成功后，才迁移用户本地环境。
5. 三个开发依赖适配器、`run.mjs` 和沙盒独立命令接入同一编排，移除旧的重复创建／清理分支。
6. 按下表验证，修复本次引入的问题；更新文档，交独立验收。

## 数据流与接口

```text
.env.web + 本地持久卷映射
    → 统一开发 Compose
    → PostgreSQL / Redis / 可选沙盒就绪
    → API + worker + Vite

模型正文 → worker → Redis → API SSE → 浏览器
最终回复、业务回执 → PostgreSQL
代码／内置任务 → control → 私有 runtime → 临时 gVisor 容器 → 成果
```

运行时 HTTP、SSE、工具协议和数据持久化不变。新增命令建议为 `npm run dev:web:migrate`，只迁移本地容器编排；已有 `npm run db:company` 仍专门负责业务数据库迁移。

## 迁移与回滚

- 旧容器无 Compose 标签，需重建容器外壳；先记录实际镜像 ID、挂载、端口和必要配置，禁止在日志中打印凭据。
- 数据库使用原卷和原镜像；当前机器为 `paa_company_pgdata`，但迁移器必须按实际检查结果绑定。新安装与旧卷迁移使用不同的创建条件，旧卷缺失直接报错。
- 旧沙盒使用按仓库路径生成的项目名。显式保留实际 `engine-data`、`control-state` 卷与 runner 镜像身份，避免新的项目名前缀导致空状态或重复下载。
- 停旧服务后重建 socket 连接；持久状态卷用明确名称引用，禁止两个引擎或数据库实例同时读写同一卷。
- 端口或容器名需要让位时，将本项目旧容器停用并保留可恢复名称；新服务通过健康检查和业务数据核对后才结束迁移。回滚停新容器、恢复旧名称／配置／原镜像，不清空卷。
- 迁移可中断后再执行，记录阶段并核对真实状态；失败不得把半完成迁移当作正常新安装。
- 生产部署已有统一 Compose，此次不迁移线上；执行静态配置兼容检查即可。

## 测试计划

实施属于 S3：涉及启动基础设施、容器资源归属与持久数据迁移。文档阶段为 S0，仅检查文档与引用，不运行下列测试。

| 层面 | 必测场景 | 验证方式 |
| --- | --- | --- |
| 编排与生命周期 | 新安装、旧容器、服务已运行、第二次启动、外部地址、端口冲突、Docker 不可用、启动期间退出、健康检查失败 | 定向 Node 测试；Docker 调用桩验证参数、停止顺序和归属 |
| 真实容器 | 启用／关闭沙盒、冷／热启动、连续三次启停、独立 API／worker 命令 | 隔离 Compose 项目真实运行，检查项目标签、端口、容器及进程残留 |
| 迁移 | 带种子数据的旧 docker run 数据库、旧 Redis、旧沙盒项目；原卷复用、镜像不变、迁移中断、故障回滚 | 独立卷与端口演练，迁移前后核对账号／会话／工作／记忆／成果、文件摘要及控制回执 |
| 流式聊天 | API／worker 分进程、中文增量、长答案、完成保存、刷新、中断、手动重试、Redis 重启 | 既有 Redis 真实传输测试、正文流服务测试及浏览器流式用例；固定模型流作为可重复输入 |
| Agent 业务流程 | 普通问答；引用工作→修改内容→读回；附件→提取→总结；记忆跨会话；报告生成→确认提交；三档权限与角色隔离 | 真实 API／worker＋固定可控模型，检查工具执行、回执、数据库与 UI 一致；不把模型发挥当基础设施结论 |
| 沙盒 | Python、表格／图表／文档内置工具、生成下载、多轮改成果；并发排队、超时、中断、运行时缺失 | 隔离控制服务与真实 gVisor 执行，不只 mock；检查非 root、无网络、无业务凭据、任务间文件隔离和回收 |
| Web 冒烟 | 员工／管理员登录、聊天、我的工作、报告／团队看板、模型管理、记忆、附件与成果下载 | 复用现有种子用户与页面流程，确认页面无服务错误且数据可读写 |
| 生产兼容 | 本地覆盖不污染生产 Compose、发布脚本仍能解析原拓扑 | 测试配置解析与既有部署定向测试，不连接或发布服务器 |

执行入口：

- `node --test tests/deploy/local-*.test.mjs tests/sandbox/local-dev.test.mjs`，覆盖新增启动与迁移逻辑；跨平台测试不得新增只在 Unix 可用的调用桩。
- `npm run test:server -- tests/server/test_reply_stream_transport.py tests/server/test_assistant_reply_stream.py tests/server/test_sandbox_runtime.py tests/server/test_sandbox_execution.py`，设置隔离数据库与 Redis 测试地址；真实 Redis 测试不得因未配置而跳过后宣称通过。
- 复用 `tests/sandbox/test_protocol.py`、`real_execution.py`、`recovery_execution.py` 和 Web 的 `streaming*.spec.ts` 进行对应场景验证。真实沙盒故障脚本只连接明确标记的隔离测试服务。
- 格式化本次修改的 MJS／JSON／工作流文件，并检查相关文件；没有修改前端，不默认全量前端构建或 Electron 测试。

测试专用配置必须覆盖所有固定容器名、项目名、端口和持久卷，不能因复制开发 Compose 而挂载用户真实卷。破坏性场景只在测试资源中执行，不停止日常服务。必要时一次性补充真实模型冒烟，单独记录服务商限制；固定输入测试与真实模型测试分别报告。

记录冷／热启动耗时、空闲资源和首字延迟作为对照，不能把不同网络／模型强度差异归因于容器整合。已有定向检查通过后不无依据重复执行。

## 主要风险

- 更换项目名可能误建空卷：依赖显式映射、旧卷存在检查和迁移前后数据核对。
- Compose 默认网络可能扩大互通范围：显式分隔业务基础服务与沙盒，验证网络可达性。
- 多入口使用同一项目后可能误停共享服务：统一归属记录、启动互斥和精确停止服务列表。
- 数据库镜像标签变化可能引入额外升级：旧环境迁移固定原镜像，不混入版本升级。
- 单一分组本身不会明显减少资源占用；若用户要求减少实际服务，需重新确认架构及验证范围。
