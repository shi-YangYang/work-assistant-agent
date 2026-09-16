<p align="center">
  <img src="packages/ui-web/assets/app-icon.png" alt="work-assistant-agent Logo" width="120" height="120" />
</p>

<h1 align="center">work-assistant-agent</h1>

<p align="center">让 AI 参与工作记录、团队汇报与会议整理。</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-345BD8?style=flat-square" alt="许可证：MIT" /></a>
  <a href="#功能"><img src="https://img.shields.io/badge/Clients-Web%20%7C%20macOS%20%7C%20Windows-596780?style=flat-square" alt="客户端：Web、macOS、Windows" /></a>
</p>

work-assistant-agent 是一个开源 AI 工作助手，包含面向团队协作的 **公司 Web** 和面向本地会议的 **Electron 桌面端**。员工通过对话记录工作，AI 整理进展与报告；会议录音经过本地转写，生成可回溯的纪要与行动项。

## 目录

[功能](#功能) · [安装](#安装) · [使用](#使用) · [技术栈](#技术栈) · [项目结构](#项目结构) · [部署与打包](#部署与打包) · [贡献](#贡献)

## 功能

### 公司 Web

- **对话式工作记录**：发送文字、图片、语音和文档，支持截图粘贴、文件拖拽、图片与 PDF 预览。
- **工作与报告**：AI 提取工作进展，经用户确认后更新工作事项；生成日报、周报草稿，支持编辑提交与汇报提醒。
- **团队看板与问答**：管理员查看团队进度、阻碍和汇报情况，也可直接向助手提问；员工查询范围限定为本人资料。
- **模型服务管理**：配置多家服务，为工作助手、报告生成和语音转写分配模型，测试连通性并查看调用用量。

### Electron 桌面端

- **会议录制与回放**：支持暂停、继续、进度跳转、倍速播放和会议搜索。
- **本地语音转写**：多款 Whisper 模型，支持中文、英文及中英混合，可选择 CPU 或受支持的 GPU 推理。
- **AI 会议纪要**：生成摘要、决策与行动项，关联原始转写和录音，支持 Markdown／TXT 导出。

Web 适配电脑和手机浏览器；桌面端支持 macOS、Windows，录音与转写保存在本机。两端目前独立运行，数据与模型配置不自动同步。

## 安装

源码运行需要 **Node.js 24、npm 11、Python 3.12**；公司 Web 另需 **Docker Compose、FFmpeg**。

```sh
git clone https://github.com/shi-YangYang/work-assistant-agent.git
cd work-assistant-agent
npm ci
```

选择要运行的应用，先完成一次环境初始化：

| 应用 | 初始化内容 | 指南 |
| --- | --- | --- |
| 公司 Web | Python 依赖、环境配置、数据库与管理员账号 | [Web 初始化](docs/setup.md#公司-web) |
| 桌面端 | Python 依赖与本地核心 | [桌面初始化](docs/setup.md#electron-桌面端) |

## 使用

<a id="公司工作助手-webspec-008"></a>

### 公司 Web

初始化完成后，启动数据库和应用：

```sh
docker compose --env-file .env.company -f deploy/company/compose.dev.yml up -d --wait
npm run dev:company
```

访问 [http://127.0.0.1:5174](http://127.0.0.1:5174)。该命令同时启动 Web、API 和后台任务。管理员登录后配置模型服务、添加成员，员工即可在工作助手中发送记录。

### Electron 桌面端

```sh
npm run dev
```

在设置中下载转写模型、配置纪要模型，然后开始会议。模型下载后可离线转写，生成纪要需要在线模型 API。桌面安装包自带 Python，终端用户无需配置开发环境。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | React、TypeScript、Vite、React Router |
| 桌面应用 | Electron、electron-vite |
| 服务端 | Python、FastAPI、Uvicorn |
| Agent | Deep Agents、LangGraph；harness 管理工具权限、任务恢复与人工确认 |
| 数据存储 | PostgreSQL、SQLAlchemy、Alembic；桌面使用 SQLite |
| 语音处理 | faster-whisper／CTranslate2、MLX Whisper、sounddevice、FFmpeg |
| 文档与媒体 | pypdf、python-docx、python-pptx、openpyxl、Pillow、PDF.js |
| 部署与打包 | Docker Compose、Caddy、electron-builder、PyInstaller |

## 项目结构

```text
apps/
  web/              公司 Web
  desktop/          Electron 应用与本地 Python 核心
services/
  company/          公司 API、后台任务与 Agent
packages/           共享类型、模型配置与界面样式
scripts/            开发与构建脚本
tests/              各模块测试
deploy/             部署配置
docs/               安装指南与技术架构
```

应用通过 npm workspaces 组织，桌面 Python 核心与公司服务使用各自的依赖环境。模块职责和数据流见[技术架构](docs/architecture.md)。

## 部署与打包

- **公司 Web**：使用 Docker Compose 部署到 Linux，通过 HTTPS 提供访问；模型推理调用外部 API。见 [Web 部署与备份](docs/setup.md#web-部署)。
- **桌面端**：在对应系统构建 macOS DMG 或 Windows 安装程序，打包内置 Python 核心。见[桌面打包](docs/setup.md#桌面打包)。目前尚未接入正式签名、公证和自动更新。

## 贡献

欢迎提交 [Issue](https://github.com/shi-YangYang/work-assistant-agent/issues) 或 Pull Request，参与问题修复、功能改进与文档完善。

## 维护者

[小洋（@shi-YangYang）](https://github.com/shi-YangYang)

## 许可证

[MIT](LICENSE) © 2026 小洋。
