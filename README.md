<p align="center">
  <img src="packages/ui-web/assets/app-icon.png" alt="work-assistant-agent Logo" width="120" height="120" />
</p>

<h1 align="center">work-assistant-agent</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-345BD8?style=flat-square" alt="许可证：MIT" /></a>
  <a href="#功能"><img src="https://img.shields.io/badge/Clients-Web%20%7C%20macOS%20%7C%20Windows-596780?style=flat-square" alt="客户端：Web、macOS、Windows" /></a>
</p>

<p align="center">记录会议、整理工作汇报，让团队进展清晰可查。</p>

## 目录

[功能](#功能) · [安装](#安装) · [使用](#使用) · [技术栈](#技术栈) · [部署与打包](#部署与打包) · [如何贡献](#如何贡献)

## 功能

| 公司工作助手 · Web | 桌面会议助手 · macOS / Windows |
| --- | --- |
| 通过文字、图片、语音和文件汇报工作 | 录制会议，支持暂停、继续和回放 |
| AI 整理工作进展，确认后生成日报、周报草稿 | 使用本地 Whisper 模型转写录音 |
| 多会话管理，查询自己的工作和报告 | 在线生成会议纪要、决策和行动项 |
| 管理员查看团队看板、进展和阻碍 | 搜索会议、定位原文与录音、导出纪要 |

Web 适配电脑与手机，可粘贴截图、拖入文件，混合发送图片、文档和语音，支持 MP3、HEIC 照片及 PDF、DOCX、PPTX、XLSX、TXT、JSON、Markdown、CSV。图片和 PDF 可直接预览；扫描件暂不支持文字识别。管理员可维护成员、汇报规则和模型服务。

桌面提供多款转写模型，支持中文、英文和中英混合。录音与转写保存在本机，模型下载后可离线转写；在线 AI 功能需要配置模型服务。

**Web 与桌面端目前独立存储，数据和模型配置不自动同步。**

## 安装

使用已部署的 Web 只需浏览器和账号；桌面安装包自带 Python。以下为源码运行方式。

准备 **Node.js 24、npm 11、Python 3.12、Git**；公司 Web 还需要 **Docker 和 FFmpeg**。

```sh
git clone https://github.com/shi-YangYang/work-assistant-agent.git
cd work-assistant-agent
npm ci
```

首次运行需完成对应环境初始化：[公司 Web](docs/setup.md#公司-web) · [Electron 桌面端](docs/setup.md#electron-桌面端)。指南包含 macOS／Linux 和 Windows 命令。

## 使用

<a id="公司工作助手-webspec-008"></a>

### 公司 Web

```sh
docker compose --env-file .env.company -f deploy/company/compose.dev.yml up -d --wait
npm run dev:company
```

打开 [http://127.0.0.1:5174](http://127.0.0.1:5174)，使用初始化时创建的管理员账号登录。

在“模型服务管理”选择服务商、填写密钥并添加模型，再为工作助手、报告生成和语音转写分配用途。之后创建员工账号，即可开始汇报工作；员工确认工作进展、审阅并提交报告，管理员从团队看板查看结果。

### Electron 桌面端

```sh
npm run dev
```

在设置中下载本地转写模型、配置纪要模型，然后点击“开始会议”。会议结束后查看转写和纪要，可回放录音或导出 Markdown／TXT。

## 技术栈

| 部分 | 技术与用途 |
| --- | --- |
| 界面 | React、TypeScript、Vite；React Router 负责 Web 路由 |
| 桌面应用 | Electron，提供 macOS／Windows 窗口与系统能力 |
| 服务端 | Python、FastAPI、Uvicorn，提供公司 API 和后台任务 |
| Agent | Deep Agents、LangGraph；通过 harness 管理工具调用、任务状态与人工确认 |
| 数据存储 | PostgreSQL 存储公司数据，SQLite 存储桌面资料；SQLAlchemy、Alembic 管理服务端数据访问与迁移 |
| 语音与媒体 | faster-whisper、CTranslate2 用于桌面本地转写；sounddevice 录音，FFmpeg 处理音频，Web 转写调用外部 API |
| 文件解析与预览 | pypdf、python-docx、python-pptx、openpyxl 提取文档与表格；Pillow／pillow-heif 处理图片，PDF.js 预览 PDF |
| 部署与打包 | Docker Compose、Caddy 部署 Web；electron-builder、PyInstaller 打包桌面应用和 Python 核心 |
| 测试与检查 | Vitest、pytest、unittest、Playwright、ESLint、Prettier |

## 部署与打包

公司 Web 使用 Docker Compose 部署到 Linux，通过 HTTPS 供电脑和手机访问。模型推理调用外部 API，服务器无需部署桌面转写模型。

桌面端在对应系统打包，生成 macOS DMG 或 Windows 安装程序。目前桌面包尚未接入正式签名、公证和自动更新。

操作步骤：[Web 部署与备份](docs/setup.md#web-部署) · [桌面打包](docs/setup.md#桌面打包)。

## 如何贡献

欢迎通过 [Issues](https://github.com/shi-YangYang/work-assistant-agent/issues) 反馈问题，或向 `main` 提交 PR。较大的功能改动请先讨论方案。

<details>
<summary>开发与 CI</summary>

### CI 分层

PR 运行格式、Lint、类型、单元／模块测试和普通构建，覆盖 macOS、Windows 及公司 Web／API。完整桌面流程、真实转写和安装包检查按手动选项运行；`v*` 标签运行完整检查，不自动发布。

普通分支推送不会单独触发 CI，但推送到已有 PR 的分支会更新检查。具体配置见 [CI 工作流](.github/workflows/ci.yml)，开发结构见[技术架构](docs/architecture.md)。

</details>

## 维护者

[小洋（@shi-YangYang）](https://github.com/shi-YangYang)

## 许可证

[MIT](LICENSE) © 2026 小洋。
