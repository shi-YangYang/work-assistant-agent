# 实施计划

## 边界与分工

三块按下列接口分开实施，禁止交叉编辑；协调者整合，另由新的 Agent 独立验收。

1. 公司服务／Web：`services/company/`、`apps/web/`、`tests/server/`、`tests/web/`、`deploy/company/`、`scripts/company/`、`packages/api-contracts/`。负责迁移、浏览器桌面授权、声纹登记／管理／同步与真实 CPU 提取运行条件。
2. 桌面连接：`apps/desktop/src/`、`tests/desktop/`；负责 main 网络／安全存储、IPC、公司设置和浏览器授权轮询，不编辑 Python。现有 keychain identity 保持不变。
3. 声纹引擎／本地核心：`packages/voiceprint-engine/`、`apps/desktop/core/`、`tests/core/`、`scripts/benchmarks/`、桌面 Python 打包脚本；负责登记和匹配共用的固定特征算法、实时后台处理、人工修正和会后整合，以及真实样本验证。

## 公司 API 契约

所有路径以 `/api/v1` 为前缀。新桌面专用端点不放宽现有 Web Cookie／CSRF／Origin 防护，不接受 Web Cookie 代替桌面 bearer。请求体只含指定字段，错误沿用现有 error envelope。

- `GET /desktop/info` → `{protocolVersion: 1, webOrigin: string}`；webOrigin 来自服务端可信配置。main 检查协议、URL、重定向和响应大小，仅打开确认连接的服务所声明的网页。
- `POST /desktop/login/start`，`{challenge: string}`，S256 PKCE → `{requestId, expiresAt, authorizationUrl}`。服务端限速、短期有效，浏览器访问 `/desktop/connect?request=<id>`，登录后明示账号并确认授权。
- `POST /desktop/login/exchange`，`{requestId, verifier}` → pending 时 HTTP 202 `{state: 'pending'}`；成功时 `{token, expiresAt, member: {id,name,role}, company: {id,name}}`。批准、兑换一次性且原子；短期请求不可枚举或重放。浏览器批准端点使用现有 Cookie／CSRF 身份；桌面无静态 client secret。
- `GET /desktop/me`（bearer）→ `{member, company, expiresAt}`；`POST /desktop/logout`（bearer）撤销该凭证。新桌面会话与现有密码／账号撤销联动；令牌过期仅影响在线能力。
- `GET /desktop/voiceprints`（bearer 且管理员）→ `{modelId, revision, profiles: [{memberId,name,templates: number[][]}]}`。modelId 代表固定模型和预处理格式，向量维数及质量校验由共享引擎明确。revision 表示快照版本。Web 管理接口由公司实施 Agent 定义，上传最大 20 MiB／3 分钟，失败不破坏旧就绪模板。

## 共享引擎与桌面核心契约

- `packages/voiceprint-engine/` 提供可被公司提取进程与桌面核心共同调用的 Python 包；不让服务端依赖桌面业务代码。固定嵌入权重复用现有资源，部署时显式复制并校验；推理重依赖惰性加载，普通 CI 不下载模型。
- 公司后台在受限子进程执行提取，单次有超时及数量限制；部署依赖必须可安装，不把依赖错误标为成功。共享入口、modelId、向量维数由引擎实施 Agent 提前发送给公司 Agent。
- 桌面 main 保管加密凭证及公司模板缓存，renderer 仅接收身份／状态／数量。调用 core JSON Lines `voiceprints.configure`，参数 `{scope: string|null, modelId: string, profiles: [{memberId,name,templates: number[][]}]}`；空 profiles／scope null 清空当前可用模板。配置只在 core 内存生效，持久缓存由 main 管理；core 重启后重新配置。
- core `voiceprints.status` 返回 `{enabled: boolean, profileCount: number, modelId: string, state: string, error: string|null}`。状态通过 main 暴露，不输出向量。录音流识别自动跟随已有会话和转写进度；结果沿用 transcript 的 `speaker`／`speakerName` 字段，保护稳定片段 ID 与人工修订。
- main 的网络请求有超时／大小限制，默认拒绝重定向携带凭证；HTTPS 校验证书，本机开发只对 loopback 开 HTTP。切换／退出清除在途回调，防止旧请求重新写回模板。

## 验证与迁移

按 S3：新增身份认证、持久模板与迁移涉及安全边界。运行所涉及 API／core／main 的定向测试、两端类型与构建检查及修改文件的格式／lint，不自动跑全部发行包或下载 ASR 模型。相关通过项不无故重复。

迁移追加，不改旧版本；开发数据库升级前备份，自动测试只用已有独立测试库。GUI 在日常项目环境启动，保留现有密钥、模型、录音；真实模型实验使用公开语料，清理本次临时资料，不混入用户公司资料。登记和识别样本隔离，保留最小可复核指标。

无需 commit／push 或自动运行远端 CI。文档维护实际实现和必要验证，不写讨论流水账。
