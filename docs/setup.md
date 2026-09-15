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

麦克风不可用时，到系统隐私设置允许访问后重启。开发版和安装版使用同一资料目录时，不要同时运行。

## Web 部署

[生产 Compose](../deploy/company/compose.yml) 在 Linux 上运行 Caddy、API、worker 和 PostgreSQL，自动先执行数据库迁移。Web 与 API 同源，通过 HTTPS 提供访问；数据库不暴露公网端口。服务器调用外部 AI／ASR API，不部署桌面的 faster-whisper。

部署前准备域名、Docker Compose 和 `.env.company`：

- 域名解析到服务器，开放 80／443；设置 `PAA_DOMAIN` 和 `PAA_WEB_ORIGIN=https://你的域名`。
- 设置数据库随机密码；在仓库与镜像之外创建一次 **32 字节随机主密钥文件**，所属 UID 为 `10001`、权限为 `600`。
- 将 `PAA_MODEL_KEY_HOST_PATH` 指向该文件的绝对路径。API 与 worker 只读共享它，文件缺失时不会自动创建；升级时不能重新生成。

```sh
docker compose --env-file .env.company -f deploy/company/compose.yml up --build -d
docker compose --env-file .env.company -f deploy/company/compose.yml exec api python -m paa_server.cli bootstrap-admin
```

部署完成后登录 Web 配置模型用途。手机录音需要有效 HTTPS，访问开发电脑的局域网 HTTP 地址不满足条件，也不保证锁屏后持续录音。

### 备份与恢复

升级前设置两个独立私有目录：`PAA_BACKUP_DIR` 存数据库／附件，`PAA_MODEL_KEY_BACKUP_DIR` 存主密钥，再从仓库根运行：

```sh
sh deploy/company/backup.sh
```

脚本会暂停写入服务，保存 PostgreSQL dump、附件、镜像信息与校验文件，然后恢复服务；业务备份保留最近 7 份，密钥备份独立保存。运维需将两类备份分别复制到受控异机位置。

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
