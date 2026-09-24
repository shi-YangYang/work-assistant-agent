# 桌面工程基线

- main 管理无 shell 的 Python 子进程，以带请求 ID 的 UTF-8 JSON Lines／stdio 通信；音频不进入控制消息。
- renderer 只调用受限的类型化 preload 接口，不能直接访问文件、Node 或任意 IPC。
- 桌面使用 SQLite 和本地文件，不增加 HTTP 服务、PostgreSQL 或业务编排框架；模型通过 Provider 接入。
- `npm ci` 的 postinstall 显式准备 Electron 运行时，避免 electron-vite 找不到 `path.txt`。
