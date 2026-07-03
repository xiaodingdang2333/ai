# 小说创作统一工作流

本文件是仓库内所有小说任务的可迁移入口。无论使用哪个 Codex 账号、哪台服务器或网页自定义 GPT，只要工作区来自本仓库，都必须执行以下规则。

## 强制读取顺序

1. `memory/user-profile.md`
2. `memory/workflow-preferences.md`
3. 新书构思：`codex/skills/fanqie-novel-ideation/SKILL.md`
4. 八项原创门禁：`codex/skills/fanqie-novel-ideation/references/originality-gate.md`
5. 写作与上传：`codex/skills/fanqie-write-upload/SKILL.md`
6. 网页自定义 GPT：`services/novel-actions/custom-gpt-instructions.md`

## 不可绕过的总流程

- 新书先按官方榜单拆书，只提取功能 DNA，不复制正文、名字、标志性事件或情节序列。
- 男频榜单严格按`起点→飞卢→七猫→番茄`降级；女频严格按`晋江→七猫→番茄`降级。当前平台失败或整批不足3本有效样本后才能切下一平台。
- 执行八项原创门禁和`12→3→用户选1`；用户选择前不得建书或写正文。
- 选定后首次只写3章，每章至少2500个中文汉字，通常约3000字；用户批准后才能继续。
- 后续每批开始前确认章数/字数及自动上传或人工检阅；内部每批最多4章。
- 写作必须读取项目设定、大纲、追踪状态和最近章节；完成后更新细纲、上下文、人物、时间线和伏笔。
- QA必须检查字数、重复、格式、标题、连续性、场景因果、跨书换皮和AI模板痕迹；失败不得上传。
- 默认只上传番茄草稿，不自动发布；账号、作品ID和平台草稿必须逐章验收。

具体阈值、字段和操作命令以对应技能及`workflow-preferences.md`的最新版本为准，不得用聊天记忆覆盖仓库规则。
