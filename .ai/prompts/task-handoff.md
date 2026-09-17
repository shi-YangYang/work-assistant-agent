# 当前交接

[桌面公司连接与员工声纹](../../specs/spec-022-company-voiceprints/spec.md)已实现，[软件与真实模型验证通过](../../specs/spec-022-company-voiceprints/acceptance.md)。Mac 锁屏阻止原生交互，解锁后待补默认日常环境的桌面登录、同步、实际录音和离线重启操作；Windows／发行包及完整 Docker 构建未执行。不要重复已通过的定向检查。

开发库迁移前备份为 `artifacts/spec022/company-before-voiceprints.dump`；升级至 `0011_company_voiceprints`。本地 `.env.company` 已配置现有 `.venv` 为声纹提取运行环境，`npm run dev:company` 启动公司端，`npm run dev` 启动桌面。临时账号、声纹及录音已清理；最小实测结果在 `artifacts/spec022/`。

保留已有用户数据、密钥与下载模型。
