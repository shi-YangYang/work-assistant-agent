# 安装与部署指南

员工使用公司已部署的 Web，只需浏览器和管理员提供的账号。

源码运行需要 Node.js 24、npm 11、Python 3.12，先获取代码并执行 `npm ci`。下列命令默认在仓库根目录执行。

## 公司 Web

准备 Docker Desktop（或 Docker Engine＋Compose）和 FFmpeg，再初始化 Python 环境。

macOS／Linux：

```sh
python3.12 -m venv .venv-server
.venv-server/bin/python -m pip install -r apps/server/requirements.lock
cp apps/server/.env.web.example apps/server/.env.web
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv-server
.venv-server\Scripts\python.exe -m pip install -r apps/server/requirements.lock
Copy-Item apps/server/.env.web.example apps/server/.env.web
```

`apps/server/.env.web` 只在首次创建，勿覆盖已有配置。设置随机 `POSTGRES_PASSWORD` 并同步 `DATABASE_URL`；FFmpeg 不在 PATH 时，用 `PAA_FFMPEG` 指定可执行文件。

启动 Docker 后初始化数据库和管理员：

```sh
docker compose --env-file apps/server/.env.web -f deploy/company/compose.dev.yml up -d --wait
npm run db:company
node scripts/company/run.mjs model-key
npm run admin:company
```

`model-key` 不覆盖已有密钥；`admin:company` 创建首家公司和管理员，无默认账号。已有环境升级需停服务、备份数据库与附件、更新依赖，再执行迁移，无需重建账号或模型配置。

初始化完成后启动：

```sh
npm run dev:web
```

