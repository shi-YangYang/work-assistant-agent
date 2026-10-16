# 安装与部署指南

员工使用公司已部署的 Noria Web，只需浏览器和管理员提供的账号。

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

访问 [http://127.0.0.1:5174](http://127.0.0.1:5174)。该命令统一管理 Docker 的 `paa-company` 项目：PostgreSQL、正文流 Redis，以及可选的沙盒 control/runtime；等待健康检查通过后启动宿主机上的 Web、API、worker。请先启动 Docker；Python 修改后需重启。`Ctrl+C` 停止应用及本次启动的 Redis，数据库继续运行；原已运行的 Redis 不会被停止。配置远程数据库或非 5432 端口时跳过本地容器，由使用者确保数据库可用；同一环境只允许一个开发管理命令运行，第二个终端不会接管服务。分开运行 API／worker 时，先在 Docker Desktop 启动已经创建的 postgres、redis 服务；独立命令不管理这些依赖。

### 旧版 Office 文件读取

DOC／RTF／ODT、XLS／ODS、PPT／ODP 在发送消息后，由 worker 分别转换为 DOCX、XLSX、PPTX 再读取。上传不会触发转换，原件保留供下载和沙盒使用；PDF、新版 Office、文本与代码继续直接读取。复杂版式、图形和嵌入内容不保证完整，建议先用 Office／WPS 另存为新格式。包含宏、外部数据或活动对象，以及转换导致公式保存结果变化的文件会给出明确失败，不猜测缺失内容。

本地开发需安装 LibreOffice（macOS：`brew install --cask libreoffice`；Debian／Ubuntu：`sudo apt-get install libreoffice-writer libreoffice-calc libreoffice-impress`；Windows 安装官方桌面发行版）。将 `soffice` 加入 PATH，或设置 `PAA_OFFICE_BINARY` 为其绝对路径；macOS 默认 `/Applications/LibreOffice.app/Contents/MacOS/soffice` 也会识别。重启 worker 后只检查一次版本，未安装不会阻止普通聊天及原有格式读取。

生产仅 worker 镜像安装转换、页面渲染与中文字体依赖，不增加容器，不依赖 Agent 沙盒，也不放入 API 镜像。CD 在切换服务前实际执行 DOC／XLS／PPT 转换、内容读取及 Office→PDF→PNG 页面预检，失败则停止发布。手动检查可在 worker 环境运行 `python -m app.integrations.parsing.office_preflight`。回滚保留原件及分段；旧 worker 不能继续解析新增格式，需恢复带转换依赖的版本或让用户上传新格式。

### 长文件与图文内容读取

发送后先准备有界的文字范围。短文件正文直接提供给主模型，长文件可按需继续提取和搜索后续范围；不再把首次提取上限当作文件结尾。表格保留单元格定位、日期及公式保存值，不执行公式刷新或外部数据更新；隐藏内容及不支持对象仍明确标注。

图表、扫描件和版式通过文档页面图片补充。Word／PPT／表格按需由 worker 生成 PDF，再用 Poppler 渲染指定页面；PDF 直接渲染。页面图片随正常主模型请求提供，不增加一个单独的图片描述模型或固定核对轮次。模型需要支持图像输入；纯文字读取不需要渲染。Word 页码是“转换后第 N 页”，可能与本机 Office 排版不同；表格页面按指定工作表生成，精确计算仍使用单元格数据。

本地页面读取还需 `pdftoppm` 在 PATH 中（macOS：`brew install poppler`；Debian／Ubuntu：`sudo apt-get install poppler-utils fonts-noto-cjk`；Windows 配置 Poppler 的 bin 目录）。缺少页面依赖时保留可读正文并提示图片未读到，不会自动换模型。上传本身仍然不解析、不渲染、不调用 Agent。

处理后的文件存放在媒体目录的 `.documents/`，与原件身份和解析／转换版本绑定，首次处理后复用。它们是持久化附件产物，随附件保留和删除，不按页数或短期 TTL 淘汰，也不设总量或单附件累计容量额度。提取的文字随附件保存在数据库中，附件删除时一并清理。

每次转换／渲染仍为单次最多 32 MiB 输出预留空间，并保留至少 512 MiB 磁盘空闲；跨 worker 共享重任务槽位。实际磁盘空间不足时只停止新的对应页面准备，已读正文、已有页面和原文件仍保留；扩容磁盘或正常删除不再需要的附件后可重试。不要手工清空 `.documents/`，否则历史页面预览会失效。成功保存到工作中的文件有独立原件，源聊天删除后仍可读取或重建页面。

### 旧本地容器迁移

升级前先退出 API、worker、Web 和独立沙盒命令，再执行：

```sh
npm run dev:web:migrate
npm run dev:web
```

迁移器检查端口、数据库连接与在途任务，将数据库备份恢复到隔离容器核对，再用原数据库镜像、数据卷与沙盒持久卷创建统一项目。只有健康与数据核对成功后才移除旧容器外壳；不会删除数据卷或镜像。外部数据库、Redis 和远程沙盒不迁移。沙盒 socket 使用新卷，执行镜像缓存沿用原引擎数据。

资源映射、旧配置、数据库备份和沙盒控制状态保存在 `data/company/local-infra/`，包含本机凭据，不要提交或公开。迁移完成后使用开发命令管理容器，不用未带资源映射的原始 Compose 命令重新创建数据库。

失败会尝试恢复旧拓扑。中途强制退出或需要回退时，退出应用后执行：

```sh
npm run dev:web:migrate -- rollback
```

回滚继续使用原持久卷，保留迁移后的业务数据；它不把数据库还原到旧时间点。不要删除 `local-infra/` 或原卷。若报告仍有活动连接／任务，先退出对应进程或等待任务结束，不要强行清理卷。生产部署与 CD 不受此次本地迁移影响。

### 本地代码执行与文件生成

Docker 启动后，执行一次 `npm run sandbox:setup`。首次下载并构建镜像，自动向已有 `apps/server/.env.web` 写入本地地址和随机沙盒密钥，保留其他配置。升级代码后先执行 `npm run db:company`。

之后 `npm run dev:web` 会一起启动沙盒，`Ctrl+C` 停止本次启动的沙盒服务，保留镜像和缓存。沙盒使用独立 Docker 引擎和 gVisor，不修改系统 Docker 配置；接口仅监听本机 `127.0.0.1:8011`，默认同时执行 1 个任务。

分开调试时可用 `npm run sandbox:start`、`npm run sandbox:status`、`npm run sandbox:stop`。已手动启动的沙盒不会随 `dev:web` 退出而停止。仅需普通聊天时，将 `PAA_SANDBOX_LOCAL=false` 并清空 `PAA_SANDBOX_URL` 后重启。

已运行的沙盒仅在源码、镜像和配置一致时复用。若提示需要更新，等待任务结束并退出开发命令，执行 `npm run sandbox:stop`，再执行 `npm run sandbox:start`（或 `npm run dev:web`）；启动命令不会自动重建其他命令正在使用的沙盒。

### 模型用途分配

管理员保存模型服务后，在“用途分配”中设置文字模型、语音转写和图片生成。聊天搭子与日报周报生成共用文字模型；聊天可按账号选择思考强度，报告使用模型设置中的初始强度。

升级后优先沿用原工作助手模型；仅配置过报告模型时沿用该模型，请求参数统一取模型设置。旧任务继续使用已绑定的配置，新任务使用合并后的用途；无需数据库迁移或重新分配模型。

### 图片生成

管理员在“系统设置 → 模型服务管理”为服务添加图片模型，选择图片接口；保存服务后，在“用途分配 → 图片生成”选择该模型。此用途独立于聊天和语音，留空不影响已有功能。已有 `wan2.7-image` 配置无需重新填写。

内置 Wan 模型可自动匹配阿里 Token Plan 同步图片接口和百炼原生异步接口。已有 Token Plan 服务可以复用原 Base URL 和密钥，无需另建服务或手改路径。其他模型可手动选择“同步多模态”或“异步图片”接口，只要服务兼容对应请求与响应格式、返回 PNG 图片，就无需修改代码；协议不同的服务仍需增加适配器。服务地址支持根域名、`/api/v1` 或 `/compatible-mode/v1`，不会跨服务域名转发密钥。实际模型权限、额度及可用性以服务商返回为准。

尺寸可选择自动、服务商默认或固定尺寸。自动模式为已知模型带入规则：`wan2.7-image` 支持 1K／2K，`wan2.7-image-pro` 另支持 4K，二者默认 2K；未知模型不会套用 Wan 的尺寸规则。不清楚模型尺寸能力时选择服务商默认，未指定尺寸的请求不发送 size；固定尺寸模式可逐个输入“宽*高”并按 Enter 添加，再选择默认尺寸。

用户在聊天中直接提出“生成一张咖啡店海报”“画一张 16:9 的横向封面”等需求。明确像素优先，比例按该模型的尺寸规则处理；不支持的尺寸会给出说明，不通过循环重试或静默换尺寸生成。聊天的 low／high 不控制图片模型。当前仅文字生图，不支持修改上传图片或参考原图生成。

生成结果保存为会话中的私有 PNG 成果，可预览、下载，尺寸以实际图片为准。刷新或下载重试复用原结果；若提示外部生成结果尚无法确认，先查看原任务状态，避免重复要求生成。需要另一张图时，在下一条消息中明确提出。管理员主动点击图片配置测试会实际生成一张测试图；保存配置和刷新模型列表不会生成图片。

该功能调用外部图片服务，不需要新增容器、GPU 或启用代码沙盒。升级时照常执行数据库迁移并重启 API、worker；新增操作表用于恢复图片任务，不改变已有工作、会话与模型配置。

### 跨会话记忆

在“设置 → 记忆”管理本人跨会话记忆。默认开启，可直接编辑“我的记忆” Markdown（最多 6,000 字符），保存后用于其它会话；自动记忆可能需要纠正，以这里保存的内容为准。开关独立保存，关闭后停止提供和新增／更新记忆，已有内容保留，当前会话前文仍可继续承接。关闭时也可以手动编辑、清空或在对话中明确要求忘记。

删除聊天不会删除已保存记忆；清空记忆不删除聊天原文或已有备份，也不能撤回已经发给模型的内容。管理员只管理自己的记忆，删除员工账号会清理该账号记忆。编辑期间如有其它会话更新，保存会提示冲突并保留草稿；先查看最新内容再合并。

### 发送与查看附件

工作助手支持选择、粘贴、拖入附件，可混发图片、文档和语音。每条最多 9 个附件，其中语音最多 3 段；单图最多 30 MiB／2,000 万像素，文档和语音每个最多 20 MiB，每段语音最长 3 分钟。支持 MP3、HEIC／HEIF；HEIC 预览会上传转换，发送时复用，不创建聊天消息。

图片可放大，PDF 可翻页和下载。XLSX 读取可见单元格及已有公式结果，不重算；不识别隐藏内容、扫描件、图表和嵌入图片。

### 记录工作与让助手协助

在“我的工作”中只填标题即可创建，再逐步补充正文、清单、图片和文件。正文单独保存；“记录新进展”追加动态，不覆盖方案。状态和截止日期可独立修改，进展可更正或删除并保留历史。

每次添加材料最多 9 个，其中语音最多 3 段；单图 30 MiB，文档和语音每个 20 MiB。材料保存后随工作可见，解析失败可重试。工作可以分次积累材料。

点击“让助手协助”将一项工作引用带入最近聊天。可以先分析材料、修改方案；明确要求保存时才更新正文、记录进展或保存指定成果。已保存到工作的文件不受源聊天删除影响，未保存的聊天内容仍保持私有。报告根据期间进展生成，不把未来计划算作已完成工作。

### 公司声纹

管理员在“系统设置 → 公司声纹”登记员工单人录音，须经本人知情同意。建议 30～120 秒，最长 3 分钟、最大 20 MiB，中英文均可；替换失败保留原声纹。

删除员工账号会同时清除其服务端声纹及登记录音。文件清理失败会自动重试，并可在公司声纹页查看状态、手动重试。旧版本留下的已删除成员资料须先预览，再明确清理；升级不会自动删除。

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

[生产 Compose](../deploy/company/compose.yml) 在 Linux 运行 Caddy、API、worker、PostgreSQL 和 Redis，启动前执行迁移。Web／API 同源 HTTPS，数据库与 Redis 不暴露公网；聊天和 ASR 调用外部服务。

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

发布顺序：构建镜像／拉取 PostgreSQL 和 Redis → 检查配置和密钥 → 停止 Web／API 接收新请求，最多等待 480 秒排空任务 → 停写备份 → 迁移／Redis 健康检查 → 启动 API／worker／Web → 检查 HTTPS、数据库与 worker。排空超时保持维护状态，由运维检查，不把混合版本部署当作无损滚动升级。回滚同样先停入口并排空任务，沿用已有备份恢复流程。备份位于部署目录 `backups/`、`key-backups/`，需另外异机保存。

首次构建下载依赖，后续复用 Docker 缓存；构建会占用服务器资源。工作流超时 60 分钟，服务器发布超时 50 分钟。镜像按本地 image ID 固定，勿清理 `current/`、`previous/` 引用的镜像。

Web 缓存由 `deploy/company/Caddyfile.app` 管理：HTML（含前端路由）和固定文件名资源使用 `no-cache`，保留 ETag 校验；`/assets/` 下带构建哈希的资源使用 `public, max-age=31536000, immutable`。缺失静态文件返回不缓存的 404，不回退成首页。API、私有文件及流式响应沿用后端的缓存规则。部署不会强制刷新已打开的页面；此前缓存的旧页面可能仍需手动刷新一次。

`current/` 指向本次尝试，`previous/` 保留旧版本，结果在 `deployment-status`。构建／配置检查失败不停止旧服务，备份失败尝试恢复旧服务；迁移或上线检查失败则停用应用并保留数据，不自动启动旧代码。schema 变化须按备份恢复，不能只切旧镜像。排障命令：`sh /srv/work-assistant-agent/current/deploy/company/compose.sh logs --tail=100 api worker migrate`。

旧手工部署接入 CD 时沿用部署根目录、`.env.company`、主密钥和 `paa-company` 数据卷；发布脚本将旧配置链接到新版本 `apps/server/.env.web`。续期 cron 和日常备份改用 `current/deploy/company/` 下的脚本。

### 自部署代码沙盒

沙盒用于运行 Python、分析文件和生成 Excel、Word、PDF、PPT；普通问答不依赖沙盒。每次执行使用独立环境，生成文件随会话保留。

常规操作使用五个内置工具，无需用户配置：

| 工具 | 输入与结果 |
| --- | --- |
| `inspect_table` | 附件／成果中的 CSV、XLSX；返回列、缺失、重复和最多 20 行样本 |
| `export_table` | 内联表格或文件引用；导出 CSV、XLSX |
| `create_chart` | 指定横轴与数值列；生成中文柱状图／折线图 PNG |
| `create_document` | 标题、段落、列表、表格、图片；生成 DOCX、PDF |
| `create_slides` | 页面标题与内容块；生成可编辑 PPTX，长内容自动拆页 |

常规文件可直接说“把这份计划生成 PDF”。工具不自动清洗、汇总或执行公式；特殊算法与布局仍可用 `run_python`。CSV 默认保留文本与前导零，指定列类型后才转换。表格最多 40 列、20000 行（内联最多 2000 行）；图表最多 60 行，重复类别需先明确汇总规则。文档宽表超过 8 列、PPT 表格超过 6 列或单行过长会明确失败。格式可读与视觉排版检查是不同事项。

内置任务参数示例（由模型提交，不要求用户手写）：

```json
{
  "filename": "实施计划.pdf",
  "format": "pdf",
  "title": "实施计划",
  "blocks": [{"type": "paragraph", "text": "先确认需求，再完成验证。"}]
}
```

`run_python` 也可 `from noria_tools import export_table`，调用 `export_table(filename="结果.xlsx", data={"columns":["数量"],"rows":[[3]]})`。文件引用使用真实附件或成果 ID，不传宿主机路径；每次执行是新环境，继续处理使用已保存成果。


Linux 执行主机先按 [gVisor 安装说明](https://gvisor.dev/docs/user_guide/install/)安装 `runsc` 并注册到 Docker。安装或调整 Docker 配置安排在维护时段；CD 只检查运行时，不自动安装。使用完整发行包及其校验文件，保留 `runsc` 同目录的 `gvisor-bin/`，不能只复制单个可执行文件。

确认隔离运行时可用：

```sh
docker run --rm --runtime=runsc --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --user=65532:65532 \
  --memory=1g --memory-swap=1g --cpus=1 busybox:1.37 uname -r
```

输出应包含 `gvisor`。在已有 `apps/server/.env.web` 补充以下配置，控制令牌使用至少 32 字节随机值，不提交 Git：

```dotenv
COMPOSE_PROFILES=sandbox
PAA_SANDBOX_URL=http://sandbox:8010
PAA_SANDBOX_TOKEN=替换为随机控制令牌
SANDBOX_CONCURRENCY=1
SANDBOX_MEMORY_MIB=1024
SANDBOX_CPUS=1
SANDBOX_TIMEOUT_SECONDS=60
PAA_GENERATED_QUOTA_MB=512
PAA_GENERATED_TOTAL_QUOTA_MB=4096
```

先构建执行镜像，再按原域名／IP Compose 或 CD 流程发布：

```sh
docker build -f deploy/company/Dockerfile.sandbox --target runner \
  -t noria-sandbox-runner:local .
```

升级内置工具时同时更新控制服务与 runner 镜像，再执行数据库迁移并启动业务服务；只更新 API 不会把工具装入旧镜像。本地重新执行 `npm run sandbox:setup` 后运行 `npm run db:company`。旧 Python 请求及历史成果兼容，无需新增环境变量。

CD 启用此配置后会构建并固定控制服务与执行镜像版本。并发 `1` 是资源测试起点，达到上限才排队；提高前需测量整机内存、文档渲染与业务 API 响应。控制服务只在内网提供接口；Docker 控制 socket 仅供可信管理服务使用，不挂入生成代码的环境。

生成文件默认每人最多 512 MiB、全站最多 4 GiB；达到配额时停止新增，不删除已交付文件。调整上限前确认媒体卷的可用空间。

本地真实执行同样需要支持 `runsc` 的 Docker daemon，可用 `DOCKER_HOST` 指向独立测试环境。默认 Docker Desktop 未注册 `runsc` 时不能直接启用，不回退为宿主 Python。未配置沙盒时，其余助手能力照常使用。

关闭功能时清空 `PAA_SANDBOX_URL`，停用沙盒 profile 并重启应用；保留数据库及媒体数据卷，历史成果仍可下载。

### 钉钉登录配置

1. 取得企业内部应用开发管理权限，可管理凭证、接口权限、可用范围、安全设置和发布。
2. 创建企业内部应用，取得 **CorpId、AppKey／Client ID、AppSecret／Client Secret**；开通 `open_app_api_base`、`Contact.User.Read`、`qyapi_get_member` 并发布。通讯录授权与应用可用范围均限于允许登录的员工，无需考勤、审批或消息权限。
3. 回调为 **`PAA_WEB_ORIGIN` + `/api/v1/auth/dingtalk/callback`**；在实际应用后台登记并验证，尤其是公网 IP 回调。
4. 单公司可留空 `PAA_LOGIN_COMPANY_ID`；多公司须在 `apps/server/.env.web` 指定公司 UUID 并重启 API，否则钉钉入口关闭。
5. 在“系统设置 → 登录方式”保存配置、试登录后开启入口；Secret 留空保留原值。凭证、授权码、Token 和回调查询参数不入 Git、截图或日志。

首次登录为已核验且允许的成员创建员工账号；已有账号需主动验证绑定，不按姓名合并，钉钉管理员不自动成为系统管理员。用户可设置本地密码；关闭钉钉前确认所需密码可用。删除账号会撤销已有登录；如需阻止再次通过钉钉注册，请在钉钉侧移除其应用授权。

成员管理提供姓名编辑、重置密码和删除，不再提供启停。删除撤销登录、停止待处理任务和提醒，保留历史业务，释放账号名及钉钉绑定。重建账号不继承旧资料；历史记录在团队看板的全部／停用成员范围查看。

升级后执行一次历史停用员工清理（正常员工、管理员不受影响）：

```sh
# 本地，仓库根目录
PYTHONPATH=apps/server:packages/voiceprint-engine/src .venv-server/bin/python -m app.cli cleanup-inactive-members
# 服务器，使用当前部署配置
sh /srv/work-assistant-agent/current/deploy/company/compose.sh exec -T api python -m app.cli cleanup-inactive-members
```

先按备份流程保存数据库和媒体。命令复用账号删除流程，不物理删除历史成员行；输出 `deleted`、`failed`、`remaining`、`cleanupPending`、`cleanupFailed`、`cleanupErrors`。账号或文件清理失败、仍有停用员工或文件待清理时退出码为 1；排障后可重复执行，已完成账号不会重复处理，待清理文件继续重试。代码回滚不会恢复已删账号或录音。

上线验证首次开户、再次登录、密码设置、外部及范围外成员拒绝，并用实体手机验证授权返回。

钉钉登录按浏览器限制 10 分钟 12 次发起，同一出口 IP 允许每分钟 120 次；共享公司网络不会共用一个低额度。计数保存在 PostgreSQL，进程重启不会清零。浏览器使用独立的短期 HttpOnly 标识，与授权 state、登录会话分开；清除标识仍受 IP 限流保护。超限返回 `Retry-After`，页面提示等待时间，不自动重试。

生产 Caddy 与 API 使用专用 `proxy` 网络，API 只信任 Caddy 的固定地址，Caddy 覆盖外部传入的转发头；API 不发布宿主端口。默认网段为 `172.30.254.0/29`，Caddy 固定为 `172.30.254.2`，API 固定为 `172.30.254.3`，避免 API 先启动时自动占用 Caddy 地址。部署预检查使用不接入该网络的临时 worker 容器，不占用在线 API 的固定地址。如与现有 Docker／内网路由冲突，在部署环境同时调整 `PAA_PROXY_SUBNET`、`PAA_PROXY_IP` 和 `PAA_API_PROXY_IP`，确保两个地址不同且均在该网段内。域名和 IP 两种部署均通过现有 CD 应用，不需要数据库迁移。此配置假定 Caddy 是公网入口；增加 CDN 或其他前置代理时，须另行配置并验证可信来源链，不能直接信任任意转发头。

登录并发复验使用隔离测试数据库和本地 Docker Desktop：先准备与当前依赖一致的 API `service` 镜像，再运行 `PAA_TEST_LOGIN_PROXY_IMAGE=<镜像名> npm run test:server -- tests/server/modules/auth/test_login_proxy.py -s`。该检查使用当前源码、生产 Caddy 转发规则和模拟钉钉响应，覆盖 50／100 个独立浏览器集中登录及伪造转发头，不调用真实钉钉或模型服务，也不代表云服务器容量承诺。

登录后配置模型用途。手机录音需要有效 HTTPS，局域网 HTTP 不满足条件，锁屏后不保证持续录音。

### 使用问题与反馈

在“问题反馈”描述操作和现象，管理员跟进处理。诊断只附请求编号、错误类型和浏览器信息，不自动附聊天、文件或密钥；服务不可用时可复制反馈。

发送超时先恢复原消息状态，不自动重发。会话过期后，同页面的草稿可在原账号重新登录后恢复；刷新、关页或切换账号不保留。

按请求编号查 API 日志，日志不含业务正文。手机检查覆盖 Safari／Chrome 的真实键盘、权限和录音，不只看窄屏模拟。

### 后台处理与汇报安排

生产 worker 及子进程的资源由 `PAA_WORKER_CPUS`、`PAA_WORKER_MEMORY` 配置，默认 2 核、3 GiB，禁用 swap；超出 CPU 会限速，超内存可能 OOM。此限制不约束镜像构建。

`PAA_WORKER_CONCURRENCY` 默认 `3`，范围 `1～8`；不同员工并行，同员工串行，仅运行一个 worker。提高并发需检查模型限流与内存。

每个处理槽一个 checkpoint 连接，另有进程锁连接；API／worker 各自的事务连接池由 `PAA_DB_POOL_SIZE`（默认 2）和 `PAA_DB_MAX_OVERFLOW`（默认 1）控制。连接预算为 `并发槽数 + 1 + API 池上限 + worker 池上限`，另留迁移、运维和临时进程余量。PostgreSQL 的 `PAA_POSTGRES_MAX_CONNECTIONS`、`PAA_POSTGRES_SHARED_BUFFERS` 默认分别为 20、64MB。

8 核／16 GiB 单机可从以下配套配置起步，写入服务器持久环境文件（现有 CD 使用的 `.env.company` 或 `apps/server/.env.web`），后续发布继续沿用：

```dotenv
PAA_WORKER_CONCURRENCY=6
PAA_WORKER_CPUS=4
PAA_WORKER_MEMORY=4g
PAA_DB_POOL_SIZE=5
PAA_DB_MAX_OVERFLOW=5
PAA_POSTGRES_MAX_CONNECTIONS=60
PAA_POSTGRES_SHARED_BUFFERS=256MB
SANDBOX_CONCURRENCY=2
```

该配置的应用连接预算为 27，数据库上限 60；聊天等待外部模型时仍占用处理槽，硬件升级不意味着任务无限并发。沙盒执行容器单独占用资源，不能只看 control 容器的内存限制。增加 API 进程或任务并发前重新核算总连接与内存，并验证模型服务限流；这些参数不是并发容量承诺。修改后需排空任务并重建 PostgreSQL、API、worker 容器，不能只重启旧容器；不需要数据库迁移。

语音转换每进程最多 2 个；退出等候 10 秒，Compose 留 20 秒。结果未知的已发送模型请求由用户确认重试，未发出的可恢复排队。

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

产物位于 `dist/desktop/`，以 Noria 命名：macOS ARM64 为 DMG，Windows x64 为 NSIS。安装包内置 Python、录音与转写依赖；模型仍由用户在应用内下载。`npm run package:dir` 只生成应用目录。

尚无正式签名、公证和自动更新。macOS 切换开发版／安装版或重建后可能请求钥匙串授权；安装和卸载保留用户资料。

## 数据存放

Noria 桌面端沿用旧内部名称对应的目录和密钥身份，品牌更新不会迁移或清空已有资料。

| 内容 | 位置 |
| --- | --- |
| macOS 桌面资料 | `~/Library/Application Support/个人工作助手/` |
| Windows 桌面资料 | `%APPDATA%/个人工作助手/` |
| 公司业务数据 | PostgreSQL；原始附件在共享私有目录，生产环境默认使用 Docker 卷 |
| 公司密钥 | 数据库保存密文，主密钥单独保管；本地默认为 `data/company/model-master.key` |

桌面备份须关闭应用并复制整个资料目录；公司备份保留数据库、附件及独立主密钥。环境文件、密钥和业务资料不入 Git。

### 正文流缓存

API／worker 使用 `PAA_REPLY_STREAM_REDIS_URL`（开发默认 `redis://127.0.0.1:6379/0`，Compose 使用私网服务名）。Redis 7.4.2 关闭持久化，最大内存 64 MiB、容器 128 MiB、拒绝容量外的新写入。每次生成快照和增量各最多 480 KiB、最多 256 个事件，另预留 64 KiB 元数据空间，活跃 TTL 15 分钟；终态清除正文并留下短期防迟到写入标记。可用 `PAA_REPLY_STREAM_NAMESPACE` 隔离测试键，禁止清空共享实例。

Redis 不可用或预览达到预算时，界面提示实时预览不可用；任务继续生成并保存最终答案，不截短答案、不退回高频正文写库。刷新／离开页面不取消任务；明确点击中断才封存仍有权限的片段。API 重启可恢复 Redis 中尚存的快照；worker 或 Redis 崩溃可能丢失未保存尾部，已保存回复和工具回执不受影响。诊断日志 `paa.latency` 仅包含关联编号、阶段及计时，不记录正文或密钥；不同进程的单调时钟不能直接相减。
