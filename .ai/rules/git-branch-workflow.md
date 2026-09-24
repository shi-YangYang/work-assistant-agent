# Git 分支工作规则

- 长期保留 `dev`、`main`，默认在 `dev` 开发，不为普通任务另开分支。
- 仅在用户要求时 commit／push；仅本地提交不推送。不触发 CI 的要求也适用于 PR 更新和手动工作流。
- 推送后提供 `dev → main` 的 HTTP(S) PR 链接；没有 PR 时提供创建页，说明区别，不重复创建。
- 用户确认当前提交的必需检查并合并；Agent 不自动合并、不默认等待 CI，只报告对应提交的已知结果。
- 优先普通 merge commit。合并后在 `dev` 执行 `git pull --no-rebase origin main`、`git push origin dev`；Agent 仅在另行授权后操作。
- 保留用户修改和他人提交，不用强制推送、reset 或丢弃内容解决冲突。内容未变的回同步不重复验证。
- 不删除长期分支；临时分支仅可清理本任务创建且已安全合并、推送的分支。
