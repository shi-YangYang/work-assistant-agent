<p align="center">
  <img src="packages/ui-web/brand/logo.png" alt="Noria 小熊 Logo" width="160" height="160" />
</p>

<h1 align="center">Noria</h1>

<p align="center">面向公司的云端工作助手。</p>

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

Noria 是一个开源的公司工作助手。你可以通过浏览器提问、分析材料、查询公开资料和生成文件，再按需要把成果保存到工作或周报。Electron 桌面端用于会议录音、本地转写和 AI 纪要。

公司服务可部署在自己的云服务器或内网。Web 适配电脑和手机；桌面端支持 macOS、Windows，也可独立使用。

## 从这里开始

| 你想做什么              | 阅读入口                                                                                 |
| ----------------------- | ---------------------------------------------------------------------------------------- |
| 使用公司已经部署的服务  | 浏览器打开公司地址，用管理员提供的账号登录；[功能与使用说明](docs/setup.md#模型用途分配) |
| 在本机运行公司 Web      | [开发环境安装](docs/setup.md#公司-web)                                                   |
| 运行桌面会议应用        | [桌面端安装](docs/setup.md#electron-桌面端)                                              |
| 部署、更新或备份服务器  | [Web 部署](docs/setup.md#web-部署)                                                       |
| 了解代码和数据流        | [技术架构](docs/architecture.md)                                                         |
| 验证 Agent 的回答和操作 | [本地评测](eval/README.md)                                                               |
| 查看设计依据和验收结果  | [规格索引](specs/README.md)                                                              |

## 主要功能

### 公司 Web

- **问答与材料分析**：多会话聊天、联网查询，读取文档、图片和语音，连续修改方案与文稿。旧版 Office 和文档页面读取需安装相应依赖。
- **文件与图片生成**：启用沙盒后，可分析表格、运行 Python、绘图并生成 Office／PDF 文件；图片生成使用管理员单独配置的图片模型。
- **工作与周报**：管理工作正文、清单、附件和进展；手动准备周报，或按管理员的汇报安排审阅、提交。正式报告只保留周报。
- **团队与公司管理**：管理员查看团队进度和汇报情况，管理成员、模型服务、用量、登录方式、声纹及问题反馈。

助手的执行权限按账号设置，适用于所有会话。员工只访问本人资料，管理员的团队查询仍受服务端权限控制。工具显示成功并不代替你对内容的检查。

### 桌面会议

- **录音与回放**：暂停、继续、进度跳转、倍速播放和会议搜索。
- **本地转写与说话人识别**：支持中文、英文及混合语音；按设备选择 CPU、Apple Silicon GPU 或受支持的 NVIDIA GPU。同步公司声纹后可匹配姓名，也可手动更正。
- **AI 纪要**：整理议题、观点、决策和行动项，回到原文核对，导出 Markdown／TXT。

会议资料保存在本机，不自动上传公司服务。下载模型后可离线转写；生成纪要时，所选文字会发送到配置的模型服务。

## 源码运行

需要 **Node.js 24、npm 11、Python 3.12**。公司 Web 另需 Docker Compose 和 FFmpeg。

```sh
git clone https://github.com/shi-YangYang/work-assistant-agent.git
cd work-assistant-agent
npm ci
```

先按[安装指南](docs/setup.md)完成 Python、环境配置和数据库初始化，再启动对应应用：

```sh
npm run dev:web       # 公司 Web：http://127.0.0.1:5174
npm run dev:electron  # 桌面会议应用
```

两条命令按需要选择，不要求同时运行。公司 Web 的开发命令会管理本地数据库、Redis 和已启用的沙盒；桌面本地会议不依赖公司后端。

## 项目结构

```text
apps/web/           浏览器界面
apps/server/        公司 API、后台任务与 Agent
apps/desktop/       Electron 应用与本地 Python 核心
apps/sandbox/       隔离代码执行与文件生成
packages/           共享类型、模型参数、品牌资源和声纹引擎
scripts/            开发、构建与运维脚本
tests/              普通自动化测试
eval/               本地 Agent 测试集、评分器与真实流程评测
deploy/             部署配置
docs/               安装、架构与设计说明
constitution/       产品方向与工程约定
specs/              需求、实施方案与验收记录
.ai/                项目决策与协作规则
```

前端使用 React／TypeScript，服务端使用 FastAPI／PostgreSQL，Agent 基于 Deep Agents／LangGraph，桌面端使用 Electron 与 Python。完整版本和工程命令见[技术栈](constitution/tech-stack.md)。

## 发布与贡献

公司 Web 通过 Docker Compose 部署；GitHub Actions 的手动发布流程负责构建、备份、迁移和更新。[部署说明](docs/setup.md#github-手动发布)包含所需配置和恢复步骤。可选沙盒需要 gVisor/runsc，不能用普通容器替代隔离执行。

桌面安装包自带 Python，产物为 macOS DMG 或 Windows 安装程序。见[打包说明](docs/setup.md#桌面打包)；目前尚未接入正式签名、公证和自动更新。

欢迎提交 [Issue](https://github.com/shi-YangYang/work-assistant-agent/issues) 或 Pull Request。维护者：[小洋（@shi-YangYang）](https://github.com/shi-YangYang)。

## 许可证

[MIT](LICENSE) © 2026 小洋。随包分发的模型另有许可证，见[模型署名与许可](packages/voiceprint-engine/resources/models/speaker-community-1/NOTICE.md)。
