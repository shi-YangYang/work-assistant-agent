# Task Handoff — Spec 003 CI 修复后的独立验收

## Role / Goal / Project Mode

新的 Acceptance Agent / EXISTING。只写 acceptance.md，不修改业务、测试、配置，不创建子 Agent，不 commit / push。原两轮失败报告均保留。Spec 决策无需子 Agent 验证；本次仅验收已授权的实际工程。

## Required Reading

AGENTS.md、constitution/mission.md / tech-stack.md、.ai/rules/、Spec003 spec.md / plan.md / implementation.md / implementation-rework-1.md / implementation-ci-rework.md / verification.md、acceptance-round-1.md / acceptance-round-2.md、rework.md 和当前相关 diff。主Agent提供最终代码提交及其实际双平台CI证据。

## Context / Focus

- 原实现已覆盖模型下载、独立worker、持久任务、Transcript、历史补转写和退出恢复。第一轮暂停与已选块竞态已修复，共同控制锁与不可复用token，经第二轮独立审查成立。
- d7013c9首个真实CI中macOS慢worker测试等running超时，Windows真实ASR业务断言成功但打印中文JSON遇到cp1252编码失败，后续smoke未运行。此次只针对真实失败修复，不能靠skip、放宽业务断言或更换模型取得绿色。
- 独立检查测试修复是否仍真正证明慢推理期间录音帧增长/积压/非阻塞停止、供帧不依赖不可控定时；Windows控制台ASCII转义JSON与UTF8原文报告是否可读、断言和真实Provider不变。
- 真实固定两分钟参考CER6.52%、44.659秒；用户批准的物理声学回采37.035秒、首字18.383秒、CER15.56%，补尾/重启/定位实际播放通过。最终Provider10秒纯静音words=[]的独立证据在final-provider-silence.json。代码/参数未改变时复用，不重复。

## Validation Boundary

先审查CI修复的具体diff、实施证据和新版对应macOS/Windows任务/实际日志。当前问题属于测试与报告输出的S2相关交互，原业务S3基础证据可复用。只有具体未覆盖问题才执行最小探测，不重复已通过测试来提高主观信心。

最终PASS必须有对应业务代码提交的双平台依赖/真实模型/新增Electron任务成功证据；清楚记录每个平台真正运行及旧Windows4项平台受限skip。Windows物理麦克风/最低配置/安装包仍未验证，不能额外承诺。主Agent若仍在等CI，则先交代码审查结论并等待，不提前PASS。

## Output

只在已修复且必要检查通过时写最终PASS。否则明确FAIL和具体返工目标。区分本轮独立审查/独立执行与复用证据，标明所有报告和原始证据路径；没有具体新问题、需求和必要验证均满足后停止，不追加探索。
