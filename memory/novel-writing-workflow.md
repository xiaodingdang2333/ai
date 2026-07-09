# 小说创作统一工作流

本文件是仓库内所有小说任务的可迁移入口。无论使用哪个 Codex 账号、哪台服务器或网页写作流程，只要工作区来自本仓库，都必须执行以下规则。

## 2026-07-09 流程废弃声明

旧的“网页自定义 GPT + `services/novel-actions` 服务器 Action + 服务器保存正文/上传”的小说生产流程已废弃，之后不再使用这套流程作为写作、修订、QA、上传或长任务执行主线。相关 `openapi-gpt.json`、4操作RPC、`runNovelWorkflow`、`runFanqieWorkflow`、`getNovelJob`、`saveNovelAssets`、`next_action.action/payload_schema` 等规则只作为历史事故记录保留，不得作为当前执行依据。

当前网页版小说生产的权威流程是 `/home/admin/chatgpt-novel-production-system` 最新 `main` 中的 2.2-LTS Git 仓库工作流：网页版 ChatGPT 按仓库协议写作、审查、修订并上传 Git；服务器/Codex 后续若要吸收能力，必须围绕该 Git 仓库的 `CURRENT.json`、active ruleset、章节产物、current-blob P0 evidence、handoff snapshot、sample registry 等可审计文件重新设计，不得复活旧 Action 流程。

## 2026-07-09 Git 驱动的网页/服务器分工

- 主要写作默认由网页版 ChatGPT 执行，以节约服务器 Codex token；网页版必须使用 `/home/admin/chatgpt-novel-production-system` 的 2.2-LTS Git 工作流和同一套质量标准。
- 服务器侧只通过 Git 队列接收任务：样本需求在 `sample-requests/pending/*.json`，样本结果在 `sample-results/<request_id>/status.json`，显式服务器代写请求在 `server-write-requests/pending/*.json`，番茄上传就绪由各小说 `00_PROJECT.json` 的上传字段声明。
- 服务器样本流水线默认脚本化完成发现、合法性判断、SoNovel/允许来源获取、清洗、packet、基础统计和 Git 回写；只有请求显式写明 `analysis_engine=server_codex`、`allow_codex=true`、`codex_scope=packet_deep_teardown` 时，才允许服务器 Codex 对 packet 做深度拆书。
- 样本请求必须使用 5 倍候选池：需要 N 本有效样本时，网页提交至少 N*5 本候选，设置 `min_effective_samples=N`、`max_attempts=N*5`；服务器按顺序尝试，成功够 N 本即停止。失败或不足时，网页自动补同题材备用样本，默认最多 3 轮；第 3 轮仍失败才提示换赛道/扩大平台/人工材料。
- 服务器任务进度默认看 8090 网页 `/novel-jobs`，由 Git 状态文件只读展示 sample/upload/server-write 任务。ChatGPT 不默认高频轮询，避免长会话卡顿；用户在聊天里问进度时再读取 Git 状态回答。
- 番茄草稿上传由服务器扫描 Git 中 `upload_status=ready_for_draft_upload` 的项目后执行，必须核验 `fanqie_account`、`expected_author_name`、`fanqie_book_id`、`ai_use`、QA 证据和 current-blob 证据；默认只上传草稿，不自动发布。
- 服务器代写只在请求显式写明 `allow_server_codex=true`、`target_mode=continue_formal`、`quality_profile=v2.2-LTS-strong` 时执行；这会消耗服务器 Codex quota。代写完成后仍必须跑 2.2-LTS P0/READY 质量门禁，番茄上传 worker 还会独立复验，不能只凭网页或服务器自称“已通过”上传。
- 多个网页版会话可以并行写不同书，但每本书必须有独立项目/分支/状态文件，通过 Git 快照接力，不依赖单个长聊天保存全部上下文。
- 服务器已新增 Git worker 入口：`/home/admin/ai/scripts/novel-git-poller.py`、`novel-git-sample-worker.py`、`novel-git-upload-worker.py`；对应 systemd 模板在 `/home/admin/ai/systemd/`。worker 默认 dry-run，execute 模式才写文件/上传，且 Git 回写只提交本轮生成路径，不强推。
- 服务器 Git worker 还包括 `/home/admin/ai/scripts/novel-git-write-worker.py`，用于上述显式代写队列。当前 timer：poller 每1分钟，upload 每1分钟，write 每2分钟，sample 每5分钟。

## 强制读取顺序

1. `memory/user-profile.md`
2. `memory/workflow-preferences.md`
3. 新书构思：`codex/skills/fanqie-novel-ideation/SKILL.md`
4. 八项原创门禁：`codex/skills/fanqie-novel-ideation/references/originality-gate.md`
5. 写作与上传：`codex/skills/fanqie-write-upload/SKILL.md`
6. 网页 2.2-LTS Git 工作流：`/home/admin/chatgpt-novel-production-system/CURRENT.json`

## 不可绕过的总流程

- 新书先按官方榜单拆书，只提取功能 DNA，不复制正文、名字、标志性事件或情节序列。
- 男频榜单严格按`起点→飞卢→七猫→番茄`降级；女频严格按`晋江→七猫→番茄`降级。当前平台失败或整批不足3本有效样本后才能切下一平台。
- 执行八项原创门禁和`12→3→用户选1`；用户选择前不得建书或写正文。
- 选定后首次只写3章，每章至少2500个中文汉字，通常约3000字；用户批准后才能继续。
- 后续每批开始前确认章数/字数及自动上传或人工检阅；正文按1到4章建立强制创作合同。每章先规划主角目标、阻力、关键选择、代价、状态变化、情绪回报、类型兑现和独立结构指纹，再执行“候选稿→独立批评→实际返修→重新验收→原子检查点→QA”；验收必须重建角色、时序、物件和现实约束模型，并为每项判断提交返修正文证据与推理，不能只勾选通过。最多返修3轮，仍有中高风险问题则停下交人工。段末再做跨章审稿；任一步未通过不得进入下一章。
- 写作必须读取项目设定、大纲、追踪状态和最近章节；完成后更新细纲、上下文、人物、时间线、伏笔、完整章节索引和结构化状态。历史修订同样执行合同、自审、逐章QA和段末审稿，不能由网页直接批量生成后一次机械验收。
- QA必须检查字数、重复、格式、标题、连续性、场景因果、跨书换皮和AI模板痕迹；失败不得上传。
- 【已废弃，不再执行】旧网页自定义GPT曾要求使用`openapi-gpt.json`的4操作RPC、`action + payload_json`、`next_action.action/payload_schema`、服务器检查点和`context_get`分页等机制。这套 Action 流程已废弃，之后不得按这些机制继续组织小说写作、修订、QA或上传。
- 当前网页版写作必须以 2.2-LTS Git 仓库流程为准：正文、审查、修订、QA证据、handoff 和样本状态都以 Git 仓库文件为权威，不以旧 Action 数据库、旧服务器 checkpoint 或网页聊天记录为权威。
- 默认只上传番茄草稿，不自动发布；账号、作品ID和平台草稿必须逐章验收。
- 【旧Action流程规则已废弃】没有`book_id`时从服务器模糊查找、旧稿修订批次、逐章暂存和QA晋级等规则只适用于已废弃的 `novel-actions` 流程；当前不得用它作为网页写作主线。旧稿续写/修订应优先通过 Git 仓库项目文件和本地正式正文定位。

具体阈值、字段和操作命令以对应技能及`workflow-preferences.md`的最新版本为准，不得用聊天记忆覆盖仓库规则。