访问 [http://127.0.0.1:5174](http://127.0.0.1:5174)。该命令启动 Web、API、worker；Python 修改后需重启。`Ctrl+C` 停止应用，数据库继续运行；下次启动前用 Compose 确认数据库就绪。

### 发送与查看附件

工作助手支持选择、粘贴、拖入附件，可混发图片、文档与一段语音。每条最多 4 个附件、合计 20 MiB；单图最多 5 MiB／2,000 万像素，语音最长 3 分钟。支持 MP3、HEIC／HEIF；HEIC 预览会上传转换，发送时复用，不创建聊天消息。

图片可放大，PDF 可翻页和下载。XLSX 读取可见单元格及已有公式结果，不重算；不识别隐藏内容、扫描件、图表和嵌入图片。

### 公司声纹

管理员在“系统设置 → 公司声纹”登记员工单人录音，须经本人知情同意。建议 30～120 秒，最长 3 分钟、最大 20 MiB，中英文均可；替换失败保留原声纹。

本地安装独立 CPU 声纹环境：

```sh
python3.12 scripts/company/install-voiceprints.py
```

Windows 使用 `py -3.12 scripts/company/install-voiceprints.py`。脚本创建 `.venv-voiceprints`，不影响 `.venv-server`；也可用 `PAA_VOICEPRINT_PYTHON` 指定已装依赖的解释器。生产 worker 镜像已包含 CPU 环境与权重。

## Electron 桌面端

macOS：

```sh
python3.12 -m venv .venv
node scripts/desktop/install-python.mjs
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
node scripts/desktop/install-python.mjs
```

桌面使用 `.venv`，公司使用 `.venv-server`，无需手动激活；不替换系统 Python。

```sh
npm run dev:electron
```

在“本地转写模型”下载模型后可离线转写；在“模型服务管理”配置在线纪要 API。

“本地转写模型 → 推理设备”显示硬件并支持 CPU／GPU 切换，默认优先可用 GPU，之后保留用户选择。Apple Silicon 使用 Metal，需下载独立 GPU 模型；Windows 需要兼容 NVIDIA 显卡、驱动、CUDA 12 和 cuDNN 9，其他情况可用 CPU。

设备选择只影响新建或重转写任务，已有任务保持原配置。CPU／GPU 的错误率与内存实测分别展示。

麦克风不可用时，到系统隐私设置允许访问后重启。开发版和安装版使用同一资料目录时，不要同时运行。

### 连接公司与离线识别

复制 `apps/desktop/.env.electron.example` 为同目录 `.env.electron`，设置 `PAA_DESKTOP_COMPANY_URL=https://公司地址`。已有配置只补此项；修改后重启开发进程或重新打包，安装后的客户端不会读取环境文件更新。

只将公开地址写入桌面主进程，不打包环境文件或其他配置。地址留空为游客，不加载旧登录及声纹；配置后只恢复同地址缓存。生产使用员工可访问的 HTTPS 地址。

在“公司连接”登录，系统浏览器确认账号后，管理员可同步声纹。连接失败或网络恢复后可直接重试。联调使用 `http://127.0.0.1:5174` 并另启 `npm run dev:web`；本地会议本身不需要后端。

姓名匹配不足时保留说话人编号，可人工纠正。已同步声纹长期离线可用，更新需在线验证；退出账号或清缓存会移除声纹，不删除会议。

## Web 部署

[生产 Compose](../deploy/company/compose.yml) 在 Linux 运行 Caddy、API、worker 和 PostgreSQL，启动前执行迁移。Web／API 同源 HTTPS，数据库不暴露公网；聊天和 ASR 调用外部服务。

部署前准备固定公网 IPv4 或域名、Docker Compose 和 `apps/server/.env.web`：

- 持续开放 TCP 80／443，用于访问、签发和续期。仅 Web 暴露端口，API／数据库留在 Compose 内网。
- `PAA_DOMAIN` 填域名或公网 IPv4，`PAA_WEB_ORIGIN=https://同一主机`，不带路径或末尾斜线；生产启用 Secure Cookie。
- 设置数据库随机密码；在仓库与镜像之外创建一次 **32 字节随机主密钥文件**，所属 UID 为 `10001`、权限为 `600`。
- 将 `PAA_MODEL_KEY_HOST_PATH` 指向该文件的绝对路径。API 与 worker 只读共享它，文件缺失时不会自动创建；升级时不能重新生成。

### 域名部署

将域名解析到服务器，按以下命令启动。Caddy 自动申请并续期域名证书：

```sh
docker compose --env-file apps/server/.env.web -f deploy/company/compose.yml up --build -d
docker compose --env-file apps/server/.env.web -f deploy/company/compose.yml exec api python -m app.cli bootstrap-admin
```

### 公网 IP 部署

IP 部署使用固定公网 IPv4 和 [IP Compose 配置](../deploy/company/compose.ip.yml)。只把 IP 填入默认域名配置会得到浏览器不信任的证书。

服务器需 Python 3 venv（Ubuntu 可安装 `python3-venv`）。证书保存在仓库外，Caddy 只读挂载整个 `/etc/letsencrypt`，包括符号链接目标。

```sh
sudo python3 -m venv /opt/paa-certbot
sudo /opt/paa-certbot/bin/pip install 'certbot==5.4.0'
sudo install -d -m 700 /etc/letsencrypt
sudo install -d -m 755 /var/lib/paa-acme /var/lib/letsencrypt

# 首次仅启动 HTTP 验证文件服务；此配置不提供业务页面或 API。
PAA_IP_CADDY_CONFIG=Caddyfile.ip-bootstrap docker compose --env-file apps/server/.env.web \
  -f deploy/company/compose.yml -f deploy/company/compose.ip.yml up --build -d --no-deps web
```

替换维护邮箱和公网 IP，先用测试 CA 验证，再申请生产证书：

```sh
sudo /opt/paa-certbot/bin/certbot certonly --dry-run --non-interactive --agree-tos \
  --email '维护邮箱' --cert-name paa-ip --preferred-profile shortlived \
  --webroot --webroot-path /var/lib/paa-acme --ip-address '固定公网IPv4'
sudo /opt/paa-certbot/bin/certbot certonly --non-interactive --agree-tos \
  --email '维护邮箱' --cert-name paa-ip --preferred-profile shortlived \
  --webroot --webroot-path /var/lib/paa-acme --ip-address '固定公网IPv4'

# 证书存在后切换到 HTTPS，并启动业务服务；不要持久设置 bootstrap 变量。
docker compose --env-file apps/server/.env.web -f deploy/company/compose.yml \
  -f deploy/company/compose.ip.yml up --build -d
docker compose --env-file apps/server/.env.web -f deploy/company/compose.yml \
  -f deploy/company/compose.ip.yml exec api python -m app.cli bootstrap-admin
```

IP 证书有效期 6 天，必须自动续期。使用[续期脚本](../deploy/company/ip-certificate.sh)处理证书重载和失败重试，不能仅依赖 Certbot 的退出码。

```sh
# 此步骤需要服务器公网 80 可达；验证续期及 hook，不替换正在使用的生产证书。
sudo deploy/company/ip-certificate.sh renew --dry-run --run-deploy-hooks
# 如需单独重载已有证书：
sudo deploy/company/ip-certificate.sh reload
```

在 root crontab（`sudo crontab -e`）配置每日两次检查，替换绝对路径并确保 cron 运行。保留错误输出，监控续期失败和到期时间：

```cron
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 3,15 * * * /绝对路径/work-assistant-agent/deploy/company/ip-certificate.sh renew
```

部署后从公司网络和手机流量验证 HTTPS 无警告、钉钉回调和录音。切换域名时停止 IP 续期任务，更新域名解析、环境地址及钉钉回调，用域名 Compose 重建；保留数据卷和主密钥，用户重新登录。

### GitHub 手动发布

在 GitHub **Actions → Deploy Company Web → Run workflow** 手动发布。Branch 选 `main`，`commit` 留空或填 main 历史中的完整 SHA；`mode` 选 `domain`／`ip`。PR、push 和合并不触发部署。

GitHub 通过 SSH／rsync 增量上传源码，每次建立独立版本目录并复用完整旧版文件；首次全量上传，中断不进入构建。服务器串行构建 API、worker、Web，不打包 Electron，不使用镜像仓库账号。所选版本须包含 `deploy/company/build.sh`。

**一次性配置 GitHub：**

在仓库 **Settings → Secrets and variables → Actions** 添加四项 Secrets，无需 Environment 或 Variables：

| Secret | 内容 |
| --- | --- |
| `DEPLOY_HOST` | 服务器公网 IPv4 或主机名 |
| `DEPLOY_USER` | 部署用户，能够运行 Docker、读写部署目录 |
| `DEPLOY_SSH_KEY` | 专用无口令 SSH 私钥，对应公钥安装在部署用户的 authorized_keys |
| `DEPLOY_KNOWN_HOSTS` | 已核对服务器指纹的 SSH known_hosts 记录 |

默认 SSH 端口 `22`，目录 `/srv/work-assistant-agent`；修改位置为工作流的 `DEPLOY_PORT`／`DEPLOY_PATH`。有仓库写权限的维护者可从 main 手动发布。

**一次性准备服务器：**

1. Linux x86_64，安装 Docker Engine、Buildx、Compose ≥2.24.4、Bash、Python 3、rsync、curl、flock 和 GNU coreutils。确认 `docker buildx version` 正常、GitHub runner 可 SSH 连接、服务器可下载镜像和依赖。腾讯云可在 Docker `registry-mirrors` 中加入 `https://mirror.ccs.tencentyun.com`，保留已有配置。
2. 部署用户可读写部署目录。创建 `apps/server/.env.web` 并设权限 `600`，准备主密钥、HTTPS 和钉钉回调；IP 模式先完成证书申请和续期。CD 不生成主密钥或自动签署证书协议。
3. 默认使用腾讯云 Debian／PyPI、npmmirror npm、南京大学 PyTorch CPU 源。地址在 `deploy/company/Dockerfile` 的 `ARG` 中，依赖锁和 HTTPS 校验保留；不改开发机源，不安装 CUDA。
4. 首次发布后创建管理员：`sh /srv/work-assistant-agent/current/deploy/company/compose.sh exec api python -m app.cli bootstrap-admin`。

发布顺序：构建镜像／拉取 PostgreSQL → 检查配置和密钥 → 停写备份 → 迁移 → 启动 → 检查 HTTPS、数据库与 worker。备份位于部署目录 `backups/`、`key-backups/`，需另外异机保存。

首次构建下载依赖，后续复用 Docker 缓存；构建会占用服务器资源。工作流超时 60 分钟，服务器发布超时 50 分钟。镜像按本地 image ID 固定，勿清理 `current/`、`previous/` 引用的镜像。

`current/` 指向本次尝试，`previous/` 保留旧版本，结果在 `deployment-status`。构建／配置检查失败不停止旧服务，备份失败尝试恢复旧服务；迁移或上线检查失败则停用应用并保留数据，不自动启动旧代码。schema 变化须按备份恢复，不能只切旧镜像。排障命令：`sh /srv/work-assistant-agent/current/deploy/company/compose.sh logs --tail=100 api worker migrate`。

旧手工部署接入 CD 时沿用部署根目录、`.env.company`、主密钥和 `paa-company` 数据卷；发布脚本将旧配置链接到新版本 `apps/server/.env.web`。续期 cron 和日常备份改用 `current/deploy/company/` 下的脚本。

### 钉钉登录配置

1. 取得企业内部应用开发管理权限，可管理凭证、接口权限、可用范围、安全设置和发布。
2. 创建企业内部应用，取得 **CorpId、AppKey／Client ID、AppSecret／Client Secret**；开通 `open_app_api_base`、`Contact.User.Read`、`qyapi_get_member` 并发布。通讯录授权与应用可用范围均限于允许登录的员工，无需考勤、审批或消息权限。
3. 回调为 **`PAA_WEB_ORIGIN` + `/api/v1/auth/dingtalk/callback`**；在实际应用后台登记并验证，尤其是公网 IP 回调。
4. 单公司可留空 `PAA_LOGIN_COMPANY_ID`；多公司须在 `apps/server/.env.web` 指定公司 UUID 并重启 API，否则钉钉入口关闭。
5. 在“系统设置 → 登录方式”保存配置、试登录后开启入口；Secret 留空保留原值。凭证、授权码、Token 和回调查询参数不入 Git、截图或日志。

首次登录为已核验且允许的成员创建员工账号；已有账号需主动验证绑定，不按姓名合并，钉钉管理员不自动成为系统管理员。用户可设置本地密码；关闭钉钉前确认所需密码可用。阻止再次登录应停用账号，以撤销会话并禁止重新开户。

停用可恢复；删除撤销登录、停止待处理任务和提醒，保留历史业务，释放账号名及钉钉绑定。重建账号不继承旧资料；历史记录在团队看板的全部／停用成员范围查看。

上线验证首次开户、再次登录、密码设置、外部及范围外成员拒绝，并用实体手机验证授权返回。

登录后配置模型用途。手机录音需要有效 HTTPS，局域网 HTTP 不满足条件，锁屏后不保证持续录音。

### 使用问题与反馈

在“问题反馈”描述操作和现象，管理员跟进处理。诊断只附请求编号、错误类型和浏览器信息，不自动附聊天、文件或密钥；服务不可用时可复制反馈。

发送超时先恢复原消息状态，不自动重发。会话过期后，同页面的草稿可在原账号重新登录后恢复；刷新、关页或切换账号不保留。

按请求编号查 API 日志，日志不含业务正文。手机检查覆盖 Safari／Chrome 的真实键盘、权限和录音，不只看窄屏模拟。

### 后台处理与汇报安排

生产 worker 及子进程合计上限为 2 核、3 GiB，禁用 swap；超出 CPU 会限速，超内存可能 OOM。此限制不约束镜像构建。

`PAA_WORKER_CONCURRENCY` 默认 `3`，范围 `1～8`；不同员工并行，同员工串行，仅运行一个 worker。提高并发需检查模型限流与内存。

每个处理槽一个 checkpoint 连接，另有进程锁连接和两个最多各 3 个连接的 API／worker 事务池；并发 8 时最多 15 个连接，PostgreSQL 上限 20，须留运维余量。语音转换每进程最多 2 个；退出等候 10 秒，Compose 留 20 秒。结果未知的已发送模型请求由用户确认重试，未发出的可恢复排队。

汇报待办从规则生效后的周期产生，不追补旧欠交；新成员和规则变化不改既有截止时间。停机恢复分批补待办及站内提醒，不集中调用模型。

提醒在员工登录后可见，不做站外推送；已读不等于提交，提交后停止催交。报告由服务端校验四个栏目并保存，失败可重试或手填，仍需本人审阅提交。

### 备份与恢复

升级前设置两个独立私有目录：`PAA_BACKUP_DIR` 存数据库／附件，`PAA_MODEL_KEY_BACKUP_DIR` 存主密钥，再从仓库根运行：

```sh
sh deploy/company/backup.sh
```

脚本停写后保存数据库 dump、全部私有附件、镜像信息和校验文件，再恢复服务。业务备份保留最近 7 份，主密钥独立保存；两类备份分别复制到受控异机位置。

恢复先验证两处 `SHA256SUMS`，停写后用对应镜像导入空库、还原附件，安装同批主密钥（UID `10001`／权限 `600`），核对再启动。勿直接降级 schema；主密钥丢失时旧凭证无法恢复，须撤销并重新配置。

## 桌面打包

完成桌面开发环境安装后，在对应系统与架构执行：

```sh
node scripts/desktop/install-build-python.mjs
npm run package
```

产物位于 `dist/desktop/`：macOS ARM64 为 DMG，Windows x64 为 NSIS。安装包内置 Python、录音与转写依赖；模型仍由用户在应用内下载。`npm run package:dir` 只生成应用目录。

尚无正式签名、公证和自动更新。macOS 切换开发版／安装版或重建后可能请求钥匙串授权；安装和卸载保留用户资料。

## 数据存放

| 内容 | 位置 |
| --- | --- |
| macOS 桌面资料 | `~/Library/Application Support/个人工作助手/` |
| Windows 桌面资料 | `%APPDATA%/个人工作助手/` |
| 公司业务数据 | PostgreSQL；原始附件在共享私有目录，生产环境默认使用 Docker 卷 |
| 公司密钥 | 数据库保存密文，主密钥单独保管；本地默认为 `data/company/model-master.key` |

桌面备份须关闭应用并复制整个资料目录；公司备份保留数据库、附件及独立主密钥。环境文件、密钥和业务资料不入 Git。
