<p align="center">
  <img src="packages/ui-web/brand/desktop/app-icon.png" alt="work-assistant-agent Logo" width="120" height="120" />
</p>

<h1 align="center">work-assistant-agent</h1>

<p align="center">让 AI 参与工作记录、团队汇报与会议整理。</p>

<p align="center">
  <img src="https://img.shields.io/badge/React-20232A?style=flat-square&amp;logo=react&amp;logoColor=61DAFB" alt="React" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&amp;logo=typescript&amp;logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/Electron-47848F?style=flat-square&amp;logo=electron&amp;logoColor=white" alt="Electron" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python" />
  <br />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&amp;logo=fastapi&amp;logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square&amp;logo=langgraph&amp;logoColor=white" alt="LangGraph" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&amp;logo=postgresql&amp;logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&amp;logo=docker&amp;logoColor=white" alt="Docker" />
</p>

work-assistant-agent 是一个开源 AI 工作助手，包含面向团队协作的 **公司 Web** 和面向本地会议的 **Electron 桌面端**。员工通过对话记录工作，AI 整理进展与报告；会议录音经过本地转写，生成可回溯的纪要与行动项。

## 目录

[功能](#功能) · [安装](#安装) · [使用](#使用) · [技术栈](#技术栈) · [项目结构](#项目结构) · [部署与打包](#部署与打包) · [贡献](#贡献)

## 功能

### 公司 Web

- **对话式工作记录**：多会话聊天，支持文字、图片、网页录音与语音文件；可粘贴截图、拖入附件、预览图片和 PDF，修正语音转写。
- **文档理解**：解析 PDF、Word（DOCX）、PowerPoint（PPTX）、Excel（XLSX）、TXT、Markdown、CSV 和 JSON，结合材料处理工作。
- **工作与报告**：手动创建工作，或让助手创建、修改工作与报告草稿；支持日报、周报和汇报提醒，提交与删除前确认。
- **团队看板与问答**：管理员查看团队进度、阻碍和汇报情况，也可直接向助手提问；员工查询范围限定为本人资料。
- **模型服务管理**：配置多家服务，为工作助手、报告生成和语音转写分配模型，测试连通性并查看调用用量。
- **公司管理**：账号密码或钉钉登录；管理员管理成员、汇报规则，并登记成员声纹供桌面端使用。
- **使用反馈**：查看任务处理进度、恢复异常请求，提交问题反馈并跟进处理结果。

### Electron 桌面端

- **会议录制与回放**：支持暂停、继续、进度跳转、倍速播放和会议搜索。
- **本地语音转写**：多款 Whisper 模型，支持中文、英文及中英混合；可选择 CPU、Apple Silicon GPU 或受支持的 NVIDIA GPU，查看模型实测错误率和内存占用。
- **AI 会议纪要**：整理议题、发言人观点、决策、行动项及风险，区分会议结论与 AI 建议，可回到原文核对，支持 Markdown／TXT 导出。
- **说话人识别**：无需公司声纹也能区分不同说话人；同步声纹后可匹配成员姓名，支持会后校正与人工修改。文字记录可切换发言人／纯文本视图，纪要可选择是否使用发言人信息。

Web 适配电脑和手机浏览器；桌面端支持 macOS、Windows，可作为游客独立使用。会议资料保存在本机，不自动同步到公司服务；生成纪要时，所选文字会发送至配置的模型服务。

## 安装

源码运行需要 **Node.js 24、npm 11、Python 3.12**；公司 Web 另需 **Docker Compose、FFmpeg**。

```sh
git clone https://github.com/shi-YangYang/work-assistant-agent.git
cd work-assistant-agent
npm ci
```

首次运行先初始化对应应用：

| 应用 | 初始化内容 | 指南 |
| --- | --- | --- |
| 公司 Web | Python 依赖、环境配置、数据库与管理员账号 | [Web 初始化](docs/setup.md#公司-web) |
| 桌面端 | Python 依赖与本地核心 | [桌面初始化](docs/setup.md#electron-桌面端) |

## 使用

<a id="公司工作助手-webspec-008"></a>

### 公司 Web

初始化完成后，启动数据库和应用：

```sh
docker compose --env-file apps/server/.env.web -f deploy/company/compose.dev.yml up -d --wait
npm run dev:web
```

访问 [http://127.0.0.1:5174](http://127.0.0.1:5174)。管理员配置模型服务、添加成员后即可使用。

### Electron 桌面端

```sh
npm run dev:electron
```

在设置中下载转写模型、配置纪要模型，然后开始会议。模型下载后可离线转写，生成纪要需要在线模型 API。桌面安装包自带 Python，终端用户无需配置开发环境。

需要匹配员工姓名时，在 `apps/desktop/.env.electron` 设置 `PAA_DESKTOP_COMPANY_URL`，登录并同步公司声纹。留空为游客模式；本地会议无需公司后端。见[公司连接配置](docs/setup.md#连接公司与离线识别)。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | React、TypeScript、Vite、React Router |
| 桌面应用 | Electron、electron-vite |
| 服务端 | Python、FastAPI、Uvicorn |
| Agent | Deep Agents、LangGraph；通过 harness 管理工具权限、任务恢复与人工确认 |
| 数据存储 | PostgreSQL、SQLAlchemy、Alembic；桌面使用 SQLite |
| 语音处理 | faster-whisper／CTranslate2、MLX Whisper、sounddevice、FFmpeg |
| 说话人与声纹 | pyannote Community-1、WeSpeaker、PyTorch |
| 文档与媒体 | pypdf、python-docx、python-pptx、openpyxl、Pillow、PDF.js |
| 部署与打包 | Docker Compose、Caddy、electron-builder、PyInstaller |

## 项目结构

```text
apps/
  web/              公司 Web
  desktop/          Electron 应用与本地 Python 核心
  server/           公司 API、后台任务与 Agent
packages/           共享类型、模型参数、品牌资源与声纹引擎
scripts/            开发与构建脚本
tests/              各模块测试
deploy/             部署配置
docs/               安装指南与技术架构
```

模块职责和数据流见[技术架构](docs/architecture.md)，视觉与品牌见[设计规范](docs/design/README.md)。

## 部署与打包

- **公司 Web**：使用 Docker Compose 部署到 Linux，通过 HTTPS 提供访问；聊天与转写调用外部 API，声纹登记由后台 CPU 提取。见 [Web 部署与备份](docs/setup.md#web-部署)。
- **更新发布**：支持在 GitHub Actions 手动触发 Web 部署，在服务器构建并更新服务。见[发布配置](docs/setup.md#github-手动发布)。
- **桌面端**：在对应系统构建 macOS DMG 或 Windows 安装程序，打包内置 Python 核心。见[桌面打包](docs/setup.md#桌面打包)。目前尚未接入正式签名、公证和自动更新。

## 贡献

欢迎提交 [Issue](https://github.com/shi-YangYang/work-assistant-agent/issues) 或 Pull Request，参与问题修复、功能改进与文档完善。

## 维护者

[小洋（@shi-YangYang）](https://github.com/shi-YangYang)

## 许可证

[MIT](LICENSE) © 2026 小洋。

随包分发的说话人模型遵循各自许可证，见[模型署名与许可](apps/desktop/resources/models/speaker-community-1/NOTICE.md)。
