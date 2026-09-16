# 安装与部署指南

本文适用于自行运行或部署项目的人。员工使用已部署的公司 Web，只需浏览器和管理员提供的账号。

所有命令均在仓库根目录执行；先按 [README](../README.md#安装) 安装 Node.js 24、npm 11、Python 3.12 并获取代码。

## 公司 Web

准备 Docker Desktop（或 Docker Engine＋Compose）和 FFmpeg，再初始化 Python 环境。

macOS／Linux：

```sh
python3.12 -m venv .venv-server
.venv-server/bin/python -m pip install -r services/company/requirements.lock
cp .env.company.example .env.company
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv-server
.venv-server\Scripts\python.exe -m pip install -r services/company/requirements.lock
Copy-Item .env.company.example .env.company
```

仅首次创建 `.env.company`；已有配置不要覆盖。编辑其中的 `POSTGRES_PASSWORD` 为长随机字母数字密码，并同步 `DATABASE_URL`。FFmpeg 不在 PATH 时设置 `PAA_FFMPEG` 为其可执行文件路径。

先启动 Docker，再依次执行；`--wait` 会等待数据库健康后返回：

```sh
docker compose --env-file .env.company -f deploy/company/compose.dev.yml up -d --wait
npm run db:company
node scripts/company/run.mjs model-key
npm run admin:company
```

`model-key` 初始化本地私有主密钥，不覆盖已有文件；`admin:company` 交互创建首家公司和管理员，不提供通用默认账号密码，也不会覆盖已有公司。已有环境升级时，先停服务并备份数据库与附件，更新依赖后执行 `npm run db:company`，无需重新创建账号或模型配置。

初始化完成后启动：

```sh
npm run dev:company
```

访问 [http://127.0.0.1:5174](http://127.0.0.1:5174)。命令同时启动 Web、API 和后台任务；修改 Python 代码后重启，`Ctrl+C` 停止应用，数据库继续运行。下次使用前可重新执行上面的 Compose 命令，确保数据库已启动。

### 发送与查看附件

在工作助手选择文件、粘贴截图或拖入本地文件；可将图片、文档与一段语音放在同一条消息中。每条最多 4 个附件、合计 20 MiB，单图最多 5 MiB／2,000 万像素，语音最长 3 分钟。支持 MP3 与 HEIC／HEIF 照片；HEIC 点击“生成预览”后上传到公司服务转换，发送时复用，不会因预览创建聊天消息。

点击图片可放大查看，PDF 可翻页预览并下载原件。Excel 支持 XLSX 中的可见单元格，保留公式及文件已有的结果，不重新计算。隐藏内容、扫描件文字、图表和嵌入图片不作为已识别内容。

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

桌面使用 `.venv`，公司服务使用 `.venv-server`，均不需要手动激活。解释器命令名称不同时，用对应的 Python 3.12 创建环境，不替换系统 Python。

```sh
npm run dev
```

首次使用时，在“本地转写模型”下载模型，在“模型服务管理”配置纪要模型。转写模型下载后可离线使用，在线纪要需要模型 API。

“本地转写模型 → 推理设备”可切换 CPU／GPU，并显示检测到的硬件名称。首次优先使用可用 GPU，不支持时使用 CPU；之后保留你的选择。Apple Silicon 使用内置的 Metal 推理组件，首次切换需下载对应 GPU 模型，已有 CPU 模型保留。Windows GPU 需要兼容的 NVIDIA 显卡、驱动、CUDA 12 和 cuDNN 9；缺少运行库或使用 AMD／Intel 显卡时仍可使用 CPU。

设备选择作用于新建或重新转写的任务，已有任务继续使用原配置。CPU 和 GPU 的错误率、内存占用可能不同，页面不会将 CPU 实测结果当作 GPU 数据。

麦克风不可用时，到系统隐私设置允许访问后重启。开发版和安装版使用同一资料目录时，不要同时运行。

## Web 部署

[生产 Compose](../deploy/company/compose.yml) 在 Linux 上运行 Caddy、API、worker 和 PostgreSQL，自动先执行数据库迁移。Web 与 API 同源，通过 HTTPS 提供访问；数据库不暴露公网端口。服务器调用外部 AI／ASR API，不部署桌面的 faster-whisper。

部署前准备固定公网 IPv4 或域名、Docker Compose 和 `.env.company`：

- 开放公网 TCP 80／443；仅 Web 暴露端口，API 和数据库保持在 Compose 内网。80 端口还用于证书首次签发和续期，不能只在首次申请时开放。
- `PAA_DOMAIN` 填访问主机（沿用原变量名，也可填公网 IPv4）；`PAA_WEB_ORIGIN=https://同一个主机`，不带路径或末尾斜线。生产 Compose 强制启用 Secure Cookie。
- 设置数据库随机密码；在仓库与镜像之外创建一次 **32 字节随机主密钥文件**，所属 UID 为 `10001`、权限为 `600`。
- 将 `PAA_MODEL_KEY_HOST_PATH` 指向该文件的绝对路径。API 与 worker 只读共享它，文件缺失时不会自动创建；升级时不能重新生成。

### 域名部署

将域名解析到服务器，按以下命令启动。Caddy 自动申请并续期域名证书：

```sh
docker compose --env-file .env.company -f deploy/company/compose.yml up --build -d
docker compose --env-file .env.company -f deploy/company/compose.yml exec api python -m paa_server.cli bootstrap-admin
```

### 公网 IP 部署

无需先购买域名。`.env.company` 中将 `PAA_DOMAIN` 设为固定公网 IPv4，`PAA_WEB_ORIGIN` 设为 `https://该IP`，再使用 [IP Compose 配置](../deploy/company/compose.ip.yml)。不要只把 IP 填进默认域名配置：当前 Caddy 版本的默认 IP 证书不受员工浏览器信任。

以下在 Linux 服务器执行，使用系统 Python 3 的 venv 支持（Debian／Ubuntu 可安装 `python3-venv`）与固定版本 `certbot==5.4.0`。证书与私钥保留在仓库之外；Caddy 只读挂载整个 `/etc/letsencrypt`，包含 `live/` 指向 `archive/` 的符号链接目标。

```sh
sudo python3 -m venv /opt/paa-certbot
sudo /opt/paa-certbot/bin/pip install 'certbot==5.4.0'
sudo install -d -m 700 /etc/letsencrypt
sudo install -d -m 755 /var/lib/paa-acme /var/lib/letsencrypt

# 首次仅启动 HTTP 验证文件服务；此配置不提供业务页面或 API。
PAA_IP_CADDY_CONFIG=Caddyfile.ip-bootstrap docker compose --env-file .env.company \
  -f deploy/company/compose.yml -f deploy/company/compose.ip.yml up --build -d --no-deps web
```

用真实公网 IP 和维护邮箱替换下列占位值。先验证 ACME 网络可达性；`--dry-run` 使用测试 CA，不保存或部署不受信的测试证书。成功后执行第二条申请生产证书：

```sh
sudo /opt/paa-certbot/bin/certbot certonly --dry-run --non-interactive --agree-tos \
  --email '维护邮箱' --cert-name paa-ip --preferred-profile shortlived \
  --webroot --webroot-path /var/lib/paa-acme --ip-address '固定公网IPv4'
sudo /opt/paa-certbot/bin/certbot certonly --non-interactive --agree-tos \
  --email '维护邮箱' --cert-name paa-ip --preferred-profile shortlived \
  --webroot --webroot-path /var/lib/paa-acme --ip-address '固定公网IPv4'

# 证书存在后切换到 HTTPS，并启动业务服务；不要持久设置 bootstrap 变量。
docker compose --env-file .env.company -f deploy/company/compose.yml \
  -f deploy/company/compose.ip.yml up --build -d
docker compose --env-file .env.company -f deploy/company/compose.yml \
  -f deploy/company/compose.ip.yml exec api python -m paa_server.cli bootstrap-admin
```

IP 证书有效期为 6 天，必须配置自动续期。[续期脚本](../deploy/company/ip-certificate.sh) 用 deploy hook 在签发成功后执行 `caddy reload --force`，以相同路径重新读取证书；重载失败会返回失败并保留标记，下次运行会先重试。Certbot 自身可能在 hook 失败时返回 0，因此定时任务要调用该脚本。

```sh
# 此步骤需要服务器公网 80 可达；验证续期及 hook，不替换正在使用的生产证书。
sudo deploy/company/ip-certificate.sh renew --dry-run --run-deploy-hooks
# 如需单独重载已有证书：
sudo deploy/company/ip-certificate.sh reload
```

在 root 的 crontab（`sudo crontab -e`）加入下面一行，把仓库绝对路径换成实际位置；主机须安装并运行 cron。每天两次检查，未到续期时间不会重新申请。保留任务错误输出，并由运维监控续期失败与证书到期；不要丢弃到 `/dev/null`。

```cron
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 3,15 * * * /绝对路径/work-assistant-agent/deploy/company/ip-certificate.sh renew
```

部署后从公司网络与手机流量访问 `https://该IP`，确认浏览器无证书警告，再验证钉钉回调和录音。自签证书／本地配置检查不能替代此步骤。以后切换域名时，停止这条 IP 续期任务，将域名解析到同一服务器，更新 `PAA_DOMAIN`、`PAA_WEB_ORIGIN` 及钉钉回调，改用上面的域名 Compose 命令重建服务；保留数据库、附件卷及主密钥，账号和业务数据不需重建，员工在新地址重新登录。

依据：[Let’s Encrypt 的 IP 证书与 Certbot 说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)、[Certbot 续期与 hook](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates)、[Caddy 强制重载](https://caddyserver.com/docs/command-line#caddy-reload)。

### 钉钉登录配置

1. 请公司钉钉主管理员授予「应用开发子管理员」，或由管理员创建企业内部应用并授予开发管理权限；需要管理应用凭证、接口权限、可用范围、安全设置与发布。
2. 在钉钉开发者后台创建企业内部应用，取得企业 **CorpId**、应用 **AppKey／Client ID** 与 **AppSecret／Client Secret**。在「开发配置 → 权限管理」开通基础访问凭证权限 `open_app_api_base`、个人信息读权限 `Contact.User.Read` 和成员信息读权限 `qyapi_get_member`，供登录及核验企业成员。确认审批通过后发布应用版本。将**通讯录授权范围限定为允许登录的员工**，并与应用可使用范围保持一致；工作台可见性不能替代服务端成员准入校验。不需要考勤、审批或消息权限。
3. 登记回调地址 **`PAA_WEB_ORIGIN` + `/api/v1/auth/dingtalk/callback`**，并发布给目标员工。公网 IP 回调是否被实际钉钉应用接受须在后台登记并实测；本机调试成功不代表生产 IP 回调已通过。
4. 如果部署数据库只有一家公司，可留空 `PAA_LOGIN_COMPANY_ID`；多公司部署必须在 `.env.company` 指定试点公司的 UUID，重启 API 后生效。未指定且存在多家公司时，公共钉钉入口关闭，不会自动选第一家公司。
5. 本系统管理员在「系统设置 → 登录方式」填写并保存应用配置，再进行试登录，验证成功后开启入口。Secret 留空保留原值；不要将 Secret、授权码、Token 或完整回调地址查询参数写入 Git、截图或日志。「已保存」仅表示字段已保存，不能当作真实授权成功。

首次允许范围内的成员登录会创建员工账号；已有账号应先在「账户」验证身份并主动绑定，系统不按姓名合并，也不把钉钉管理员自动提升成本系统管理员。钉钉新账号可按需在账户中设置本地密码；密码登录入口始终保留。停用钉钉前先确认管理员密码可用，并为需要密码登录的员工设置密码。离职或收回权限时还需停用本系统账号，以撤销本地密码与已有会话访问。

取得应用权限、凭证和公网服务器后，实际验证首次开户、再次登录、密码设置、外部人员及授权范围外成员拒绝，并在实体手机验证授权与返回。当前缺少这些条件时，只能完成软件验证。依据：[钉钉应用权限配置](https://help.aliyun.com/zh/agentcore/agentcore-configure-dingtalk-account-integration)、[官方第三方网站登录教程](https://open.dingtalk.com/document/orgapp-server/tutorial-obtaining-user-personal-information)。

部署完成后登录 Web 配置模型用途。手机录音需要有效 HTTPS，访问开发电脑的局域网 HTTP 地址不满足条件，也不保证锁屏后持续录音。

### 使用问题与反馈

在“问题反馈”描述操作和遇到的现象；管理员可查看本公司反馈并填写处理结果。错误提示也可进入反馈，附带请求编号、错误类型及浏览器信息，不自动附带聊天、文件或模型密钥。服务不可用时可复制反馈信息，交给维护者。

请求超时并不代表服务端没有收到。聊天发送结果不确定时，使用原消息的恢复／重试入口；联网后页面会恢复读取状态，不会自动重发消息。登录过期后，同一页面内的未发送聊天内容可在原账号重新登录后恢复；刷新、关闭页面或切换账号不保留。

维护者可按反馈中的请求编号查找 API 请求日志，日志使用路由模板、状态和耗时，不包含业务正文。手机优先检查 Safari／Chrome；窄屏模拟不能替代实体手机的软键盘、权限和录音操作验证。

### 后台处理与汇报安排

`PAA_WORKER_CONCURRENCY` 默认 `3`，可设 `1～8`；不同员工并行，同一员工串行。当前部署只运行一个 worker，重复启动会退出，避免意外放大请求量。提高并发前应确认模型服务限流与服务器内存；此范围不是容量承诺。

每个处理槽使用独立 checkpoint 连接；worker 另有 1 个进程锁连接，数据库短事务池最多 3 个连接，API 事务池最多 3 个连接。并发为 8 时这些常驻组件最多使用 15 个连接；现有 PostgreSQL 上限为 20，运维／迁移另需余量。语音转换每个进程最多同时 2 个，关闭时最多等 10 秒处理在途任务，然后取消并回收；Compose 留 20 秒退出窗口。已发送而结果未知的模型请求需用户确认重试，未发出的任务可恢复排队。

升级至 `0007_report_obligations` 前先备份，停止旧 API／worker，再迁移并启动新版本，避免两代调度同时工作。现有汇报规则与报告保持不变；待办从升级后的下一个日报／周报周期开始，不补旧欠交。新成员与规则变更同样从后续周期生效；已产生的截止时间保留原安排。停机恢复会分批补待办及站内提醒，过期周期不集中调用模型。

提醒保存在服务端；员工下次登录可见，未打开网页时不发送系统推送。已读不等于提交，正式提交后停止催交。报告生成一次调用后由服务端检查四个栏目并保存，失败可重试或手动填写，仍需员工审阅提交。

### 备份与恢复

升级前设置两个独立私有目录：`PAA_BACKUP_DIR` 存数据库／附件，`PAA_MODEL_KEY_BACKUP_DIR` 存主密钥，再从仓库根运行：

```sh
sh deploy/company/backup.sh
```

脚本会暂停写入服务，保存 PostgreSQL dump、整个私有附件目录（含图片预览等派生文件）、镜像信息与校验文件，然后恢复服务；业务备份保留最近 7 份，密钥备份独立保存。运维需将两类备份分别复制到受控异机位置。

恢复时验证两处 `SHA256SUMS`，停止写服务，用对应镜像将 dump 导入空库、还原附件，并安装同一时间戳的主密钥（UID `10001`／权限 `600`），核对后再启动。不要把新 schema 直接降级。主密钥丢失后旧凭证不可恢复，应先保留业务备份、撤销旧服务，再重新配置凭证。

## 桌面打包

完成桌面开发环境安装后，在对应系统与架构执行：

```sh
node scripts/desktop/install-build-python.mjs
npm run package
```

产物位于 `dist/desktop/`：macOS ARM64 为 DMG，Windows x64 为 NSIS。安装包内置 Python、录音与转写依赖；模型仍由用户在应用内下载。`npm run package:dir` 只生成应用目录。

当前为测试分发，尚未接入正式签名、公证和自动更新。macOS 开发版与安装版切换或重新构建后，系统可能请求“个人工作助手 Safe Storage”钥匙串访问授权。安装与卸载不会清除用户会议、模型和服务配置。

## 数据存放

| 内容 | 位置 |
| --- | --- |
| macOS 桌面资料 | `~/Library/Application Support/个人工作助手/` |
| Windows 桌面资料 | `%APPDATA%/个人工作助手/` |
| 公司业务数据 | PostgreSQL；原始附件在共享私有目录，生产环境默认使用 Docker 卷 |
| 公司密钥 | 数据库保存密文，主密钥单独保管；本地默认为 `data/company/model-master.key` |

桌面备份前关闭应用，复制整个资料目录，包含数据库、录音、模型和配置。公司备份按上面的“备份与恢复”操作，同时保留数据库、附件和独立主密钥。不要将 `.env.company`、密钥或业务资料提交到 Git。
