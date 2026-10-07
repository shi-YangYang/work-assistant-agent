# Plan

## 对应 Spec

[成员管理改造](spec.md)。按已确认范围实施。

## 涉及模块与数据流

- 成员页面读取已有完整列表，以 URL 的 `q` 搜索全部成员，再按 `page` 每页展示 20 人；刷新保留关键词和有效页码。旧 `status` 参数不再筛选成员。
- 成员列表接口补充账号创建时间；单行操作沿用成员 ID 和现有服务端公司／角色检查。
- 姓名表单 → 成员请求层 → PATCH 校验 → 仅更新姓名 → 成功刷新列表一次。移除成员启停写入路径，保留删除、创建各自已有的资格计算和会话处理。
- “查看工作”用现有 `/team` 的 `member`、`members`、`view=work`、`scope=current` 参数，不新增查询接口；通过既有返回状态保留成员列表入口。
- 升级时运行一次历史停用员工清理命令，按公司复用既有删除业务及文件清理队列，不增加页面操作或周期性扫描。

## 改造后目录

```text
apps/web/src/
├── app/AppRoutes.tsx                         修改：成员页面导入路径
├── features/members/
│   ├── api/requests.ts                       修改：用姓名更新替换启停请求、列表类型
│   └── components/
│       ├── overview/
│       │   ├── MembersPage.tsx               移动并修改：页面状态与操作编排
│       │   ├── MembersPage.module.css        新增：布局、列表与响应式
│       │   ├── MembersToolbar.tsx            新增：搜索与数量
│       │   └── MembersList.tsx               新增：成员行和操作入口
│       ├── forms/
│       │   ├── MemberForm.tsx                移动：保留创建／重置及校验
│       │   └── MemberNameForm.tsx            新增：姓名编辑
│       └── actions/
│           └── DeleteMember.tsx             移动并修改：删除影响与防重复提交
├── features/team/components/TeamWorkspace.tsx 修改：返回成员页并保留关键词
└── features/auth/components/configuration/
    └── LoginConfiguration.tsx               修改：移除“在成员管理中停用”的提示
apps/server/app/modules/members/
├── router.py                                修改：列表创建时间序列化
├── serializers.py                           修改：列表专用输出
├── schemas.py                               修改：仅接受姓名、拒绝 active
├── commands.py                              修改：姓名更新替换启停；复用删除业务
└── cleanup_inactive.py                       新增：一次性清理历史停用员工
apps/server/app/cli.py                        修改：清理命令入口
packages/api-contracts/src/index.ts           修改：成员列表条目类型
docs/setup.md                                修改：升级清理、账号删除与钉钉授权说明
tests/
├── web/
│   ├── member-form.test.ts                   修改：组件导入路径
│   ├── request-contracts.test.ts             修改：姓名请求契约
│   ├── routes.test.ts                        修改：页面导入路径
│   └── dom/
│       ├── members.test.tsx                  新增：搜索、无启停入口与操作反馈
│       └── voiceprint-cleanup.test.tsx       修改：删除组件导入路径
├── server/
│   ├── member_fixtures.py                    新增：历史停用状态夹具
│   ├── test_member_management.py             新增：姓名更新、拒绝启停及权限边界
│   ├── test_inactive_member_cleanup.py       新增：清理范围、关联处理与重复执行
│   ├── test_input_validation.py              修改：新增字段输入边界
│   ├── test_auth_concurrency.py              修改：保留停用后会话拒绝验证
│   ├── test_company.py                       修改：保留账号安全验证
│   ├── test_core_scope_coverage.py           修改：合法姓名更新覆盖
│   ├── test_dingtalk.py                      修改：历史停用夹具
│   ├── test_member_deletion.py               修改：已删除账号更新拒绝
│   ├── test_report_reliability.py            修改：保留历史汇报资格验证
│   └── test_voiceprint_lifecycle.py          修改：保留历史停用声纹验证
└── e2e/web/settings/management.spec.ts        修改：成员流程、状态与视觉验证
```

移动限于此次成员功能；同步实际导入者，不整理其他模块。原 `components/` 根目录的三个文件移到上述子目录，不留转发文件。

## 修改顺序与接口

1. 确认范围，冻结列表信息和操作入口。
2. 补充列表专用类型／序列化，将 PATCH 改为姓名更新，覆盖旧启停请求被拒绝的用例。
3. 整理成员组件，完成列表、搜索与姓名编辑，删除启停菜单及请求；保留已有表单、删除行为。
4. 接入团队看板入口，验证返回条件；更新受移除功能影响的登录配置提示。
5. 新增清理命令及升级说明，在隔离数据中验证历史停用员工的删除和关联资料保留。
6. 完成相关模块和浏览器流程检查，再由新的独立验收 Agent 验收。

GET `/members` 保持 `{ items: [...] }` 形状，每项新增 `createdAt`。PATCH 仅可传 `{ name }`；空对象、`null`、非法姓名及 `active` 均返回校验错误。原创建、重置和删除接口不变。前后端一起发布，旧页面的启停请求必须明确失败，不保留成功但未操作的兼容假象。

## 验证计划

本次写 Spec 为 S0，只检查文档和引用。实施涉及公共 API、持久化和权限边界，按 S3 选择成员／认证相关检查，不默认执行全项目或真实模型测试。

- Web：成员表单、列表 DOM、请求契约及 Web 类型检查；覆盖搜索、无结果、取消、错误、重复提交、成功刷新和返回状态，确认无启停入口或请求。
- 后端：新增成员管理与输入校验用例，连同既有成员删除、相关认证／会话用例。验证姓名更新不改变密码、会话、状态或汇报安排；旧启停调用、越权请求均拒绝。历史停用和已删除账号仍无法登录。
- 浏览器：在隔离测试账号完成添加、改名、搜索、查看工作、返回、重置、删除、重建；检查浅／深色和桌面／手机截图。替换已取消功能的流程断言，保留删除、会话撤销和历史资料验证。
- 依赖启停 API 构造数据的既有认证／历史测试，改为测试夹具设置历史状态，不删除这些边界测试；按实际引用同步涉及测试文件。
- 清理：混合正常员工、停用员工、管理员、已删除账号及多个公司的夹具；验证选取准确、公司边界、会话和绑定回收、工作／报告保留、同账号名重建、重复执行与中断续跑。关联文件失败进入原重试队列，不物理删除历史成员行。
- 故障：请求失败、慢响应、连续点击、对象已被删除；表单输入不丢、无错误成功提示、不重复提交。
- 不使用真实员工账号做破坏性操作。未运行项目如实列出，不以模拟测试代替真实 API 流程。

## 风险与迁移

- 使用一次性 CLI 数据清理，不在数据库结构迁移里复制删除逻辑，也不在每次启动时扫描账号。升级时执行并核对结果；处理前在事务内重新核对员工角色和停用、未删除条件。
- 保留 `active` 存储及认证检查；旧客户端启停请求明确失败，历史账号不能因入口移除而恢复登录。
- 当前为完整列表上的前端分页；若将来改为后端分页，搜索和计数需同时迁至后端，不能仅对当前页搜索或统计。
- 姓名变化不重写历史快照；成员 ID、已有归属及账号名称保持稳定。
- 无结构迁移、无新依赖；包含一次历史账号数据清理。PATCH 请求能力发生变化，发布和回滚配套前后端版本。代码回滚不会恢复已删除账号及已清理文件，按既有部署备份流程保留恢复条件。
